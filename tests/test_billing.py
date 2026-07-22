from fastapi.testclient import TestClient


def _seeded_appointment(
    client: TestClient, patient: dict | None = None, price: str | None = "1000.00",
) -> str:
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json=patient or {"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    if price is not None:
        client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": price})
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": (patient or {}).get("id", "patient-1"), "starts_at": "2099-01-01T10:00:00",
    })
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]
    confirmed = client.post(f"/appointments/{appointment_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return appointment_id


def test_get_arca_config_defaults_to_none(admin_client: TestClient):
    response = admin_client.get("/config/arca")
    assert response.status_code == 200
    assert response.json() is None


def test_set_and_get_arca_config(admin_client: TestClient):
    client = admin_client
    set_response = client.put("/config/arca", json={
        "cuit": "20111222339", "punto_venta": 3,
        "certificado_path": "cert.crt", "clave_path": "clave.key",
        "ambiente": "homologacion",
    })
    assert set_response.status_code == 200
    assert set_response.json()["punto_venta"] == 3

    fetched = client.get("/config/arca")
    assert fetched.status_code == 200
    assert fetched.json()["cuit"] == "20111222339"

    updated = client.put("/config/arca", json={
        "cuit": "20111222339", "punto_venta": 5,
        "certificado_path": "cert.crt", "clave_path": "clave.key",
    })
    assert updated.status_code == 200
    assert updated.json()["punto_venta"] == 5


def test_complete_without_price_configured_does_not_invoice(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client, price=None)
    response = client.post(f"/appointments/{appointment_id}/complete")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["factura"] is None


def test_complete_with_price_and_no_deposit_requires_medio_pago(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    response = client.post(f"/appointments/{appointment_id}/complete")
    assert response.status_code == 422


def test_complete_with_price_and_no_deposit_invoices_full_amount(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    response = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert response.status_code == 200
    factura = response.json()["factura"]
    assert factura is not None
    assert factura["total"] == 1000.0
    assert factura["cae"]  # dev mock genera un CAE simulado


def test_complete_with_paid_deposit_covering_full_price_needs_no_medio_pago(
    admin_client: TestClient,
):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    deposit = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "1000.00"})
    deposit_id = deposit.json()["id"]
    client.post(f"/deposits/{deposit_id}/mark-paid", json={"medio_pago": "transferencia"})

    response = client.post(f"/appointments/{appointment_id}/complete")
    assert response.status_code == 200
    factura = response.json()["factura"]
    assert factura is not None
    assert factura["total"] == 1000.0


def test_complete_with_partial_deposit_requires_medio_pago_for_balance(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    deposit = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "400.00"})
    deposit_id = deposit.json()["id"]
    client.post(f"/deposits/{deposit_id}/mark-paid", json={"medio_pago": "mercadopago"})

    without_medio_pago = client.post(f"/appointments/{appointment_id}/complete")
    assert without_medio_pago.status_code == 422

    with_medio_pago = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert with_medio_pago.status_code == 200
    assert with_medio_pago.json()["factura"]["total"] == 1000.0


def test_factura_type_is_a_for_responsable_inscripto_patient(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client, patient={
        "id": "patient-1", "name": "Carlos",
        "cuit": "20111222339", "condicion_iva": "Responsable Inscripto",
    })
    response = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert response.status_code == 200
    assert response.json()["factura"]["tipo"] == 1


def test_factura_type_is_b_for_consumidor_final_patient(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client, patient={
        "id": "patient-1", "name": "Ana", "condicion_iva": "Consumidor Final",
    })
    response = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert response.status_code == 200
    assert response.json()["factura"]["tipo"] == 6


def test_complete_twice_raises_invalid_transition_without_double_billing(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    first = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert second.status_code == 409


def test_config_arca_requires_admin(staff_client: TestClient):
    assert staff_client.get("/config/arca").status_code == 403
