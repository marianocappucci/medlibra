"""La migración `0021_patient_sequences` corre en LOS DOS MUNDOS.

1. **Base armada por las migraciones** — la tabla no existe y hay que crearla.
2. **Instancia viva** — el esquema lo armó `Base.metadata.create_all()` desde los
   modelos, así que la tabla YA existe cuando la migración llega. Un
   `create_table` pelado revienta con *relation already exists*, y desde LibraCore
   v1.48.0 una migración fallida aborta el deploy. Mismo escenario que
   `test_migracion_sin_users.py`, y la misma fixture.
"""
from alembic import command
from motor_de_test import TEST_DATABASE_URL
from test_migracion_sin_users import _cruda, _revision, base_limpia  # noqa: F401

PREVIA = "0020_medio_del_saldo"
NUEVA = "0021_patient_sequences"


def _hay_la_tabla() -> bool:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        return c.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'patient_sequences'"
        ).fetchone()[0] == 1


def test_mundo_1_la_crea_cuando_no_existe(base_limpia):  # noqa: F811
    command.stamp(base_limpia, PREVIA)
    assert not _hay_la_tabla(), "el control: la base no la tiene"

    command.upgrade(base_limpia, NUEVA)

    assert _hay_la_tabla()
    assert _revision() == NUEVA


def test_mundo_2_no_falla_si_create_all_ya_la_creo(base_limpia):  # noqa: F811
    """🔴 El que decide: la tabla ya está (la armó `create_all`) y la migración corre igual."""
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        c.execute("CREATE TABLE patient_sequences (name varchar(20) PRIMARY KEY, last integer NOT NULL)")
    command.stamp(base_limpia, PREVIA)

    command.upgrade(base_limpia, NUEVA)

    assert _hay_la_tabla()
    assert _revision() == NUEVA


def test_el_downgrade_la_saca(base_limpia):  # noqa: F811
    command.stamp(base_limpia, PREVIA)
    command.upgrade(base_limpia, NUEVA)

    command.downgrade(base_limpia, PREVIA)

    assert not _hay_la_tabla()
    assert _revision() == PREVIA
