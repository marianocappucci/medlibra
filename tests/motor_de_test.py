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
# Cada test arranca de bases **nuevas**, y rearmarlas es lo que mas cuesta. Medido
# sobre PostgreSQL 16, por test (la suite corria 4 procesos y otras tres suites en
# la misma maquina, asi que valen las proporciones, no los milisegundos):
#
#     dejar LibraCore con la cadena de auth (DROP SCHEMA + libraauth)   ~0,25 s
#     vaciar el dominio (DROP SCHEMA)                                   ~0,04 s
#     `create_app()` sobre las dos bases vacias                         ~1,0 s
#       (la mitad es `init_core_schema()`, la otra mitad el `create_all` del dominio)
#     `create_app()` sobre las dos ya armadas (idempotente)             ~0,22 s
#
# El mecanismo de las plantillas (una base por worker de xdist, `CREATE DATABASE ...
# TEMPLATE`, `FORCE` para echar las conexiones del test anterior) vive en
# `libracore.testing.pg_por_worker`; aca queda lo propio de MedLibra: que hay en
# cada plantilla y a quien se la damos.
#
# 🔴 **Son DOS bases por worker**, igual que antes (ver `url_libracore()`): la del
# dominio (`medlibra_gw0`) y la de LibraCore/libraauth (`medlibra_core_gw0`).
# Restaurar cuesta un `DROP DATABASE` por base, y ese fuerza un checkpoint: con dos
# bases por test una restauracion sale ~2x lo que un solo `DROP SCHEMA`. Por eso
# **solo hay una plantilla (por base), la "armada"**, y es para los tests que la
# amortizan:
#
# - **armada** (dominio y LibraCore): lo que `admin_client` le hacia a esas bases
#   antes de loguear (`create_app()`: `init_core_schema`, `create_all`, el admin de
#   bootstrap, los modulos). Solo la ven los tests que piden `admin_client` (387 de
#   508; `staff_client` lo arrastra). Su `create_app()` posterior es idempotente
#   sobre ella, que es lo que el producto hace en cada arranque.
# - **vacio** (el resto: 121 tests, los que arman su propia app o prueban
#   migraciones y arranque desde cero): NO se restaura de ninguna plantilla. Se
#   hace lo que se hacia hoy, sobre la base de este worker: dominio sin tablas y
#   LibraCore con solo la cadena de auth. Con una plantilla "vacia" esos tests
#   cuestan mas (medido: ~0,43 s con `DROP SCHEMA` contra ~1,05 s restaurando dos
#   bases) y, de paso, ven EXACTAMENTE el estado de partida de siempre, no uno
#   equivalente.
#
# Una plantilla por base y un estado de partida que no es de plantilla, entonces.
# `TEST_DATABASE_URL` es la del worker: `from motor_de_test import TEST_DATABASE_URL`
# es como la leen los tests, asi que reasignarla aca alcanza.
#
# 🔴 Algo que ANTES no pasaba: `fresh_database_url()` ya **no vacia** nada. La base
# se deja lista UNA VEZ POR TEST en la fixture autouse (`limpiar_entre_tests`); si
# vaciara tambien aca, un test con `admin_client` perderia la plantilla armada.
# Ningun test llama `fresh_database_url()` dos veces ni despues de `admin_client`
# esperando una base vacia (verificado), asi que "una base nueva por test" alcanza.
from libracore.respaldo_postgres import con_base  # noqa: E402
from libracore.testing.pg_por_worker import base_por_worker  # noqa: E402


def _url_cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _url_original_de_core(url_dominio: str) -> str:
    """La URL del servidor ORIGINAL de la base de LibraCore: `<dominio>_core`, en forma `postgresql://`."""
    from urllib.parse import urlsplit

    nombre = urlsplit(url_dominio).path.lstrip("/")
    return con_base(_url_cruda(url_dominio), f"{nombre}_core")


def _asegurar_la_base_original_de_core(url_dominio: str, url_core: str) -> None:
    """Crea `medlibra_core` si el servidor no la tiene: el helper se administra conectado a la base ORIGINAL.

    El servicio de PostgreSQL del CI solo trae `medlibra`. Corre en el proceso
    que lanza a xdist y en cada worker a la vez, asi que dos pueden intentar
    crearla juntos: perder esa carrera no es un error.
    """
    from urllib.parse import urlsplit

    import psycopg
    from psycopg import errors, sql

    nombre = urlsplit(url_core).path.lstrip("/")
    with psycopg.connect(_url_cruda(url_dominio), autocommit=True) as conexion:
        if conexion.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)).fetchone():
            return
        try:
            conexion.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
        except errors.DuplicateDatabase:
            pass


_PG = base_por_worker("medlibra", TEST_DATABASE_URL)

# 🔴 El servidor ORIGINAL se pide al helper y no a `TEST_DATABASE_URL`: mas abajo se
# pisa la variable con la URL del worker, y un worker de xdist hereda el entorno
# del proceso que lo lanza, o sea que leeria `medlibra_main` como si fuera el
# servidor y derivaria `medlibra_main_core`.
_URL_ORIGINAL_DE_CORE = _url_original_de_core(_PG.url_original)
_asegurar_la_base_original_de_core(_PG.url_original, _URL_ORIGINAL_DE_CORE)
_PG_CORE = base_por_worker("medlibra_core", _URL_ORIGINAL_DE_CORE)

