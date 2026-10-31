"""La migración `0026_libraview` corre en LOS TRES MUNDOS (ADR-051).

1. **Base armada por las migraciones** — las tres tablas no existen: se crean, con sus índices (el único del número de acceso incluido).
2. **Instancia viva** — el esquema lo armó `Base.metadata.create_all()` desde los modelos nuevos, así que las tablas YA existen cuando la
   migración llega. Un `create_table` pelado revienta con *already exists*, y una migración fallida aborta el deploy.
3. **Instancia estampada sin ejecutar nada** — ni siquiera existen `study_orders` ni `study_order_items`. Es el mundo de
   `test_migracion_sin_users`, que estampa `0018` sobre un esquema vacío y sube a `head`: una clave foránea contra una tabla que no está
   hace fallar el `CREATE TABLE`. La migración se saltea lo que depende de ellas (sin pedidos no hay nada que enviar).

Mismo escenario y misma fixture que `test_migracion_walkin_called_at.py`.
"""
from alembic import command
from motor_de_test import TEST_DATABASE_URL
from test_migracion_sin_users import _cruda, _revision, base_limpia  # noqa: F401

PREVIA = "0025_walkin_called_at"
NUEVA = "0026_libraview"
TABLAS = ("envios_a_libraview", "estudios_en_libraview", "eventos_de_libraview")


def _ejecutar(sql: str) -> None:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        c.execute(sql)


def _consultar(sql: str) -> list[tuple]:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        return c.execute(sql).fetchall()


def _tablas() -> set[str]:
    return {t for (t,) in _consultar("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")} & set(TABLAS)


def _pedido_de_antes() -> None:
    """Las tablas a las que apuntan las claves foráneas (las crea la cadena de verdad; acá, lo mínimo)."""
    _ejecutar("CREATE TABLE study_orders (id varchar(100) PRIMARY KEY)")
    _ejecutar("CREATE TABLE study_order_items (id varchar(100) PRIMARY KEY)")


def test_mundo_1_crea_las_tres_tablas_y_el_indice_unico(base_limpia):  # noqa: F811
    _pedido_de_antes()
    command.stamp(base_limpia, PREVIA)
    assert _tablas() == set()

    command.upgrade(base_limpia, NUEVA)

    assert _tablas() == set(TABLAS)
    assert _revision() == NUEVA
    indices = {n for (n,) in _consultar("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
    assert {"ix_envios_a_libraview_estado", "ix_estudios_en_libraview_order_id", "ix_estudios_en_libraview_numero_acceso"} <= indices
    # Único cuando no es nulo: dos ítems preparados (sin número todavía) conviven; dos con el mismo número no.
    _ejecutar("INSERT INTO study_orders VALUES ('o')")
    _ejecutar("INSERT INTO study_order_items VALUES ('i1'), ('i2'), ('i3')")
    _ejecutar("INSERT INTO estudios_en_libraview VALUES ('i1', 'o', 'RX', NULL), ('i2', 'o', 'RX', NULL), ('i3', 'o', 'RX', '1')")
    import psycopg
    import pytest

    _ejecutar("INSERT INTO study_order_items VALUES ('i4')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _ejecutar("INSERT INTO estudios_en_libraview VALUES ('i4', 'o', 'RX', '1')")


def test_mundo_2_no_falla_si_create_all_ya_creo_las_tablas(base_limpia):  # noqa: F811
    """🔴 El que decide: las tablas ya están (las armó `create_all`) y la migración corre igual, sin tocarlas."""
    _pedido_de_antes()
    for tabla in TABLAS:
        _ejecutar(f"CREATE TABLE {tabla} (marca int)")
    command.stamp(base_limpia, PREVIA)

    command.upgrade(base_limpia, NUEVA)

    assert _revision() == NUEVA
    assert _tablas() == set(TABLAS)
    # No las tocó: siguen siendo las del test.
    assert [c for (c,) in _consultar(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'envios_a_libraview'")] == ["marca"]


def test_baja_y_vuelve_a_subir(base_limpia):  # noqa: F811
    _pedido_de_antes()
    command.stamp(base_limpia, PREVIA)
    command.upgrade(base_limpia, NUEVA)
    command.downgrade(base_limpia, PREVIA)
    assert _tablas() == set() and _revision() == PREVIA
    # Bajar con las tablas ya borradas (otro camino las sacó) tampoco falla.
    command.upgrade(base_limpia, NUEVA)
    _ejecutar("DROP TABLE eventos_de_libraview")
    command.downgrade(base_limpia, PREVIA)
    assert _tablas() == set()


def test_mundo_3_sin_las_tablas_de_pedidos_no_falla_y_se_saltea_lo_que_depende_de_ellas(base_limpia):  # noqa: F811
    """🔴 Lo que rompió el CI de medlibra#490: `test_migracion_sin_users` sube a `head` desde un esquema vacío y `0026` creaba
    `envios_a_libraview` con una clave foránea a `study_orders`, que ahí no existe."""
    command.stamp(base_limpia, PREVIA)
    assert _tablas() == set()

    command.upgrade(base_limpia, NUEVA)

    assert _revision() == NUEVA
    # Sólo la que no apunta a ninguna: las otras dos necesitan los pedidos.
    assert _tablas() == {"eventos_de_libraview"}
    command.downgrade(base_limpia, PREVIA)
    assert _tablas() == set() and _revision() == PREVIA
