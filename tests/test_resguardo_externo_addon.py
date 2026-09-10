"""`resguardo_externo`: el add-on de la copia externa, y el enlace que gatea.

El router es de LibraCore (`libracore.resguardo_enlace`, v1.93.0) y tiene sus
propios tests ahí. Lo que se prueba acá es lo que sólo este producto puede
verificar:

1. 🔴 **Que el add-on nazca APAGADO.** `ModuleRepository.is_enabled` daba por
   habilitado cualquier módulo sin fila, y un add-on —que queda afuera de
   `TODOS_LOS_MODULOS` a propósito— caía justo ahí: `require_module` nunca daba
   403 y la pantalla le ofrecía la copia a la nube a todas las instancias. No
   falla de ninguna forma visible.
2. Que ese arreglo no le cambie nada a los módulos de plan ni al core clínico.
3. Que el backoffice pueda prenderlo por el camino que usa de verdad: un
   `docker exec` que importa `app.database`, **fuera** del arranque de la app.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from motor_de_test import TEST_DATABASE_URL
from sqlalchemy import delete

import plans
from app.services.modules import ModuleRow

ENLACE = "/api/config/resguardo-externo/enlace"
ADDON = "resguardo_externo"
RAIZ = str(Path(__file__).resolve().parent.parent)


@pytest.fixture(autouse=True)
def _backups_en_tmp(monkeypatch, tmp_path):
    """`backups_dir` sale de `DATA_DIR` con la base en PostgreSQL. Sin esto
    caería en `./data/backups` del árbol de trabajo. Autouse para que corra
    antes que el `create_app()` de `admin_client`."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _modulos(client: TestClient):
    return client.app.state.modules


# ── 🔴 El gate del add-on ─────────────────────────────────────────────────

def test_sin_fila_el_addon_esta_apagado_y_da_403(admin_client: TestClient):
    """El caso de toda instancia hoy: nadie lo prendió, así que no hay fila.
    `ensure_seeded()` no la crea — si la creara, sería con `habilitado=True`."""
    assert ADDON not in _modulos(admin_client).get_all()

    r = admin_client.get(ENLACE)
    assert r.status_code == 403, r.text


def test_con_la_fila_apagada_da_403(admin_client: TestClient):
    _modulos(admin_client).set_enabled(ADDON, False)

    assert admin_client.get(ENLACE).status_code == 403


def test_prendido_da_200_con_proveedores_y_enlace(admin_client: TestClient):
    _modulos(admin_client).set_enabled(ADDON, True)

    r = admin_client.get(ENLACE)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "proveedores" in cuerpo
    assert "enlace" in cuerpo
    # Nada enlazado todavía: la carpeta `.resguardo/` no existe.
    assert cuerpo["enlace"] is None


def test_el_staff_no_llega_aunque_el_addon_este_prendido(staff_client: TestClient, admin_client: TestClient):
    """Con el add-on prendido, así el 403 no puede venir del módulo: es el rol.
    Conecta la cuenta de nube del cliente — admin y nada más."""
    _modulos(admin_client).set_enabled(ADDON, True)

    assert staff_client.get(ENLACE).status_code in (401, 403)
    assert staff_client.delete(ENLACE).status_code in (401, 403)


def test_sin_sesion_no_llega(admin_client: TestClient):
    _modulos(admin_client).set_enabled(ADDON, True)

    with TestClient(admin_client.app, base_url="https://medlibra.test") as anonimo:
        assert anonimo.get(ENLACE).status_code in (401, 403)


# ── Lo que el arreglo NO tiene que cambiar ────────────────────────────────

def test_un_modulo_de_plan_sin_fila_sigue_habilitado(admin_client: TestClient):
    """Regresión: la regla de "sin fila, apagado" es SOLO de los add-ons. Un
    módulo de plan sin fila sigue habilitado —el seed no bloquea nada— y el
    core clínico, que nunca tiene fila, también."""
    modulos = _modulos(admin_client)
    with modulos.session_factory.begin() as session:
        session.execute(delete(ModuleRow).where(ModuleRow.modulo == "dashboard"))
    assert "dashboard" not in modulos.get_all()

    assert modulos.is_enabled("dashboard") is True
    assert modulos.is_enabled("pacientes") is True
    r = admin_client.get("/dashboard?date_from=2026-07-20&date_to=2026-07-20")
    assert r.status_code == 200, r.text


