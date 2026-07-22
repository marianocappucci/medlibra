from fastapi.testclient import TestClient


def test_resource_crud_round_trip(admin_client: TestClient):
    client = admin_client
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


def test_resource_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/resources/missing").status_code == 404
    assert admin_client.put("/resources/missing", json={"name": "x"}).status_code == 404
    assert admin_client.delete("/resources/missing").status_code == 404


def test_resource_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1"})
    response = admin_client.post("/resources", json={"id": "resource-1", "name": "Otro"})
    assert response.status_code == 409


def test_cannot_delete_a_resource_with_an_appointment_pointing_at_it(admin_client: TestClient):
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
    response = client.delete("/resources/resource-1")
    assert response.status_code == 409
