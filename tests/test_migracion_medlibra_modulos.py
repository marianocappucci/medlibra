"""La migración `0023`: `modulos` pasa a `medlibra_modulos` (ADR-043).

LibraCore tiene una tabla `modulos` con otra forma, y con una sola base por producto las dos no pueden llamarse
igual (`libracore-unir-bases` corta con `choque_de_tablas`). Se ensaya sobre PostgreSQL, **con datos** y en los
mundos en que puede caer:

1. **Instancia viva** (dev y demo): `modulos` es la de MedLibra, con filas. Se renombra con su contenido y su
   clave primaria, y baja y sube sin perder nada.
2. **Base nueva y unida**: `0011` ya creó `medlibra_modulos` y `modulos` es la del motor (con `id`). No se
   toca ninguna, ni al subir ni al bajar: borrar o renombrar la del motor sería llevarse sus filas.
3. **El arranque nuevo corrió antes de migrar**: `create_all()` dejó una `medlibra_modulos` sembrada y la
   `modulos` vieja sigue con lo que alguien configuró. Manda la vieja.

El esquema de partida se arma a mano (lo que dejó `0011` con el nombre de entonces): la cadena entera necesita
las tablas de LibraGenda, que el CI corre aparte, y lo que se mide acá es esta revisión.
"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from motor_de_test import TEST_DATABASE_URL

PREVIA = "0022_consultorio_recurso"
NUEVA = "0023_medlibra_modulos"

# `modulos` como la dejaba `0011_modulos` hasta el 2026-10-24.
MODULOS_DE_MEDLIBRA = """
    CREATE TABLE modulos (
        modulo VARCHAR(50) PRIMARY KEY,
        habilitado BOOLEAN NOT NULL DEFAULT true,
        plan VARCHAR(20) NOT NULL DEFAULT 'premium'
    )
"""
# `modulos` como la crea `libracore-migrar` (`libracore.db.schema`).
MODULOS_DEL_MOTOR = """
    CREATE TABLE modulos (
        id BIGSERIAL PRIMARY KEY,
        modulo TEXT NOT NULL UNIQUE,
        habilitado INTEGER NOT NULL DEFAULT 1,
        plan TEXT NOT NULL DEFAULT 'estandar'
    )
