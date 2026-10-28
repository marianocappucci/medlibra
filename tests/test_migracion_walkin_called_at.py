"""La migración `0025_walkin_called_at` corre en LOS DOS MUNDOS (y sin la tabla).

1. **Base armada por las migraciones** — `walkins` existe sin la columna: hay que sumarla.
2. **Instancia viva** — el esquema lo armó `Base.metadata.create_all()` desde el modelo nuevo, así que la columna YA
   existe cuando la migración llega. Un `add_column` pelado revienta con *column already exists* y una migración
   fallida aborta el deploy. Mismo escenario que `test_migracion_patient_sequences.py`, y la misma fixture.
3. **Estampada sin la tabla** — `alembic stamp` no ejecuta nada: tampoco puede fallar.
"""
from alembic import command
from motor_de_test import TEST_DATABASE_URL
from test_migracion_sin_users import _cruda, _revision, base_limpia  # noqa: F401

PREVIA = "0024_libraedge"
NUEVA = "0025_walkin_called_at"


def _ejecutar(sql: str) -> None:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        c.execute(sql)


def _hay_la_columna() -> bool:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        return c.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'walkins' AND column_name = 'called_at'"
        ).fetchone()[0] == 1


def _tabla_de_antes() -> None:
    _ejecutar("CREATE TABLE walkins (id varchar(100) PRIMARY KEY, status varchar(20) NOT NULL)")


def test_mundo_1_suma_la_columna_y_conserva_las_filas(base_limpia):  # noqa: F811
    _tabla_de_antes()
    _ejecutar("INSERT INTO walkins VALUES ('w1', 'completed')")
    command.stamp(base_limpia, PREVIA)
    assert not _hay_la_columna(), "el control: la tabla no la tiene"

    command.upgrade(base_limpia, NUEVA)

    assert _hay_la_columna()
    assert _revision() == NUEVA
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        # lo anterior queda sin llamada: «no lo sabemos», no una hora inventada
        assert c.execute("SELECT id, called_at FROM walkins").fetchall() == [("w1", None)]


def test_mundo_2_no_falla_si_create_all_ya_la_creo(base_limpia):  # noqa: F811
    """🔴 El que decide: la columna ya está (la armó `create_all`) y la migración corre igual."""
    _tabla_de_antes()
    _ejecutar("ALTER TABLE walkins ADD COLUMN called_at timestamptz")
    command.stamp(base_limpia, PREVIA)

    command.upgrade(base_limpia, NUEVA)

    assert _hay_la_columna()
    assert _revision() == NUEVA


def test_sin_la_tabla_no_falla(base_limpia):  # noqa: F811
    command.stamp(base_limpia, PREVIA)

    command.upgrade(base_limpia, NUEVA)

    assert not _hay_la_columna()
    assert _revision() == NUEVA


def test_el_downgrade_la_saca(base_limpia):  # noqa: F811
    _tabla_de_antes()
    command.stamp(base_limpia, PREVIA)
    command.upgrade(base_limpia, NUEVA)

    command.downgrade(base_limpia, PREVIA)

    assert not _hay_la_columna()
    assert _revision() == PREVIA
