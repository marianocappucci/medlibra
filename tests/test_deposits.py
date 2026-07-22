from fastapi.testclient import TestClient


def _seeded_appointment(client: TestClient) -> str:
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })
    return created.json()["id"]


def test_request_and_get_deposit(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)

    created = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    assert created.status_code == 201
    assert created.json()["appointment_id"] == appointment_id
    assert created.json()["amount"] == "1000.00"
    assert created.json()["status"] == "pending"

    fetched = client.get(f"/appointments/{appointment_id}/deposit")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "pending"


def test_get_deposit_not_found_returns_404(admin_client: TestClient):
    appointment_id = _seeded_appointment(admin_client)
    assert admin_client.get(f"/appointments/{appointment_id}/deposit").status_code == 404


def test_admin_marks_deposit_paid(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    created = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    deposit_id = created.json()["id"]

    paid = client.post(f"/deposits/{deposit_id}/mark-paid")
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"


def test_admin_marks_deposit_failed(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    created = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    deposit_id = created.json()["id"]

    failed = client.post(f"/deposits/{deposit_id}/mark-failed")
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"


def test_admin_refunds_a_paid_deposit(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    created = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    deposit_id = created.json()["id"]
    client.post(f"/deposits/{deposit_id}/mark-paid")

    refunded = client.post(f"/deposits/{deposit_id}/refund")
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"


def test_cannot_refund_a_pending_deposit(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    created = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    deposit_id = created.json()["id"]

    response = client.post(f"/deposits/{deposit_id}/refund")
    assert response.status_code == 409


def test_mark_paid_on_unknown_deposit_returns_404(admin_client: TestClient):
    assert admin_client.post("/deposits/missing/mark-paid").status_code == 404


def test_staff_can_request_a_deposit_but_not_confirm_it(staff_client: TestClient, admin_client: TestClient):
    appointment_id = _seeded_appointment(admin_client)
    created = staff_client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    assert created.status_code == 201

    deposit_id = created.json()["id"]
    assert staff_client.post(f"/deposits/{deposit_id}/mark-paid").status_code == 403