def test_aplicar_un_plan_no_apaga_el_addon(admin_client: TestClient):
    """Un add-on sobrevive a subir o bajar de plan: es justo lo que se paga
    aparte. Se aplica por el mismo camino que el provisioning
    (`plans.aplicar_plan_en_db`), contra la base viva."""
    modulos = _modulos(admin_client)
    modulos.set_enabled(ADDON, True)

    plans.aplicar_plan_en_db(TEST_DATABASE_URL, "basico")

    # Control: el plan SÍ se aplicó. Sin esto, un `aplicar_plan_en_db` que no
    # hiciera nada dejaría este test en verde.
    assert modulos.is_enabled("dashboard") is False
    assert modulos.is_enabled(ADDON) is True
    assert admin_client.get(ENLACE).status_code == 200


# ── plans.py ──────────────────────────────────────────────────────────────

def test_resguardo_externo_es_addon_y_no_esta_en_ningun_plan():
    assert ADDON in plans.ADDONS
    for plan in plans.PLANES:
        assert ADDON not in plans.modulos_de_plan(plan), plan
    assert ADDON not in plans.TODOS_LOS_MODULOS
    # Y ningún add-on, no sólo éste: uno en `TODOS_LOS_MODULOS` lo sembraría
    # `ensure_seeded()` prendido en todas las instancias.
    assert not (plans.ADDONS & plans.TODOS_LOS_MODULOS)


# ── El contrato del backoffice (`app.database`) ───────────────────────────

def test_app_database_exporta_el_contrato_del_backoffice():
    """El import textual del snippet de `libracore.admin.services`."""
    from app.database import get_modulos, set_addon

    assert callable(get_modulos)
    assert callable(set_addon)


def _como_el_backoffice(codigo: str) -> str:
    """Corre `codigo` como lo corre el backoffice: `python3 -c` en un proceso
    nuevo, sin `create_app()`, con la base del dominio en el entorno. Es el
    `docker exec` sin el docker — el core de LibraCore arranca sin configurar,
    que es el caso que `_asegurar_core_configurado` tiene que resolver solo."""
    entorno = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "MEDLIBRA_DATABASE_URL")}
    entorno["MEDLIBRA_DATABASE_URL"] = TEST_DATABASE_URL
    r = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {RAIZ!r}); {codigo}"],
        capture_output=True, text=True, cwd=RAIZ, env=entorno, timeout=120,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    return r.stdout


def test_el_backoffice_prende_y_apaga_el_addon_en_la_base_que_lee_la_app(admin_client: TestClient):
    """🔑 El circuito completo, y el control de que el shim no abre una base
    paralela: se escribe por `app.database` y se lee por la app.

    Si `_asegurar_core_configurado()` apuntara a la base de LibraCore
    (`medlibra_core`, que tiene su propia `modulos` vacía), el `set_addon`
    saldría con éxito y el gate seguiría dando 403."""
    assert admin_client.get(ENLACE).status_code == 403

    _como_el_backoffice("from app.database import set_addon; set_addon('resguardo_externo', True)")
    assert admin_client.get(ENLACE).status_code == 200

    leido = _como_el_backoffice(
        "import json; from app.database import get_modulos; print(json.dumps(get_modulos()))"
    )
    assert json.loads(leido)[ADDON] is True

    _como_el_backoffice("from app.database import set_addon; set_addon('resguardo_externo', False)")
    assert admin_client.get(ENLACE).status_code == 403


def test_dentro_de_la_app_el_contrato_corta_en_vez_de_leer_otra_base(admin_client: TestClient):
    """Adentro de la app el core de LibraCore apunta a `medlibra_core`, no al
    dominio. Delegar ahí devolvería `{}` —el add-on "apagado" aunque esté
    prendido—, así que el shim prefiere un error que diga qué usar."""
    from app.database import get_modulos

    _modulos(admin_client).set_enabled(ADDON, True)
    with pytest.raises(RuntimeError, match="app.state.modules"):
        get_modulos()
