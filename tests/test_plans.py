import sqlite3

import pytest

import plans


def test_modulos_de_plan_basico_is_empty():
    assert plans.modulos_de_plan("basico") == set()


def test_modulos_de_plan_estandar_adds_recordatorios_y_senas():
    assert plans.modulos_de_plan("estandar") == {"recordatorios", "senas"}


def test_modulos_de_plan_premium_adds_facturacion_y_dashboard():
    assert plans.modulos_de_plan("premium") == {
        "recordatorios", "senas", "facturacion", "dashboard",
    }


def test_modulos_de_plan_unknown_plan_returns_empty_set():
    assert plans.modulos_de_plan("inexistente") == set()


def test_todos_los_modulos_matches_premium():
    assert plans.TODOS_LOS_MODULOS == plans.modulos_de_plan("premium")


def test_precios_mas_altos_que_gestiolibra():
    # MedLibra apunta a consultorios/profesionales de salud, no a negocios
    # de servicios chicos (ver DECISIONS.md ADR-018) -- precio de
    # referencia mayor que el de Gestiolibra en los tres niveles.
    assert plans.PLAN_PRECIOS == {"basico": 25000, "estandar": 40000, "premium": 60000}


def test_aplicar_plan_en_db_basico(tmp_path):
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE modulos (
            modulo TEXT PRIMARY KEY, habilitado INTEGER NOT NULL, plan TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

    plans.aplicar_plan_en_db(db_path, "basico")

    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT modulo, habilitado FROM modulos").fetchall())
    con.close()
    assert rows == {"recordatorios": 0, "senas": 0, "facturacion": 0, "dashboard": 0}


def test_aplicar_plan_en_db_estandar(tmp_path):
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE modulos (
            modulo TEXT PRIMARY KEY, habilitado INTEGER NOT NULL, plan TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

    plans.aplicar_plan_en_db(db_path, "estandar")

    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT modulo, habilitado FROM modulos").fetchall())
    con.close()
    assert rows == {"recordatorios": 1, "senas": 1, "facturacion": 0, "dashboard": 0}


def test_aplicar_plan_en_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE modulos (
            modulo TEXT PRIMARY KEY, habilitado INTEGER NOT NULL, plan TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

    plans.aplicar_plan_en_db(db_path, "premium")
    plans.aplicar_plan_en_db(db_path, "basico")  # downgrade, sobre las mismas filas

    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT modulo, habilitado FROM modulos").fetchall())
    con.close()
    assert rows == {"recordatorios": 0, "senas": 0, "facturacion": 0, "dashboard": 0}


def test_aplicar_plan_en_db_rejects_unknown_plan(tmp_path):
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE modulos (
            modulo TEXT PRIMARY KEY, habilitado INTEGER NOT NULL, plan TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

    with pytest.raises(ValueError):
        plans.aplicar_plan_en_db(db_path, "inexistente")