# La URL del worker. Se lee UNA vez, como antes: `from motor_de_test import
# TEST_DATABASE_URL` es como la leen los tests, asi que reasignarla aca alcanza.
TEST_DATABASE_URL = _PG.url

# 🔴 Y tambien la variable de entorno. `POST /api/config/restore` corre las
# migraciones contra la base restaurada y se niega ("ninguna variable de entorno
# apunta a medlibra_gw0") si ninguna variable del proceso apunta a ESA base; antes
# era `medlibra`, que es la que decia la variable. La de LibraCore la pone la
# fixture `_dev_env` en `MEDLIBRA_LIBRACORE_DB_PATH`.
os.environ["MEDLIBRA_TEST_DATABASE_URL"] = TEST_DATABASE_URL


def _construir_auth(url: str) -> None:
    # Las seis tablas de auth viven en la base de LibraCore y desde libraauth
    # v0.45.0 el arranque exige su cadena en vez de crearlas. Es el mismo orden
    # que el deploy, donde `libraauth-migrar` va antes de `libracore-migrar`.
    from libraauth.testing import crear_schema_de_auth

    crear_schema_de_auth(url)


def _vaciar(url: str) -> None:
    """`DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`: la base de este worker, sin una sola tabla."""
    import psycopg

    with psycopg.connect(_url_cruda(url), autocommit=True) as conexion:
        conexion.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conexion.execute("CREATE SCHEMA public")


def limpiar_entre_tests(armar=None) -> None:
    """Deja las DOS bases del worker como nuevas UNA VEZ POR TEST. La llama la fixture autouse.

    Sin argumentos: el estado **vacio**, el de siempre: dominio sin tablas y
    LibraCore con solo la cadena de auth. Con `armar` (una funcion `(url_dominio,
    url_core) -> None` que deja las dos bases como las deja `admin_client` antes
    de loguear): el estado **armado**, restaurado de la plantilla, que se
    construye la primera vez.

    Cada plantilla se arma con la contraparte de PASO: la del dominio usa la base
    VIVA de LibraCore del worker (que se deja con la cadena de auth) y la de
    LibraCore usa la base VIVA del dominio, que para entonces ya esta armada. Asi
    cada `restaurar()` sigue siendo independiente y, si una falla a medias, el
    reintento no deja a la otra plantilla vacia.

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
        _vaciar(_PG_CORE.url)
        _construir_auth(_PG_CORE.url)
        return

    def _dominio_armado(url_dominio: str) -> None:
        _vaciar(_PG_CORE.url)
        _construir_auth(_PG_CORE.url)
        armar(url_dominio, _PG_CORE.url)

    def _core_armado(url_core: str) -> None:
        _construir_auth(url_core)
        armar(_PG.url, url_core)

    _PG.restaurar("armada", _dominio_armado)
    _PG_CORE.restaurar("armada", _core_armado)


def fresh_database_url() -> str:
    """La URL para un `create_app()` nuevo: la base del dominio de este worker, **ya restaurada**.

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
    """La URL de la base de LibraCore: **otra base**, en el mismo servidor.

    🔴 **No puede ser el mismo schema que el dominio, y esto no es preferencia.**
    LibraCore y LibraGenda declaran los dos una tabla `clients`, con formas
    incompatibles:

        LibraCore   clients.id  INTEGER PRIMARY KEY AUTOINCREMENT
        LibraGenda  clients.id  VARCHAR(100) PRIMARY KEY

    En SQLite vivian en dos ARCHIVOS distintos y nunca se cruzaban. En un solo
    schema hay una sola tabla: el segundo `CREATE TABLE IF NOT EXISTS` no hace
    nada y no avisa, y despues PostgreSQL rechaza el DDL de LibraCore con
    *"foreign key constraint cannot be implemented: Key columns are of
    incompatible types: integer and character varying"* -- son las nueve FK del
    core que apuntan a `clients(id)`.

    Dos bases en el mismo servidor es la traduccion fiel de los dos archivos, y
    es la topologia que va a necesitar tambien la instancia de produccion.
    Mismo mecanismo que [[gestiolibra]], que llego a esto primero. Ahora cada
    worker de xdist tiene la suya: `medlibra_core_gw0`, `medlibra_core_gw1`...
    """
    return _PG_CORE.url


def destino_libracore(ruta_sqlite) -> str:  # noqa: ARG001
    """El destino de la base de LIBRACORE (facturacion, caja, ARCA).

    No restaura nada: de eso se encarga `limpiar_entre_tests()`, una vez por test.

    🔴 **Esta era la mitad que la suite no ejercitaba.** El conftest le daba un
    archivo SQLite temporal aunque el resto de la corrida fuera a PostgreSQL,
    asi que el verde de este repo no decia nada sobre las ~340 consultas crudas
    de LibraCore.
    """
    return url_libracore()
