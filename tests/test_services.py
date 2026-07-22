from fastapi.testclient import TestClient


def test_service_crud_round_trip(admin_client: TestClient):
    client = admin_client
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


def test_service_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/services/missing").status_code == 404
    assert admin_client.put("/services/missing", json={"name": "x", "duration_minutes": 30}).status_code == 404
    assert admin_client.delete("/services/missing").status_code == 404


def test_service_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    response = admin_client.post("/services", json={"id": "service-1", "name": "Otra", "duration_minutes": 15})
    assert response.status_code == 409


def test_service_rejects_zero_duration(admin_client: TestClient):
    response = admin_client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 0})
    assert response.status_code == 422


def test_cannot_delete_a_service_with_an_appointment_pointing_at_it(admin_client: TestClient):
    client = admin_client
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    client.post("/resources/resource-1/availability", json={
        "weekday": 0, "starts_at": "00:00:00", "ends_at": "23:59:00",
    })
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert created.status_code == 201
    response = client.delete("/services/service-1")
    assert response.status_code == 409
