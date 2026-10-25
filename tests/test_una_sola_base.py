"""Una sola base o dos: `Config`, el respaldo y la instancia entera con las dos formas (ADR-043).

Decisión del humano del 2026-10-22: una base por producto. Las instancias vivas de MedLibra siguen con dos
(`medlibra` y `medlibra_core`) hasta que `libracore-unir-bases` las una, así que el código tiene que andar con
las dos formas. La suite normal mide la de dos bases (es la que arma `tests/motor_de_test.py`); estos tests
miden las dos con **bases propias**, descartables, y la cadena de migraciones corrida como la corre el deploy:

1. **`Config`**: sin variable del core, o con la misma base, es una sola; con otra, son dos.
2. **El respaldo** lleva el core como segunda base sólo si es otra.
3. **Una instancia entera sobre una sola base**: las cuatro cadenas (libragenda, libraauth `--base dominio`,
   libracore, la propia) conviven sin pisarse, la app arranca, un paciente se da de alta y el backup trae
   una base.
4. **Lo mismo sobre dos bases**, con `--base core`.
5. **El paso a `libracore.db.modulos`**: las filas de `medlibra_modulos` caben en la `modulos` del motor y
   el motor las lee. Es el SQL que dice ADR-043 para después de unir.
"""
from __future__ import annotations

import contextlib
import io
import zipfile

import pytest
from bases_temporales import base_temporal, consultar, correr_cadena, una
from fastapi.testclient import TestClient
from motor_de_test import TEST_DATABASE_URL

from app.config import Config, misma_base
from app.main import _instancia_a_respaldar, create_app

PG = "postgresql+psycopg://medlibra:clave@db:5432"


@pytest.fixture
def entorno_limpio(monkeypatch):
    """Sin ninguna variable de base: cada test dice cuáles quiere."""
    for nombre in ("MEDLIBRA_DATABASE_URL", "DATABASE_URL", "MEDLIBRA_LIBRACORE_DATABASE_URL",
                   "MEDLIBRA_LIBRACORE_DB_PATH", "DATA_DIR"):
        monkeypatch.delenv(nombre, raising=False)
    return monkeypatch


# ── 1. Config ───────────────────────────────────────────────────────────────


def test_sin_variable_del_core_es_una_sola_base(entorno_limpio):
    entorno_limpio.setenv("MEDLIBRA_DATABASE_URL", f"{PG}/medlibra")

    cfg = Config.desde_entorno()

    assert cfg.database_url == f"{PG}/medlibra"
    assert cfg.libracore_database_url == cfg.database_url
    assert cfg.core_en_la_del_dominio is True
    assert cfg.base_de_auth == "dominio"


@pytest.mark.parametrize("core", [
    f"{PG}/medlibra",                       # la misma, tal cual
    f"{PG}/medlibra/",                      # barra final
    f"{PG}/medlibra?sslmode=disable",       # parámetros
    "postgresql://medlibra:clave@db:5432/medlibra",  # sin el driver
])
def test_la_misma_base_dicha_de_otra_forma_sigue_siendo_una(entorno_limpio, core):
    entorno_limpio.setenv("MEDLIBRA_DATABASE_URL", f"{PG}/medlibra")
    entorno_limpio.setenv("MEDLIBRA_LIBRACORE_DATABASE_URL", core)

    cfg = Config.desde_entorno()

    # Un solo valor, escrito una vez: la URL del dominio tal cual, para que nadie más compare cadenas.
    assert cfg.libracore_database_url == f"{PG}/medlibra"
    assert cfg.core_en_la_del_dominio is True


def test_con_otra_base_son_dos_y_todo_sigue_como_hasta_hoy(entorno_limpio):
    entorno_limpio.setenv("MEDLIBRA_DATABASE_URL", f"{PG}/medlibra")
    entorno_limpio.setenv("MEDLIBRA_LIBRACORE_DATABASE_URL", f"{PG}/medlibra_core")

    cfg = Config.desde_entorno()

    assert cfg.libracore_database_url == f"{PG}/medlibra_core"
    assert cfg.core_en_la_del_dominio is False
    assert cfg.base_de_auth == "core"


def test_el_nombre_historico_del_core_se_sigue_aceptando(entorno_limpio):
    """Los composes de `-dev` y `-demo` dicen `MEDLIBRA_LIBRACORE_DB_PATH` y no se tocan en este PR."""
    entorno_limpio.setenv("DATABASE_URL", f"{PG}/medlibra")
    entorno_limpio.setenv("MEDLIBRA_LIBRACORE_DB_PATH", f"{PG}/medlibra_core")

    cfg = Config.desde_entorno()

    assert cfg.database_url == f"{PG}/medlibra"
    assert cfg.libracore_database_url == f"{PG}/medlibra_core"
    assert cfg.core_en_la_del_dominio is False


