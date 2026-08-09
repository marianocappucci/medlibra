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


def corre_contra_postgres() -> bool:
    return TEST_DATABASE_URL.startswith("postgresql")


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
    if not corre_contra_postgres():
        return "sqlite:///:memory:"

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
