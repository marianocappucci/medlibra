from fastapi.testclient import TestClient


def test_branch_hours_crud_round_trip(admin_client: TestClient):
    client = admin_client
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    created = client.post("/branches/branch-1/hours", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert created.status_code == 201
    hours_id = created.json()["id"]
    assert created.json()["branch_id"] == "branch-1"

    assert len(client.get("/branches/branch-1/hours").json()) == 1

    updated = client.put(f"/branches/branch-1/hours/{hours_id}", json={
        "weekday": 1, "starts_at": "10:00:00", "ends_at": "16:00:00",
    })
    assert updated.status_code == 200
    assert updated.json()["weekday"] == 1

    assert client.delete(f"/branches/branch-1/hours/{hours_id}").status_code == 204
    assert client.get("/branches/branch-1/hours").json() == []


def test_branch_hours_rejects_invalid_weekday(admin_client: TestClient):
    admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    response = admin_client.post("/branches/branch-1/hours", json={
        "weekday": 7, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert response.status_code == 422


def test_branch_hours_rejects_end_before_start(admin_client: TestClient):
    admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    response = admin_client.post("/branches/branch-1/hours", json={
        "weekday": 0, "starts_at": "18:00:00", "ends_at": "09:00:00",
    })
    assert response.status_code == 422


def test_update_unknown_hours_returns_404(admin_client: TestClient):
    admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    response = admin_client.put("/branches/branch-1/hours/999", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert response.status_code == 404


def test_delete_unknown_hours_returns_404(admin_client: TestClient):
    admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    assert admin_client.delete("/branches/branch-1/hours/999").status_code == 404


def _seeded_client(client: TestClient):
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    # Resource has its own availability wide open every day.
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    return client


def _book(client, hour=10):
    return client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": f"2026-07-20T{hour:02d}:00:00",
    })


def test_appointment_without_configured_branch_hours_is_not_gated(admin_client: TestClient):
    """Opt-in gating: a branch with no hours configured doesn't block
    anything -- same behavior as before this feature existed."""
    client = _seeded_client(admin_client)
    assert _book(client, hour=22).status_code == 201


def test_appointment_outside_configured_branch_hours_is_rejected(admin_client: TestClient):
    client = _seeded_client(admin_client)
    # 2026-07-20 is a Monday (weekday 0). Consultorio only open 9-18.
    client.post("/branches/branch-1/hours", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert _book(client, hour=20).status_code == 409


def test_appointment_inside_configured_branch_hours_succeeds(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.post("/branches/branch-1/hours", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    assert _book(client, hour=10).status_code == 201


def test_reschedule_outside_configured_branch_hours_is_rejected(admin_client: TestClient):
    client = _seeded_client(admin_client)
    created = _book(client, hour=10)
    assert created.status_code == 201
    client.post("/branches/branch-1/hours", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    })
    response = client.post(f"/appointments/{created.json()['id']}/reschedule", json={
        "starts_at": "2026-07-20T20:00:00",
    })
    assert response.status_code == 409
