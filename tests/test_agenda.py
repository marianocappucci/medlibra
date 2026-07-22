import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def seeded_client(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": "18:00:00",
        })
    return client


def test_agenda_returns_appointments_within_range(seeded_client: TestClient):
    client = seeded_client
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-22T11:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["starts_at"] == "2026-07-20T10:00:00Z"


def test_agenda_covers_a_full_week_and_is_sorted(seeded_client: TestClient):
    client = seeded_client
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-22T11:00:00",
    })
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-26",
    })
    body = response.json()
    assert [item["starts_at"] for item in body] == [
        "2026-07-20T10:00:00Z", "2026-07-22T11:00:00Z",
    ]


def test_agenda_ignores_other_resources(seeded_client: TestClient):
    client = seeded_client
    client.post("/resources", json={"id": "resource-2", "name": "Consultorio 2"})
    for weekday in range(7):
        client.post("/resources/resource-2/availability", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": "18:00:00",
        })
    client.post("/appointments", json={
        "resource_id": "resource-2", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    })
    assert response.json() == []


def test_agenda_rejects_date_to_before_date_from(seeded_client: TestClient):
    response = seeded_client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-19",
    })
    assert response.status_code == 422
