from fastapi.testclient import TestClient

from app.main import create_app


def _client():
    return TestClient(create_app("sqlite:///:memory:"))


def test_resource_crud_round_trip():
    client = _client()
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    created = client.post("/resources", json={
        "id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1",
    })
    assert created.status_code == 201
    assert created.json()["branch_id"] == "branch-1"

    assert client.get("/resources/resource-1").json()["name"] == "Consultorio 1"
    assert len(client.get("/resources").json()) == 1

    updated = client.put("/resources/resource-1", json={"name": "Consultorio renombrado", "active": False})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Consultorio renombrado"
    assert updated.json()["branch_id"] is None
    assert updated.json()["active"] is False

    assert client.delete("/resources/resource-1").status_code == 204
    assert client.get("/resources/resource-1").status_code == 404


def test_resource_not_found_returns_404():
    client = _client()
    assert client.get("/resources/missing").status_code == 404
    assert client.put("/resources/missing", json={"name": "x"}).status_code == 404
    assert client.delete("/resources/missing").status_code == 404


def test_resource_duplicate_id_returns_409():
    client = _client()
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1"})
    response = client.post("/resources", json={"id": "resource-1", "name": "Otro"})
    assert response.status_code == 409
