import pytest
from fastapi.testclient import TestClient

from conftest import https_client
from tests.motor import fresh_database_url


@pytest.fixture
def seeded_client(admin_client: TestClient) -> TestClient:
    client = admin_client
    assert client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"}).status_code == 201
    assert client.post("/resources", json={
        "id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1",
    }).status_code == 201
    assert client.post("/services", json={
        "id": "service-1", "name": "Consulta clinica", "duration_minutes": 30,
    }).status_code == 201
    assert client.post("/patients", json={"id": "patient-1", "name": "Ana"}).status_code == 201
    # 2026-07-20 is a Monday (weekday 0).
    assert client.post("/resources/resource-1/availability", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "18:00:00",
    }).status_code == 201
    return client


def test_health_reports_ok(admin_client: TestClient):
    response = admin_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "product": "medlibra"}


def test_medlibra_creates_and_confirms_appointment(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert created.status_code == 201
    confirmed = client.post(f"/appointments/{created.json()['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


def test_create_appointment_rejects_unknown_service(seeded_client: TestClient):
    response = seeded_client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "missing-service",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert response.status_code == 404


def test_create_appointment_rejects_conflicting_slot(seeded_client: TestClient):
    client = seeded_client
    payload = {
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    }
    first = client.post("/appointments", json=payload)
    assert first.status_code == 201
    second = client.post("/appointments", json=payload)
    assert second.status_code == 409


def test_create_appointment_rejects_slot_outside_availability(seeded_client: TestClient):
    response = seeded_client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T20:00:00",
    })
    assert response.status_code == 409


def test_confirm_unknown_appointment_returns_404(admin_client: TestClient):
    response = admin_client.post("/appointments/missing/confirm")
    assert response.status_code == 404


def test_confirming_twice_returns_409(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    assert client.post(f"/appointments/{appointment_id}/confirm").status_code == 200
    assert client.post(f"/appointments/{appointment_id}/confirm").status_code == 409


def test_cancel_appointment_with_reason(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    response = client.post(
        f"/appointments/{appointment_id}/cancel", json={"reason": "paciente no puede asistir"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": appointment_id, "status": "cancelled", "reason": "paciente no puede asistir",
    }


def test_cancel_appointment_without_reason_is_optional(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    response = client.post(f"/appointments/{created.json()['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["reason"] is None


def test_cancel_unknown_appointment_returns_404(admin_client: TestClient):
    assert admin_client.post("/appointments/missing/cancel").status_code == 404


def test_cancelling_twice_returns_409(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 200
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 409


def test_reschedule_appointment_with_reason(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    response = client.post(f"/appointments/{appointment_id}/reschedule", json={
        "starts_at": "2026-07-20T12:00:00", "reason": "pidio otro horario",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["reason"] == "pidio otro horario"
    assert body["starts_at"].startswith("2026-07-20T12:00:00")


def test_reschedule_unknown_appointment_returns_404(admin_client: TestClient):
    response = admin_client.post("/appointments/missing/reschedule", json={
        "starts_at": "2026-07-20T12:00:00",
    })
    assert response.status_code == 404


def test_reschedule_rejects_conflicting_slot(seeded_client: TestClient):
    client = seeded_client
    first = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    second = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T14:00:00",
    })
    response = client.post(f"/appointments/{first.json()['id']}/reschedule", json={
        "starts_at": "2026-07-20T14:00:00",
    })
    assert response.status_code == 409
    assert second.status_code == 201


def test_rescheduling_a_cancelled_appointment_returns_409(seeded_client: TestClient):
    client = seeded_client
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 200
    response = client.post(f"/appointments/{appointment_id}/reschedule", json={
        "starts_at": "2026-07-20T12:00:00",
    })
    assert response.status_code == 409


def test_staff_can_manage_own_appointments_and_patients_but_not_catalog(
    seeded_client: TestClient, staff_client: TestClient,
):
    # seeded_client is the admin session that set up branch/resource/service/patient.
    created = staff_client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert created.status_code == 201
    appointment_id = created.json()["id"]
    assert staff_client.post(f"/appointments/{appointment_id}/confirm").status_code == 200
    assert staff_client.post(
        f"/appointments/{appointment_id}/cancel", json={"reason": "no vino"},
    ).status_code == 200

    assert staff_client.get("/patients").status_code == 200
    note = staff_client.post("/patients/patient-1/notes", json={
        "author": "Dr. Perez", "text": "primera consulta",
    })
    assert note.status_code == 201

    assert staff_client.get("/branches").status_code == 403
    assert staff_client.post("/resources", json={"id": "r2", "name": "Consultorio 2"}).status_code == 403
    assert staff_client.get("/users").status_code == 403
    assert staff_client.delete("/patients/patient-1").status_code == 403
    assert staff_client.delete(f"/patients/patient-1/notes/{note.json()['id']}").status_code == 403


def test_unauthenticated_request_returns_401():
    from app.main import create_app
    client = https_client(create_app(fresh_database_url()))
    assert client.get("/branches").status_code == 401
    assert client.post("/appointments", json={}).status_code == 401
