from fastapi.testclient import TestClient

from app.main import create_app


def _seeded_client():
    client = TestClient(create_app("sqlite:///:memory:"))
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def _book(client, hour=10):
    return client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": f"2026-07-20T{hour:02d}:00:00",
    })


def test_availability_window_crud_round_trip():
    client = _seeded_client()
    created = client.post("/resources/resource-1/availability", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert created.status_code == 201
    window_id = created.json()["id"]
    assert created.json()["resource_id"] == "resource-1"

    assert len(client.get("/resources/resource-1/availability").json()) == 1

    updated = client.put(f"/resources/resource-1/availability/{window_id}", json={
        "weekday": 1, "starts_at": "10:00:00", "ends_at": "16:00:00",
    })
    assert updated.status_code == 200
    assert updated.json()["weekday"] == 1

    assert client.delete(f"/resources/resource-1/availability/{window_id}").status_code == 204
    assert client.get("/resources/resource-1/availability").json() == []


def test_availability_window_not_found_returns_404():
    client = _seeded_client()
    assert client.put("/resources/resource-1/availability/999", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    }).status_code == 404
    assert client.delete("/resources/resource-1/availability/999").status_code == 404


def test_block_crud_round_trip():
    client = _seeded_client()
    created = client.post("/resources/resource-1/blocks", json={
        "starts_at": "2026-07-20T12:00:00", "ends_at": "2026-07-20T13:00:00", "reason": "almuerzo",
    })
    assert created.status_code == 201
    block_id = created.json()["id"]
    assert created.json()["reason"] == "almuerzo"

    updated = client.put(f"/resources/resource-1/blocks/{block_id}", json={
        "starts_at": "2026-07-20T14:00:00", "ends_at": "2026-07-20T15:00:00", "reason": "reunion",
    })
    assert updated.status_code == 200
    assert updated.json()["reason"] == "reunion"

    assert client.delete(f"/resources/resource-1/blocks/{block_id}").status_code == 204
    assert client.get("/resources/resource-1/blocks").json() == []


def test_exception_crud_round_trip():
    client = _seeded_client()
    created = client.post("/resources/resource-1/exceptions", json={
        "day": "2026-12-25", "starts_at": "00:00:00", "ends_at": "23:59:00", "available": False,
    })
    assert created.status_code == 201
    exception_id = created.json()["id"]

    updated = client.put(f"/resources/resource-1/exceptions/{exception_id}", json={
        "day": "2026-12-25", "starts_at": "09:00:00", "ends_at": "13:00:00", "available": True,
    })
    assert updated.status_code == 200
    assert updated.json()["available"] is True

    assert client.delete(f"/resources/resource-1/exceptions/{exception_id}").status_code == 204
    assert client.get("/resources/resource-1/exceptions").json() == []


def test_booking_requires_configured_availability():
    client = _seeded_client()
    response = _book(client)
    assert response.status_code == 409


def test_booking_succeeds_once_a_window_is_configured():
    client = _seeded_client()
    client.post("/resources/resource-1/availability", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert _book(client).status_code == 201


def test_block_prevents_booking_within_an_otherwise_open_window():
    client = _seeded_client()
    client.post("/resources/resource-1/availability", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    client.post("/resources/resource-1/blocks", json={
        "starts_at": "2026-07-20T10:00:00", "ends_at": "2026-07-20T11:00:00", "reason": "bloqueo",
    })
    assert _book(client, hour=10).status_code == 409
    assert _book(client, hour=12).status_code == 201
