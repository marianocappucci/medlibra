from fastapi.testclient import TestClient

from app.main import create_app


def _client():
    return TestClient(create_app("sqlite:///:memory:"))


def test_branch_crud_round_trip():
    client = _client()
    created = client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    assert created.status_code == 201
    assert created.json() == {"id": "branch-1", "name": "Centro", "active": True, "timezone": "UTC"}

    assert client.get("/branches/branch-1").json()["name"] == "Centro"
    assert len(client.get("/branches").json()) == 1

    updated = client.put("/branches/branch-1", json={
        "name": "Centro renombrado", "active": False, "timezone": "America/Argentina/Buenos_Aires",
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Centro renombrado"
    assert updated.json()["active"] is False

    assert client.delete("/branches/branch-1").status_code == 204
    assert client.get("/branches/branch-1").status_code == 404


def test_branch_not_found_returns_404():
    client = _client()
    assert client.get("/branches/missing").status_code == 404
    assert client.put("/branches/missing", json={"name": "x"}).status_code == 404
    assert client.delete("/branches/missing").status_code == 404


def test_branch_duplicate_id_returns_409():
    client = _client()
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    response = client.post("/branches", json={"id": "branch-1", "name": "Otro"})
    assert response.status_code == 409


def test_branch_rejects_invalid_data():
    client = _client()
    response = client.post("/branches", json={"id": "", "name": "Centro"})
    assert response.status_code == 422
