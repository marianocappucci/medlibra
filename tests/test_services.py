from fastapi.testclient import TestClient

from app.main import create_app


def _client():
    return TestClient(create_app("sqlite:///:memory:"))


def test_service_crud_round_trip():
    client = _client()
    created = client.post("/services", json={
        "id": "service-1", "name": "Consulta clinica", "duration_minutes": 30,
    })
    assert created.status_code == 201
    assert created.json()["duration_minutes"] == 30

    assert client.get("/services/service-1").json()["name"] == "Consulta clinica"
    assert len(client.get("/services").json()) == 1

    updated = client.put("/services/service-1", json={
        "name": "Consulta larga", "duration_minutes": 60,
    })
    assert updated.status_code == 200
    assert updated.json()["duration_minutes"] == 60

    assert client.delete("/services/service-1").status_code == 204
    assert client.get("/services/service-1").status_code == 404


def test_service_not_found_returns_404():
    client = _client()
    assert client.get("/services/missing").status_code == 404
    assert client.put("/services/missing", json={"name": "x", "duration_minutes": 30}).status_code == 404
    assert client.delete("/services/missing").status_code == 404


def test_service_duplicate_id_returns_409():
    client = _client()
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    response = client.post("/services", json={"id": "service-1", "name": "Otra", "duration_minutes": 15})
    assert response.status_code == 409


def test_service_rejects_zero_duration():
    client = _client()
    response = client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 0})
    assert response.status_code == 422
