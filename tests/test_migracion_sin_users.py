"""La migración `0019_sin_users` tiene que correr en LOS DOS MUNDOS.

🔴 **El segundo mundo es el que decide, y es el que no existe en el repo.**

1. **Base armada por las migraciones** — `users` existe (la crea `0001`) y hay
   que borrarla.
2. **Instancia viva** — `users` **no** existe. El esquema de las instancias lo
   creó `Base.metadata.create_all()` desde los modelos, y `users` no es un
   modelo de este producto: el auth se mudó a `libraauth` el 2026-07-30 y los
   usuarios viven en `usuarios`, contra otro engine. Medido contra la demo el
   2026-08-24, cuyo esquema coincide exacto con las migraciones hasta
   `0012_service_iva_rates` **salvo esta tabla**.

Con un `op.drop_table("users")` pelado, el mundo 2 falla con
`table "users" does not exist`. Y desde LibraCore `v1.48.0` **una migración
fallida aborta el deploy** de esa instancia — o sea que el arreglo convertiría
un deploy que funciona en uno que no. Se verificó rompiéndolo a propósito: con
`drop_table`, el mundo 1 sigue verde y **el mundo 2 se pone rojo**.

## Por qué no se levanta la cadena entera

Las revisiones intermedias tienen FK contra tablas de **LibraGenda**
(`branches`), que viven en otro paquete y otra cadena de Alembic — el CI ya las
corre en orden. Acá lo que se ejercita es **esta revisión**, así que se usa la
`0001` real (que sólo crea `users`, sin dependencias) y después se **estampa**
la anterior.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config

from motor_de_test import TEST_DATABASE_URL, corre_contra_postgres

PREVIA = "0018_envios_a_contalibra"
NUEVA = "0019_sin_users"
TABLA_VERSION = "alembic_version_medlibra"

pytestmark = pytest.mark.skipif(
    not corre_contra_postgres(),
    reason="necesita PostgreSQL: la migración se ejercita contra una base real",
)


def _cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def base_limpia(monkeypatch):
    """Un `schema public` vacío, y alembic apuntado a él **por el entorno**.

    🔑 **`sqlalchemy.url` no alcanza.** El `env.py` resuelve la URL con
    `url_de_instancia("medlibra")` y sólo cae a la config del `.ini` si el
    entorno **no dice nada**. En el CI sí dice: `DATABASE_URL` es una variable
    del job entero y apunta al SQLite del primer paso, así que las migraciones
    de este test corrían contra **otra base** y acá no pasaba nada. Local pasaba
    porque ahí esa variable no está puesta — o sea que el test era verde en la
    máquina y rojo en el único lugar donde se mira.

    Se pone el **nombre normalizado**, que `url_de_instancia` prueba antes que
    el histórico `DATABASE_URL`, así que le gana sin tener que borrar nada del
    entorno del job.
    """
    import psycopg

    from libracore.db.url_de_instancia import url_de_instancia

    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    assert url_de_instancia("medlibra") == TEST_DATABASE_URL, (
        "el control: si el entorno le gana al test, las migraciones se van a "
        "otra base y los asserts de abajo miden una base que nadie migró"
    )

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


def _hay_users() -> bool:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        return c.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'users'"
        ).fetchone()[0] == 1


def _revision() -> str | None:
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        fila = c.execute(f"SELECT version_num FROM {TABLA_VERSION}").fetchone()
    return fila[0] if fila else None


def test_mundo_1_la_borra_cuando_existe(base_limpia):
    """La base que armaron las migraciones: `0001` la creó, `0019` la saca."""
    command.upgrade(base_limpia, "0001_users")
    assert _hay_users(), "el control: `0001` tiene que haberla creado"
    command.stamp(base_limpia, PREVIA)

    command.upgrade(base_limpia, "head")

    assert not _hay_users()
    assert _revision() == NUEVA


def test_mundo_2_no_falla_cuando_no_existe(base_limpia):
    """🔴 El que decide. Una instancia viva estampada, sin la tabla.

    Se estampa sin ejecutar nada —que es exactamente lo que se le va a hacer a
    las instancias— y se sube. Con `op.drop_table()` pelado, esto revienta.
    """
    command.stamp(base_limpia, PREVIA)
    assert not _hay_users(), "el control: la instancia viva no la tiene"

    command.upgrade(base_limpia, "head")

    assert not _hay_users()
    assert _revision() == NUEVA


def test_el_downgrade_la_devuelve(base_limpia):
    """La cadena sigue siendo reversible: `downgrade` recrea la tabla como
    estaba en `0001`. Queda vacía — no hay de dónde recuperar filas que este
    producto dejó de escribir hace un mes."""
    command.stamp(base_limpia, PREVIA)
    command.upgrade(base_limpia, "head")
    assert not _hay_users()

    command.downgrade(base_limpia, PREVIA)

    assert _hay_users()
    assert _revision() == PREVIA
