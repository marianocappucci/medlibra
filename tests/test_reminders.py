from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _seeded_client(client: TestClient):
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    return client


def test_dispatch_with_no_appointments_returns_empty_list(admin_client: TestClient):
    response = admin_client.post("/reminders/dispatch")
    assert response.status_code == 200
    assert response.json() == []


def test_dispatch_does_not_send_reminders_far_in_the_future(admin_client: TestClient):
    """Neither default policy (24h, 2h) is due for an appointment years away."""
    client = _seeded_client(admin_client)
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })
    response = client.post("/reminders/dispatch")
    assert response.status_code == 200
    assert response.json() == []


def test_dispatch_sends_due_reminders_and_is_idempotent(admin_client: TestClient):
    client = _seeded_client(admin_client)
    # 90 minutos desde ahora: pasado ambos plazos (24h y 2h) -- ambos
    # disparan juntos en el primer dispatch, ya que ninguno se envio antes.
    starts_at = (datetime.now(timezone.utc) + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S")
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": starts_at,
    })
    assert created.status_code == 201
    appointment_id = created.json()["id"]

    first = client.post("/reminders/dispatch")
    assert first.status_code == 200
    sent = first.json()
    assert {(item["appointment_id"], item["policy_id"]) for item in sent} == {
        (appointment_id, "24h"), (appointment_id, "2h"),
    }

    second = client.post("/reminders/dispatch")
    assert second.json() == []  # ya enviados, el ledger evita un duplicado


def test_dispatch_requires_admin(staff_client: TestClient):
    assert staff_client.post("/reminders/dispatch").status_code == 403
