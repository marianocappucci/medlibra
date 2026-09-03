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


def fresh_database_url() -> str:
    """La URL para un `create_app()` nuevo, con la base vacia.

    Cada test arma su propia app y espera una base limpia. Con
    `sqlite:///:memory:` eso sale gratis: cada conexion nueva ES una base
    nueva. Un PostgreSQL, en cambio, es **uno solo y compartido** por toda la
    corrida, asi que hay que vaciarlo entre test y test o el segundo ve las
    filas del primero.

    Se borra el SCHEMA y no la base: `DROP DATABASE` exige que no quede ninguna
    conexion abierta, y el engine de la app del test anterior todavia puede
    tener una.

    🔴 **Y hay que soltar el engine anterior, no solo vaciar el schema.**
    `libragenda.database.configure()` reemplaza el engine del proceso **sin
    hacerle `dispose()`**, asi que cada `create_app()` deja vivo un pool
    entero. Con `sqlite:///:memory:` da igual -- es un `StaticPool` de una
    conexion que se recolecta sola -- pero contra PostgreSQL son conexiones TCP
    que se acumulan: la suite completa reventaba a las 100
    (`max_connections`) con **186 errores**, mientras cada archivo por separado
    pasaba en verde. El sintoma no se parece en nada a la causa.
    """
    import psycopg
    from libragenda.database import reset as soltar_engine_anterior

    soltar_engine_anterior()

    with psycopg.connect(
        TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1),
        autocommit=True,
    ) as conexion:
        conexion.execute("DROP SCHEMA public CASCADE")
        conexion.execute("CREATE SCHEMA public")
    return TEST_DATABASE_URL


def url_para_archivo(ruta) -> str:
    """La URL de una base **en archivo**, para los tests que necesitan que la
    base sobreviva a la app: backup, restore, migraciones.

    Contra PostgreSQL no hay archivo -- se devuelve el destino compartido, ya
    vaciado. Existe porque esos tests tenian la URL SQLite **escrita a mano**, y
    entonces contra PostgreSQL quedaban a mitad de camino: el dominio en un
    archivo y LibraCore en la base nueva. El backup salia con una sola base y el
    test fallaba por el cableado del test, no por el producto.
    """
    return fresh_database_url()


def _url_cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


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
    Mismo mecanismo que [[gestiolibra]], que llego a esto primero.
    """
    cruda = _url_cruda(TEST_DATABASE_URL)
    base, _, _ = cruda.rpartition("/")
    nombre = cruda.rsplit("/", 1)[1].split("?")[0]
    return f"{base}/{nombre}_core"


def _preparar_libracore() -> None:
    """Crea la base de LibraCore si no esta, y la deja vacia."""
    import psycopg

    cruda = _url_cruda(TEST_DATABASE_URL)
    servidor = cruda.rsplit("/", 1)[0] + "/postgres"
    nombre = cruda.rsplit("/", 1)[1].split("?")[0] + "_core"

    with psycopg.connect(servidor, autocommit=True) as conexion:
        existe = conexion.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)
        ).fetchone()
        if not existe:
            conexion.execute(f'CREATE DATABASE "{nombre}"')

    with psycopg.connect(url_libracore(), autocommit=True) as conexion:
        # `IF EXISTS` para que una corrida cortada a mitad no envenene las
        # siguientes dejando la base sin schema `public`.
        conexion.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conexion.execute("CREATE SCHEMA public")


def destino_libracore(ruta_sqlite) -> str:
    """El destino de la base de LIBRACORE (facturacion, caja, ARCA).

    🔴 **Esta era la mitad que la suite no ejercitaba.** El conftest le daba un
    archivo SQLite temporal aunque el resto de la corrida fuera a PostgreSQL,
    asi que el verde de este repo no decia nada sobre las ~340 consultas crudas
    de LibraCore.
    """
    _preparar_libracore()
    return url_libracore()