def test_la_url_que_se_pasa_manda_sobre_el_entorno(entorno_limpio):
    """`create_app(database_url)` recibe la URL; el core se resuelve contra ELLA, no contra la del entorno."""
    entorno_limpio.setenv("MEDLIBRA_DATABASE_URL", f"{PG}/otra")
    entorno_limpio.setenv("MEDLIBRA_LIBRACORE_DATABASE_URL", f"{PG}/medlibra")

    cfg = Config.desde_entorno(f"{PG}/medlibra")

    assert cfg.database_url == f"{PG}/medlibra"
    assert cfg.core_en_la_del_dominio is True


def test_sin_url_del_dominio_corta_nombrando_las_variables(entorno_limpio):
    with pytest.raises(RuntimeError, match="MEDLIBRA_DATABASE_URL"):
        Config.desde_entorno()


def test_un_dominio_que_no_es_postgres_no_inventa_una_sola_base(entorno_limpio, tmp_path):
    """El modo SQLite se retiró (2026-08-12): `libracore_setup` lo rechaza con su mensaje. Acá no se lo enmascara
    declarándolo «una sola base»: el core cae al archivo de siempre."""
    entorno_limpio.setenv("DATA_DIR", str(tmp_path))

    cfg = Config.desde_entorno("sqlite:///x.db")

    assert cfg.libracore_database_url == str(tmp_path / "medlibra_libracore.db")
    assert cfg.core_en_la_del_dominio is False


def test_misma_base_compara_servidor_usuario_y_nombre():
    assert misma_base(f"{PG}/a", f"{PG}/a?x=1")
    assert not misma_base(f"{PG}/a", f"{PG}/b")
    assert not misma_base(f"{PG}/a", "postgresql+psycopg://otro:clave@db:5432/a")


# ── 2. El respaldo ──────────────────────────────────────────────────────────


def test_el_respaldo_con_una_base_no_declara_el_core_como_extra():
    """Declararla como extra volcaría la misma base dos veces y la restauraría encima de sí misma."""
    instancia = _instancia_a_respaldar(f"{PG}/medlibra", f"{PG}/medlibra", directorios=[])

    assert instancia.postgres_url == f"{PG}/medlibra"
    assert list(instancia.postgres_extra) == []


def test_el_respaldo_con_dos_bases_lleva_las_dos():
    instancia = _instancia_a_respaldar(f"{PG}/medlibra", f"{PG}/medlibra_core", directorios=[])

    assert list(instancia.postgres_extra) == [f"{PG}/medlibra_core"]


# ── 3 y 4. Una instancia entera ─────────────────────────────────────────────


@contextlib.contextmanager
def _app(monkeypatch, tmp_path, dominio, core=None):
    """`create_app()` sobre bases propias, sin dejar nada colgado en los globales del proceso."""
    from libracore import config_manager
    from libracore.db import core as libracore_core
    from libragenda.database import reset as soltar_engine

    monkeypatch.delenv("MEDLIBRA_LIBRACORE_DB_PATH", raising=False)
    if core:
        monkeypatch.setenv("MEDLIBRA_LIBRACORE_DATABASE_URL", core)
    else:
        monkeypatch.delenv("MEDLIBRA_LIBRACORE_DATABASE_URL", raising=False)
    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", dominio)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # `create_app()` apunta `libracore.db.core` a la base de este test; el `setattr` con el mismo valor es para
    # que el `undo()` del monkeypatch lo deje como estaba.
    monkeypatch.setattr(libracore_core, "_db_path", libracore_core._db_path)
    monkeypatch.setattr(libracore_core, "_database_url", libracore_core._database_url)
    soltar_engine()
    app = create_app(dominio)
    try:
        yield app
    finally:
        app.state.auth_engine.dispose()
        soltar_engine()
        config_manager.usar_almacen_de_secretos(None)


def _sesion(app) -> TestClient:
    client = TestClient(app, base_url="https://medlibra.test")
    client.__enter__()
    r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return client


def _bases_del_zip(client: TestClient) -> list[str]:
    r = client.get("/api/config/backup-ahora")
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return sorted(n for n in z.namelist() if n.startswith("bases/"))


