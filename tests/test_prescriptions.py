import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_patient(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def test_create_and_list_prescriptions(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez",
        "items": [
            {"medication": "Ibuprofeno 400mg", "dosage": "1 cada 8hs", "instructions": "con las comidas"},
            {"medication": "Amoxicilina 500mg", "dosage": "1 cada 12hs", "instructions": None},
        ],
    })
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "patient-1"
    assert body["author"] == "Dr. Perez"
    assert [item["medication"] for item in body["items"]] == ["Ibuprofeno 400mg", "Amoxicilina 500mg"]
    assert body["items"][0]["instructions"] == "con las comidas"
    assert body["items"][1]["instructions"] is None

    listed = client.get("/patients/patient-1/prescriptions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/patients/patient-1/prescriptions/{body['id']}")
    assert fetched.status_code == 200
    assert len(fetched.json()["items"]) == 2


def test_prescription_requires_at_least_one_item(client_with_patient: TestClient):
    response = client_with_patient.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [],
    })
    assert response.status_code == 422


def test_prescriptions_are_ordered_by_creation(client_with_patient: TestClient):
    client = client_with_patient
    client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "B", "dosage": "1x1"}],
    })
    listed = client.get("/patients/patient-1/prescriptions").json()
    assert [item["items"][0]["medication"] for item in listed] == ["A", "B"]


def test_prescriptions_for_unknown_patient_return_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing/prescriptions").status_code == 404
    assert admin_client.post(
        "/patients/missing/prescriptions",
        json={"author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}]},
    ).status_code == 404


def test_prescription_update_is_not_supported(client_with_patient: TestClient):
    """Recetas son append-only por diseno: no existe endpoint PUT."""
    client = client_with_patient
    created = client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    prescription_id = created.json()["id"]
    response = client.put(
        f"/patients/patient-1/prescriptions/{prescription_id}",
        json={"author": "Dr. Perez", "items": [{"medication": "B", "dosage": "1x1"}]},
    )
    assert response.status_code == 405


def test_admin_can_delete_a_prescription(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    prescription_id = created.json()["id"]
    assert client.delete(f"/patients/patient-1/prescriptions/{prescription_id}").status_code == 204
    assert client.get(f"/patients/patient-1/prescriptions/{prescription_id}").status_code == 404


def test_delete_unknown_prescription_returns_404(client_with_patient: TestClient):
    assert client_with_patient.delete("/patients/patient-1/prescriptions/missing").status_code == 404


def test_cannot_delete_a_patient_with_prescriptions(client_with_patient: TestClient):
    client = client_with_patient
    client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    response = client.delete("/patients/patient-1")
    assert response.status_code == 409


def test_can_delete_a_patient_once_their_prescriptions_are_gone(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    client.delete(f"/patients/patient-1/prescriptions/{created.json()['id']}")
    assert client.delete("/patients/patient-1").status_code == 204


def test_staff_can_create_prescriptions_but_not_delete_them(staff_client: TestClient):
    staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    created = staff_client.post("/patients/patient-2/prescriptions", json={
        "author": "Dr. Perez", "items": [{"medication": "A", "dosage": "1x1"}],
    })
    assert created.status_code == 201
    assert staff_client.delete(
        f"/patients/patient-2/prescriptions/{created.json()['id']}",
    ).status_code == 403
