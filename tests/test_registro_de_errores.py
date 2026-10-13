"""El registro de errores de la familia (ADR-045 de libracore), cableado en Medlibra.

El motor prueba el registro entero (`libracore/tests/test_errores.py`): la limpieza, la firma, la rotacion. Lo que es de
ESTE producto, y lo que fija este archivo, es el cableado de `create_app()`:

1. Un 500 de cualquier ruta responde `{"detail": "Error interno", "ref": ...}` y deja una linea en el JSONL con el
   producto y el mismo `ref`. Si alguien sacara `instalar_registro_de_errores`, un 500 volveria a perderse en el stdout.
2. `POST /api/errores-cliente` existe y es publico (un error de la pantalla de login tambien importa).
"""
import json

import pytest
from fastapi.testclient import TestClient
from libracore import errores


@pytest.fixture()
def registro(tmp_path, monkeypatch):
    """El JSONL en un directorio del test (`LIBRA_ERRORES_DIR`) y el cache de manejadores vacio."""
    monkeypatch.setenv("LIBRA_ERRORES_DIR", str(tmp_path / "errores"))
    monkeypatch.setenv("LIBRA_INSTANCIA", "medlibra-test")
    monkeypatch.setenv("LIBRA_ENTORNO", "dev")
    monkeypatch.setattr(errores, "_manejadores", {})

    def lineas():
        archivo = tmp_path / "errores" / "errores.jsonl"
        if not archivo.exists():
            return []
        return [json.loads(x) for x in archivo.read_text(encoding="utf-8").splitlines() if x.strip()]

    return lineas


def test_un_500_responde_con_ref_y_deja_una_linea(admin_client, registro):
    app = admin_client.app

    @app.get("/__prueba_de_error__/{cid}")
    def boom(cid: int):
        raise ValueError("falló el turno")

    # `raise_server_exceptions=False`: el TestClient comun relanza lo que el servidor ya contesto como 500.
    c = TestClient(app, base_url="https://medlibra.test", raise_server_exceptions=False)
    r = c.get("/__prueba_de_error__/7")
    assert r.status_code == 500, r.text
    cuerpo = r.json()
    assert cuerpo["detail"] == "Error interno"
    assert len(cuerpo["ref"]) == 8

    [linea] = registro()
    assert linea["ref"] == cuerpo["ref"]
    assert linea["producto"] == "medlibra"
    assert linea["instancia"] == "medlibra-test"
    assert linea["entorno"] == "dev"
    assert linea["origen"] == "servidor"
    assert linea["status"] == 500
    assert linea["tipo"] == "ValueError"
    assert linea["ruta"] == "/__prueba_de_error__/{cid}"      # la plantilla, no la URL con el id


def test_un_4xx_no_se_registra(admin_client, registro):
    anonimo = TestClient(admin_client.app, base_url="https://medlibra.test")
    assert anonimo.get("/auth/me").status_code == 401
    assert registro() == []


def test_el_endpoint_de_errores_del_navegador_es_publico_y_registra(admin_client, registro):
    """Sin sesion: un error de la pantalla de login tambien tiene que llegar."""
    anonimo = TestClient(admin_client.app, base_url="https://medlibra.test")
    r = anonimo.post("/api/errores-cliente", json={
        "tipo": "error", "mensaje": "x is undefined", "stack": "at Login (login.js:1:1)",
        "pagina": "/login", "release": "dev",
    })
    assert r.status_code == 204, r.text
    [linea] = registro()
    assert linea["producto"] == "medlibra"
    assert linea["origen"] == "cliente"