def _tablas(url: str) -> set[str]:
    return {t for (t,) in consultar(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def test_una_instancia_entera_sobre_una_sola_base(monkeypatch, tmp_path):
    with base_temporal("una") as url:
        # Las cuatro cadenas del deploy, contra la misma base. Sin la `alembic_version_libragenda` de
        # libragenda v0.14.0 la del motor y la de libragenda se pisarían: la de MedLibra moriría con «Can't
        # locate revision».
        correr_cadena(url)

        versiones = {t for t in _tablas(url) if t.startswith("alembic_version")}
        assert versiones == {"alembic_version", "alembic_version_libragenda", "alembic_version_libraauth",
                             "alembic_version_medlibra"}
        tablas = _tablas(url)
        # Las dos `clients` y las dos `modulos` conviven porque ninguna se llama igual.
        assert {"clients", "agenda_clients", "modulos", "medlibra_modulos", "usuarios"} <= tablas

        with _app(monkeypatch, tmp_path, url) as app:
            cfg = Config.desde_entorno(url)
            assert cfg.core_en_la_del_dominio is True

            client = _sesion(app)
            try:
                alta = client.post("/patients", json={"id": "pac-1", "name": "Paciente Ficticio", "dni": "11111111"})
                assert alta.status_code == 201, alta.text
                # La fila de la ficha y la del cliente de la agenda, en la tabla con el nombre nuevo.
                assert una(url, "SELECT count(*) FROM agenda_clients WHERE id = 'pac-1'") == 1
                assert una(url, "SELECT count(*) FROM patients WHERE id = 'pac-1'") == 1
                # La `clients` de LibraCore no se tocó: no es de la agenda.
                assert una(url, "SELECT count(*) FROM clients") == 0
                # Lo mismo para los módulos: el arranque sembró los del producto, no los del motor.
                assert una(url, "SELECT count(*) FROM medlibra_modulos") >= 4
                assert una(url, "SELECT count(*) FROM modulos") == 0

                assert len(_bases_del_zip(client)) == 1
            finally:
                client.__exit__(None, None, None)


def test_una_instancia_entera_sobre_dos_bases(monkeypatch, tmp_path):
    with base_temporal("dom") as dominio, base_temporal("core") as core:
        correr_cadena(dominio, core)

        # Cada cadena en su base: la agenda y lo propio en el dominio; los usuarios y el motor en el core.
        assert {"agenda_clients", "patients", "medlibra_modulos"} <= _tablas(dominio)
        assert "usuarios" not in _tablas(dominio)
        assert {"usuarios", "clients", "modulos"} <= _tablas(core)

        with _app(monkeypatch, tmp_path, dominio, core) as app:
            cfg = Config.desde_entorno(dominio)
            assert cfg.core_en_la_del_dominio is False

            client = _sesion(app)
            try:
                alta = client.post("/patients", json={"id": "pac-1", "name": "Paciente Ficticio"})
                assert alta.status_code == 201, alta.text
                assert una(dominio, "SELECT count(*) FROM agenda_clients WHERE id = 'pac-1'") == 1

                assert len(_bases_del_zip(client)) == 2
            finally:
                client.__exit__(None, None, None)


# ── 5. El paso a `libracore.db.modulos` ─────────────────────────────────────

#: El SQL que ADR-043 dice para después de unir: las filas de `medlibra_modulos` pasan a la `modulos` del
#: motor (`id` serial, `habilitado` entero). Es compatible porque el motor guarda lo mismo: un nombre, un sí/no
#: y la etiqueta del plan.
PASO_A_MODULOS_DEL_MOTOR = """
    INSERT INTO modulos (modulo, habilitado, plan)
    SELECT modulo, CASE WHEN habilitado THEN 1 ELSE 0 END, plan FROM medlibra_modulos
    ON CONFLICT (modulo) DO UPDATE SET habilitado = EXCLUDED.habilitado, plan = EXCLUDED.plan
"""


def test_las_filas_de_medlibra_modulos_caben_en_la_modulos_del_motor_y_el_motor_las_lee(monkeypatch, tmp_path):
    from libracore.db.modulos import get_modulos, set_addon

    with base_temporal("modulos") as url:
        correr_cadena(url)
        with _app(monkeypatch, tmp_path, url) as app:
            propios = app.state.modules
            propios.set_enabled("senas", False)          # un plan que no es premium
            propios.set_enabled("resguardo_externo", True)  # un add-on
            esperado = propios.get_all()
            assert esperado["senas"] is False and esperado["resguardo_externo"] is True

            consultar(url, PASO_A_MODULOS_DEL_MOTOR)
            consultar(url, PASO_A_MODULOS_DEL_MOTOR)  # repetirlo no duplica ni cambia nada

            # `libracore.db.core` está apuntado a esta base (lo hizo `create_app()`): lo que lee el motor es lo mismo.
            assert get_modulos() == esperado
            assert una(url, "SELECT count(*) FROM modulos") == len(esperado)

            # Y el motor puede seguir escribiendo ahí: es la tabla que usará el producto después de unir.
            set_addon("resguardo_externo", False)
            assert get_modulos()["resguardo_externo"] is False
