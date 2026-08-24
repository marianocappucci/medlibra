"""El consultorio como entidad propia.

Hasta el 2026-08-23 lo único que MedLibra sabía ocupar era el profesional. Ver
`app/services/consultorios.py` para por qué un consultorio no es un `Resource`
de LibraGenda.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sembrado(admin_client: TestClient) -> TestClient:
    admin_client.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte"})
    return admin_client


def test_consultorio_crud_round_trip(sembrado: TestClient):
    client = sembrado
    creado = client.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })
    assert creado.status_code == 201, creado.text
    assert creado.json() == {
        "id": "cons-1", "name": "Consultorio 1",
        "branch_id": "sede-1", "active": True,
    }

    assert client.get("/consultorios/cons-1").json()["name"] == "Consultorio 1"
    assert len(client.get("/consultorios").json()) == 1

    editado = client.put("/consultorios/cons-1", json={
        "name": "Consultorio 1 (planta baja)", "branch_id": "sede-1", "active": False,
    })
    assert editado.status_code == 200
    assert editado.json()["name"] == "Consultorio 1 (planta baja)"
    assert editado.json()["active"] is False

    assert client.delete("/consultorios/cons-1").status_code == 204
    assert client.get("/consultorios").json() == []


def test_consultorio_duplicado_da_409(sembrado: TestClient):
    sembrado.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1"})
    repetido = sembrado.post("/consultorios", json={"id": "cons-1", "name": "Otro"})
    assert repetido.status_code == 409


def test_consultorio_inexistente_da_404(sembrado: TestClient):
    client = sembrado
    assert client.get("/consultorios/fantasma").status_code == 404
    assert client.put(
        "/consultorios/fantasma", json={"name": "X", "branch_id": None, "active": True},
    ).status_code == 404
    assert client.delete("/consultorios/fantasma").status_code == 404


def test_consultorio_sin_nombre_da_422(sembrado: TestClient):
    respuesta = sembrado.post("/consultorios", json={"id": "cons-1", "name": "   "})
    assert respuesta.status_code == 422


def test_consultorio_puede_no_tener_sede(admin_client: TestClient):
    """`branch_id` opcional a propósito: un consultorio único no necesita que
    alguien haya cargado la sede primero para poder existir."""
    creado = admin_client.post("/consultorios", json={"id": "cons-1", "name": "Único"})
    assert creado.status_code == 201
    assert creado.json()["branch_id"] is None
