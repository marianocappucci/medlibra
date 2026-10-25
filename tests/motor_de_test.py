"""Contra que motor corre la suite.

Por defecto SQLite en memoria, que es como corrio siempre. Con
`MEDLIBRA_TEST_DATABASE_URL` puesta, la suite entera va a ese motor -- es lo
que usa el job de PostgreSQL del CI.

🔴 **Por que hizo falta este modulo.** Hasta el 2026-08-09 los ocho archivos de
test llamaban a `create_app()` con la cadena `sqlite:///:memory:` **escrita a
mano**. Apuntar `DATABASE_URL` a un PostgreSQL real y correr la suite daba
**281 passed y cero tablas creadas en ese PostgreSQL**: la variable no la leia
nadie. Un falso verde de 281 tests que se lee exactamente igual que un gate que
funciona.

Va en un modulo y no en `conftest.py` porque los tests lo llaman como funcion:
un `conftest` se carga solo para las fixtures, no se importa por nombre.
"""
import os

#: Vacia salvo que el entorno la ponga. Se lee UNA vez, al importar: si un test
#: la cambiara a mitad de corrida, la mitad de la suite iria a un motor y la
#: mitad al otro, que es peor que cualquiera de los dos.
TEST_DATABASE_URL = os.environ.get("MEDLIBRA_TEST_DATABASE_URL", "").strip()


# 🔴 **PostgreSQL y nada mas.** Hasta el 2026-08-25 la suite caia a SQLite
# cuando la variable no estaba, y el CI corria las dos pasadas. El modo SQLite
# se retiro el 2026-08-12 para toda la familia: no chequea las FK, tipa
# dinamicamente y acepta cadenas donde la base pide enteros, asi que una corrida
# verde sobre el no dice nada del motor real.
#
# El guard va ACA porque este es el unico lugar donde se elegia el motor. Con el
# puesto, el predicado que preguntaba por el motor seria siempre True, asi que
# se saco junto con las tres ramas SQLite que colgaban de el.
if not TEST_DATABASE_URL.startswith("postgresql"):
    raise RuntimeError(
        "La suite de MedLibra necesita PostgreSQL: defini "
        "MEDLIBRA_TEST_DATABASE_URL (ej. "
        "postgresql+psycopg://medlibra:medlibra-ci@localhost:5432/medlibra). "
        "Sin esa variable la suite correria sobre SQLite, que es lo que se "
        "retiro el 2026-08-12: una suite verde sobre SQLite no dice nada "
        "sobre el motor real."
    )


# --- Una base por worker, y una plantilla para los tests con `admin_client` ----
# Cada test arranca de una base **nueva**, y rearmarla es lo que mas cuesta. Medido
# sobre PostgreSQL 16, por test (la suite corria 4 procesos y otras tres suites en
# la misma maquina, asi que valen las proporciones, no los milisegundos):
#
#     dejar la base con la cadena de auth (DROP SCHEMA + libraauth)     ~0,25 s
#     vaciar el schema (DROP SCHEMA)                                    ~0,04 s
#     `create_app()` sobre una base vacia                               ~1,0 s
#       (la mitad es `init_core_schema()`, la otra mitad el `create_all` del dominio)
#     `create_app()` sobre una ya armada (idempotente)                  ~0,22 s
#
# El mecanismo de las plantillas (una base por worker de xdist, `CREATE DATABASE ...
# TEMPLATE`, `FORCE` para echar las conexiones del test anterior) vive en
# `libracore.testing.pg_por_worker`; aca queda lo propio de MedLibra: que hay en
# cada plantilla y a quien se la damos.
#
# 🔑 **UNA sola base por worker** (ADR-044). Hasta el 2026-10-25 eran dos --el dominio
# (`medlibra_gw0`) y la de LibraCore/libraauth (`medlibra_core_gw0`)-- porque LibraCore y
# LibraGenda declaraban las dos una tabla `clients`; desde libragenda v0.14.0 la de la agenda es
# `agenda_clients` y el dominio, LibraAuth y LibraCore comparten la base, que es la forma de
# dev (unida), de un alta nueva y de un nodo de LibraEdge. La suite no define ninguna variable
# del core. **Solo hay una plantilla, la "armada"**, para los tests que la amortizan:
#
# - **armada**: lo que `admin_client` le hacia a la base antes de loguear (la cadena de auth y
#   `create_app()`: `init_core_schema`, `create_all`, el admin de bootstrap, los modulos). Solo la
#   ven los tests que piden `admin_client` (`staff_client` lo arrastra). Su `create_app()`
#   posterior es idempotente sobre ella, que es lo que el producto hace en cada arranque.
# - **vacio** (el resto, los que arman su propia app o prueban migraciones y arranque desde
#   cero): NO se restaura de ninguna plantilla. Se hace `DROP SCHEMA` y se migra solo la cadena
#   de auth: una instancia recien migrada con `libraauth-migrar`, sin el dominio ni el core. Con
#   una plantilla "vacia" esos tests cuestan mas y, de paso, ven EXACTAMENTE el estado de
#   partida de siempre, no uno equivalente.
#
# `TEST_DATABASE_URL` es la del worker: `from motor_de_test import TEST_DATABASE_URL`
# es como la leen los tests, asi que reasignarla aca alcanza.
#
# 🔴 Algo que ANTES no pasaba: `fresh_database_url()` ya **no vacia** nada. La base
# se deja lista UNA VEZ POR TEST en la fixture autouse (`limpiar_entre_tests`); si
# vaciara tambien aca, un test con `admin_client` perderia la plantilla armada.
# Ningun test llama `fresh_database_url()` dos veces ni despues de `admin_client`
# esperando una base vacia (verificado), asi que "una base nueva por test" alcanza.
from libracore.testing.pg_por_worker import base_por_worker  # noqa: E402


