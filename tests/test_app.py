from fastapi.testclient import TestClient

from app.main import create_app


def _seeded_client():
    client = TestClient(create_app("sqlite:///:memory:"))
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


def test_health_reports_ok():
    client = TestClient(create_app("sqlite:///:memory:"))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "product": "medlibra"}


def test_medlibra_creates_and_confirms_appointment():
    client = _seeded_client()
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert created.status_code == 201
    confirmed = client.post(f"/appointments/{created.json()['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


def test_create_appointment_rejects_unknown_service():
    client = _seeded_client()
    response = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "missing-service",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert response.status_code == 404


def test_create_appointment_rejects_conflicting_slot():
    client = _seeded_client()
    payload = {
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    }
    first = client.post("/appointments", json=payload)
    assert first.status_code == 201
    second = client.post("/appointments", json=payload)
    assert second.status_code == 409


def test_create_appointment_rejects_slot_outside_availability():
    client = _seeded_client()
    response = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T20:00:00",
    })
    assert response.status_code == 409


def test_confirm_unknown_appointment_returns_404():
    client = TestClient(create_app("sqlite:///:memory:"))
    response = client.post("/appointments/missing/confirm")
    assert response.status_code == 404


def test_confirming_twice_returns_409():
    client = _seeded_client()
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    assert client.post(f"/appointments/{appointment_id}/confirm").status_code == 200
    assert client.post(f"/appointments/{appointment_id}/confirm").status_code == 409


def test_cancel_appointment_with_reason():
    client = _seeded_client()
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


def test_cancel_appointment_without_reason_is_optional():
    client = _seeded_client()
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    response = client.post(f"/appointments/{created.json()['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["reason"] is None


def test_cancel_unknown_appointment_returns_404():
    client = TestClient(create_app("sqlite:///:memory:"))
    assert client.post("/appointments/missing/cancel").status_code == 404


def test_cancelling_twice_returns_409():
    client = _seeded_client()
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    appointment_id = created.json()["id"]
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 200
    assert client.post(f"/appointments/{appointment_id}/cancel").status_code == 409


def test_reschedule_appointment_with_reason():
    client = _seeded_client()
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


def test_reschedule_unknown_appointment_returns_404():
    client = TestClient(create_app("sqlite:///:memory:"))
    response = client.post("/appointments/missing/reschedule", json={
        "starts_at": "2026-07-20T12:00:00",
    })
    assert response.status_code == 404


def test_reschedule_rejects_conflicting_slot():
    client = _seeded_client()
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


def test_rescheduling_a_cancelled_appointment_returns_409():
    client = _seeded_client()
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
