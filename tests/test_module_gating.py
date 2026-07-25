from fastapi.testclient import TestClient


def _disable(admin_client: TestClient, modulo: str) -> None:
    admin_client.app.state.modules.set_enabled(modulo, False)


def _seeded_appointment(client: TestClient, price: str | None = "1000.00") -> str:
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    if price is not None:
        client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": price})
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_all_modules_enabled_by_default(admin_client: TestClient):
    assert admin_client.app.state.modules.get_all() == {
        "recordatorios": True, "senas": True, "facturacion": True, "dashboard": True,
    }


def test_reminders_dispatch_requires_recordatorios_module(admin_client: TestClient):
    _disable(admin_client, "recordatorios")
    response = admin_client.post("/reminders/dispatch")
    assert response.status_code == 403


def test_reminders_dispatch_works_when_module_enabled(admin_client: TestClient):
    response = admin_client.post("/reminders/dispatch")
    assert response.status_code == 200


def test_deposits_require_senas_module(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    confirmed = client.post(f"/appointments/{appointment_id}/confirm")
    assert confirmed.status_code == 200

    _disable(client, "senas")
    response = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "500.00"})
    assert response.status_code == 403


def test_billing_config_requires_facturacion_module(admin_client: TestClient):
    _disable(admin_client, "facturacion")
    assert admin_client.get("/config/arca").status_code == 403


def test_dashboard_requires_dashboard_module(admin_client: TestClient):
    _disable(admin_client, "dashboard")
    response = admin_client.get("/dashboard?date_from=2026-07-20&date_to=2026-07-20")
    assert response.status_code == 403


def test_complete_skips_invoicing_when_facturacion_module_disabled(admin_client: TestClient):
    client = admin_client
    appointment_id = _seeded_appointment(client)
    confirmed = client.post(f"/appointments/{appointment_id}/confirm")
    assert confirmed.status_code == 200

    _disable(client, "facturacion")
    # Sin el modulo, completar el turno nunca pide medio_pago ni factura,
    # aunque el servicio tenga precio configurado -- el plan no incluye
    # facturacion, pero eso nunca bloquea completar el turno en si.
    response = client.post(f"/appointments/{appointment_id}/complete")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["factura"] is None


def test_turnos_and_catalog_are_never_gated(admin_client: TestClient):
    client = admin_client
    for modulo in ("recordatorios", "senas", "facturacion", "dashboard"):
        _disable(client, modulo)

    appointment_id = _seeded_appointment(client)
    assert client.post(f"/appointments/{appointment_id}/confirm").status_code == 200


def test_clinical_domain_is_never_gated(admin_client: TestClient):
    """A diferencia de Gestiolibra, MedLibra deja todo el dominio clinico
    (pacientes, historia clinica, recetas, estudios, documentos,
    consentimientos) fuera de cualquier gating por plan (ver
    DECISIONS.md ADR-018) -- necesidad profesional basica de un
    consultorio, no un extra comercial."""
    client = admin_client
    for modulo in ("recordatorios", "senas", "facturacion", "dashboard"):
        _disable(client, modulo)

    patient = client.post("/patients", json={"id": "patient-2", "name": "Carlos"})
    assert patient.status_code == 201

    note = client.post("/patients/patient-2/notes", json={
        "author": "Dr. Perez", "text": "Evolucion favorable",
    })
    assert note.status_code == 201

    prescription = client.post("/patients/patient-2/prescriptions", json={
        "author": "Dr. Perez",
        "items": [{"medication": "Ibuprofeno", "dosage": "400mg", "instructions": "cada 8hs"}],
    })
    assert prescription.status_code == 201

    study_order = client.post("/patients/patient-2/study-orders", json={
        "author": "Dr. Perez",
        "items": [{"study_type": "Analisis de sangre", "reason": "control"}],
    })
    assert study_order.status_code == 201

    consent = client.post("/patients/patient-2/consents", json={
        "author": "Dr. Perez", "procedure": "Extraccion",
        "granted_by": "patient", "text": "Acepto el procedimiento",
    })
    assert consent.status_code == 201