def _url_cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


_PG = base_por_worker("medlibra", TEST_DATABASE_URL)

# La URL del worker. Se lee UNA vez, como antes: `from motor_de_test import
# TEST_DATABASE_URL` es como la leen los tests, asi que reasignarla aca alcanza.
TEST_DATABASE_URL = _PG.url

# 🔴 Y tambien la variable de entorno. `POST /api/config/restore` corre las
# migraciones contra la base restaurada y se niega ("ninguna variable de entorno
# apunta a medlibra_gw0") si ninguna variable del proceso apunta a ESA base; antes
# era `medlibra`, que es la que decia la variable.
os.environ["MEDLIBRA_TEST_DATABASE_URL"] = TEST_DATABASE_URL


def _construir_auth(url: str) -> None:
    # Las tablas de auth viven en la misma base que el dominio y desde libraauth
    # v0.45.0 el arranque exige su cadena en vez de crearlas. Es el mismo orden
    # que el deploy, donde `libraauth-migrar` va antes de `libracore-migrar`.
    from libraauth.testing import crear_schema_de_auth

    crear_schema_de_auth(_url_cruda(url))


def _vaciar(url: str) -> None:
    """`DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`: la base de este worker, sin una sola tabla."""
    import psycopg

    with psycopg.connect(_url_cruda(url), autocommit=True) as conexion:
        conexion.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conexion.execute("CREATE SCHEMA public")


def limpiar_entre_tests(armar=None) -> None:
    """Deja la base del worker como nueva UNA VEZ POR TEST. La llama la fixture autouse.

    Sin argumentos: el estado **vacio**, el de siempre: sin tablas y solo con la cadena de
    auth. Con `armar` (una funcion `(url) -> None` que deja la base como la deja `admin_client`
    antes de loguear): el estado **armado**, restaurado de la plantilla, que se construye la
    primera vez (la cadena de auth y despues `armar`).

    🔴 La armada borra la base con `FORCE`: la app de un test deja su pool y sus
    conexiones vivas, y la plantilla no se puede copiar ni la base borrar con
    alguien adentro. El estado vacio no lo necesita (vaciar el schema alcanzaba
    antes), pero SI hace falta soltar antes el engine de LibraGenda: es un global
    del proceso que `configure()` reemplaza sin cerrar.
    """
    if armar is None:
        from libragenda.database import reset as soltar_engine_anterior

        soltar_engine_anterior()
        _vaciar(_PG.url)
        _construir_auth(_PG.url)
        return

    def _armada(url: str) -> None:
        _construir_auth(url)
        armar(url)

    _PG.restaurar("armada", _armada)


def fresh_database_url() -> str:
    """La URL para un `create_app()` nuevo: la base de este worker, **ya restaurada**.

    Cada test arma su propia app y espera una base limpia. De eso se encarga
    `limpiar_entre_tests()`, una vez por test, en la fixture autouse; esta
    funcion ya no vacia nada (ver el comentario de arriba).

    🔴 **Pero hay que soltar el engine anterior.** `libragenda.database.configure()`
    reemplaza el engine del proceso **sin hacerle `dispose()`**, asi que cada
    `create_app()` deja vivo un pool entero. Contra PostgreSQL son conexiones TCP
    que se acumulan: la suite completa reventaba a las 100 (`max_connections`)
    con **186 errores**, mientras cada archivo por separado pasaba en verde. El
    sintoma no se parece en nada a la causa.
    """
    from libragenda.database import reset as soltar_engine_anterior

    soltar_engine_anterior()
    return TEST_DATABASE_URL


def url_para_archivo(ruta) -> str:  # noqa: ARG001
    """La URL de una base **en archivo**, para los tests que necesitan que la
    base sobreviva a la app: backup, restore, migraciones.

    Contra PostgreSQL no hay archivo -- se devuelve el destino de este worker, ya
    restaurado. Existe porque esos tests tenian la URL SQLite **escrita a mano**, y
    entonces contra PostgreSQL quedaban a mitad de camino: el dominio en un
    archivo y LibraCore en la base nueva. El backup salia con una sola base y el
    test fallaba por el cableado del test, no por el producto.
    """
    return fresh_database_url()


def url_libracore() -> str:
    """La URL de la base de LibraCore: **la misma que la del dominio** (una sola base, ADR-044).

    Sigue existiendo con este nombre porque la leen los tests que miden el arranque y la ubicacion
    de las tablas de auth (`usuarios`, `alembic_version_libraauth`), que desde el ADR-044 estan en
    la base del dominio. Devuelve la forma `postgresql://` de psycopg.

    La forma de DOS bases (la demo, hasta que se una) la miden `tests/test_una_sola_base.py` y
    `tests/bases_temporales.py` con bases propias y descartables: no es la forma de la suite.
    """
    return _url_cruda(_PG.url)