"""
FILAS = (("dashboard", True, "estandar"), ("senas", False, "basico"), ("resguardo_externo", True, "addon"))


def _cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _sql(sentencia: str, parametros=None):
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        cur = c.execute(sentencia, parametros)
        return cur.fetchall() if cur.description else None


def _tablas() -> set[str]:
    return {t for (t,) in _sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def _claves(tabla: str) -> list[str]:
    return [n for (n,) in _sql(
        "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'p'", (tabla,))]


def _indices_pkey() -> set[str]:
    return {n for (n,) in _sql("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE '%modulos_pkey'")}


def _filas(tabla: str) -> list[tuple]:
    return [tuple(f) for f in _sql(f"SELECT modulo, habilitado, plan FROM {tabla} ORDER BY modulo")]


@pytest.fixture
def cfg(monkeypatch):
    """Un `schema public` vacío y alembic apuntado a él **por el entorno** (el `env.py` lo lee de ahí)."""
    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    _sql("DROP SCHEMA public CASCADE")
    _sql("CREATE SCHEMA public")
    c = Config("alembic.ini")
    c.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.stamp(c, PREVIA)
    return c


def _sembrar(tabla: str = "modulos") -> None:
    for modulo, habilitado, plan in FILAS:
        _sql(f"INSERT INTO {tabla} (modulo, habilitado, plan) VALUES (%s, %s, %s)", (modulo, habilitado, plan))


# ── 1. Instancia viva ───────────────────────────────────────────────────────


def test_una_instancia_viva_renombra_la_tabla_con_sus_filas_y_su_clave(cfg):
    _sql(MODULOS_DE_MEDLIBRA)
    _sembrar()
    antes = _filas("modulos")
    assert _claves("modulos") == ["modulos_pkey"]

    command.upgrade(cfg, NUEVA)

    assert "modulos" not in _tablas()
    assert _filas("medlibra_modulos") == antes
    # La clave se renombra con la tabla: un `RENAME` no la mueve, y `modulos_pkey` es un nombre de TODA la
    # base que la `modulos` del motor necesita para sí.
    assert _claves("medlibra_modulos") == ["medlibra_modulos_pkey"]
    assert _indices_pkey() == {"medlibra_modulos_pkey"}


def test_baja_y_sube_sin_perder_filas(cfg):
    _sql(MODULOS_DE_MEDLIBRA)
    _sembrar()
    antes = _filas("modulos")

    command.upgrade(cfg, NUEVA)
    command.downgrade(cfg, PREVIA)

    assert "medlibra_modulos" not in _tablas()
    assert _filas("modulos") == antes
    assert _claves("modulos") == ["modulos_pkey"]

    command.upgrade(cfg, NUEVA)
    assert _filas("medlibra_modulos") == antes
    assert _claves("medlibra_modulos") == ["medlibra_modulos_pkey"]


def test_el_renombre_deja_lugar_para_la_modulos_del_motor(cfg):
    """El objetivo del cambio: después de renombrar, la tabla del motor se puede crear en la misma base."""
    _sql(MODULOS_DE_MEDLIBRA)
    _sembrar()

    command.upgrade(cfg, NUEVA)
    _sql(MODULOS_DEL_MOTOR)  # sin el renombre moría con «relation "modulos" already exists»

    assert _claves("modulos") == ["modulos_pkey"]
    assert _filas("medlibra_modulos") == sorted(FILAS)


# ── 2. Base nueva y unida ───────────────────────────────────────────────────


def test_si_modulos_es_la_del_motor_no_se_toca_ninguna(cfg):
    _sql(MODULOS_DEL_MOTOR)
    _sql("INSERT INTO modulos (modulo, habilitado, plan) VALUES ('caja', 1, 'estandar')")
    _sql(MODULOS_DE_MEDLIBRA.replace("TABLE modulos", "TABLE medlibra_modulos"))
    _sembrar("medlibra_modulos")

    command.upgrade(cfg, NUEVA)

    assert _sql("SELECT id, modulo, habilitado, plan FROM modulos") == [(1, "caja", 1, "estandar")]
    assert _filas("medlibra_modulos") == sorted(FILAS)

    command.downgrade(cfg, PREVIA)  # hay una `modulos` (la del motor): no se pisa ni se renombra nada

    assert _sql("SELECT id, modulo, habilitado, plan FROM modulos") == [(1, "caja", 1, "estandar")]
    assert _filas("medlibra_modulos") == sorted(FILAS)


def test_en_una_base_sin_ninguna_modulos_no_hace_nada(cfg):
    _sql(MODULOS_DE_MEDLIBRA.replace("TABLE modulos", "TABLE medlibra_modulos"))
    _sembrar("medlibra_modulos")

    command.upgrade(cfg, NUEVA)

    assert _tablas() == {"alembic_version_medlibra", "medlibra_modulos"}
    assert _filas("medlibra_modulos") == sorted(FILAS)


# ── 3. El arranque nuevo corrió antes de migrar ─────────────────────────────


def test_si_ya_existe_la_nueva_las_filas_de_la_vieja_mandan_sobre_el_sembrado(cfg):
    # `create_all()` + `ensure_seeded()` del arranque nuevo: todo habilitado, plan premium.
    _sql(MODULOS_DE_MEDLIBRA.replace("TABLE modulos", "TABLE medlibra_modulos"))
    for modulo in ("recordatorios", "senas", "facturacion", "dashboard"):
        _sql("INSERT INTO medlibra_modulos (modulo, habilitado, plan) VALUES (%s, true, 'premium')", (modulo,))
    # Lo que alguien configuró en la vieja: un plan básico y un add-on prendido.
    _sql(MODULOS_DE_MEDLIBRA)
    _sql("INSERT INTO modulos (modulo, habilitado, plan) VALUES ('senas', false, 'basico')")
    _sql("INSERT INTO modulos (modulo, habilitado, plan) VALUES ('resguardo_externo', true, 'addon')")

    command.upgrade(cfg, NUEVA)

    assert "modulos" not in _tablas()
    assert _filas("medlibra_modulos") == [
        ("dashboard", True, "premium"),
        ("facturacion", True, "premium"),
        ("recordatorios", True, "premium"),
        ("resguardo_externo", True, "addon"),
        ("senas", False, "basico"),      # la configuración de la vieja le ganó al sembrado
    ]


# ── 0011: la cadena de una base nueva ───────────────────────────────────────


def test_0011_crea_la_tabla_con_el_nombre_nuevo_aunque_modulos_ya_sea_del_motor(monkeypatch):
    """Una base nueva y unida: `libracore-migrar` corre antes y ya dejó SU `modulos`. Con el `create_table("modulos")`
    de antes, `0011` moría con «already exists»."""
    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    _sql("DROP SCHEMA public CASCADE")
    _sql("CREATE SCHEMA public")
    _sql(MODULOS_DEL_MOTOR)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.stamp(cfg, "0010_patient_created_at")

    command.upgrade(cfg, "0011_modulos")

    assert {"modulos", "medlibra_modulos"} <= _tablas()
    assert _claves("medlibra_modulos") == ["medlibra_modulos_pkey"]


@pytest.mark.parametrize("como_queda", ["medlibra_modulos", "modulos"])
def test_0011_baja_borra_la_de_medlibra_con_cualquiera_de_sus_dos_nombres(monkeypatch, como_queda):
    """Con el nombre nuevo, o con el viejo si `0023` ya se bajó y la devolvió a `modulos`."""
    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    _sql("DROP SCHEMA public CASCADE")
    _sql("CREATE SCHEMA public")
    _sql(MODULOS_DE_MEDLIBRA.replace("TABLE modulos", f"TABLE {como_queda}"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.stamp(cfg, "0011_modulos")

    command.downgrade(cfg, "0010_patient_created_at")

    assert como_queda not in _tablas()


def test_0011_baja_no_borra_la_modulos_del_motor(monkeypatch):
    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    _sql("DROP SCHEMA public CASCADE")
    _sql("CREATE SCHEMA public")
    _sql(MODULOS_DEL_MOTOR)
    _sql("INSERT INTO modulos (modulo, habilitado, plan) VALUES ('caja', 1, 'estandar')")
    _sql(MODULOS_DE_MEDLIBRA.replace("TABLE modulos", "TABLE medlibra_modulos"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.stamp(cfg, "0011_modulos")

    command.downgrade(cfg, "0010_patient_created_at")

    assert "medlibra_modulos" not in _tablas()
    assert _sql("SELECT modulo FROM modulos") == [("caja",)]
