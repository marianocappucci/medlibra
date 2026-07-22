import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_patient(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def _create(client: TestClient, patient_id: str = "patient-1", **overrides):
    data = {
        "author": "Dr. Perez", "procedure": "Endoscopia digestiva alta",
        "granted_by": "paciente", "text": "Se explicaron riesgos y beneficios, el paciente acepta.",
    }
    data.update(overrides)
    return client.post(f"/patients/{patient_id}/consents", json=data)


def test_create_and_list_consents(client_with_patient: TestClient):
    client = client_with_patient
    created = _create(client)
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "patient-1"
    assert body["author"] == "Dr. Perez"
    assert body["procedure"] == "Endoscopia digestiva alta"
    assert body["granted_by"] == "paciente"

    listed = client.get("/patients/patient-1/consents")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/patients/patient-1/consents/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["text"] == body["text"]


def test_consent_can_be_granted_by_a_guardian(client_with_patient: TestClient):
    created = _create(client_with_patient, granted_by="Juan Perez (padre)")
    assert created.status_code == 201
    assert created.json()["granted_by"] == "Juan Perez (padre)"


def test_consents_are_ordered_by_creation(client_with_patient: TestClient):
    client = client_with_patient
    _create(client, procedure="Primera")
    _create(client, procedure="Segunda")
    listed = client.get("/patients/patient-1/consents").json()
    assert [item["procedure"] for item in listed] == ["Primera", "Segunda"]


def test_consents_for_unknown_patient_return_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing/consents").status_code == 404
    assert _create(admin_client, patient_id="missing").status_code == 404


def test_consent_update_is_not_supported(client_with_patient: TestClient):
    """Consentimientos son append-only por diseno: no existe PUT."""
    client = client_with_patient
    created = _create(client)
    consent_id = created.json()["id"]
    response = client.put(
        f"/patients/patient-1/consents/{consent_id}", json={"procedure": "otro"},
    )
    assert response.status_code == 405


def test_revoking_consent_is_a_new_record_not_an_edit(client_with_patient: TestClient):
    """No hay endpoint de revocacion: retirar un consentimiento se modela
    como un consentimiento nuevo, el original nunca se toca."""
    client = client_with_patient
    original = _create(client)
    withdrawal = _create(
        client, granted_by="paciente",
        text="El paciente retira el consentimiento otorgado el " + original.json()["created_at"],
    )
    assert withdrawal.status_code == 201
    listed = client.get("/patients/patient-1/consents").json()
    assert len(listed) == 2
    assert listed[0]["id"] == original.json()["id"]
    assert listed[0]["text"] == original.json()["text"]  # el original no cambio


def test_admin_can_delete_a_consent(client_with_patient: TestClient):
    client = client_with_patient
    created = _create(client)
    consent_id = created.json()["id"]
    assert client.delete(f"/patients/patient-1/consents/{consent_id}").status_code == 204
    assert client.get(f"/patients/patient-1/consents/{consent_id}").status_code == 404


def test_delete_unknown_consent_returns_404(client_with_patient: TestClient):
    assert client_with_patient.delete("/patients/patient-1/consents/missing").status_code == 404


def test_cannot_delete_a_patient_with_consents(client_with_patient: TestClient):
    client = client_with_patient
    _create(client)
    response = client.delete("/patients/patient-1")
    assert response.status_code == 409


def test_can_delete_a_patient_once_their_consents_are_gone(client_with_patient: TestClient):
    client = client_with_patient
    created = _create(client)
    client.delete(f"/patients/patient-1/consents/{created.json()['id']}")
    assert client.delete("/patients/patient-1").status_code == 204


def test_staff_can_create_consents_but_not_delete_them(staff_client: TestClient):
    staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    created = _create(staff_client, patient_id="patient-2")
    assert created.status_code == 201
    assert staff_client.delete(
        f"/patients/patient-2/consents/{created.json()['id']}",
    ).status_code == 403
