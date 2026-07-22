import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_patient(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def test_create_and_list_notes(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/notes", json={
        "author": "Dr. Perez", "text": "Primera consulta, sin antecedentes relevantes.",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "patient-1"
    assert body["author"] == "Dr. Perez"

    listed = client.get("/patients/patient-1/notes")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/patients/patient-1/notes/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["text"] == body["text"]


def test_notes_are_ordered_by_creation(client_with_patient: TestClient):
    client = client_with_patient
    client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "Primera"})
    client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "Segunda"})
    listed = client.get("/patients/patient-1/notes").json()
    assert [item["text"] for item in listed] == ["Primera", "Segunda"]


def test_notes_for_unknown_patient_return_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing/notes").status_code == 404
    assert admin_client.post(
        "/patients/missing/notes", json={"author": "Dr. Perez", "text": "x"},
    ).status_code == 404


def test_note_update_is_not_supported(client_with_patient: TestClient):
    """Historia clinica is append-only by design: no PUT endpoint exists."""
    client = client_with_patient
    created = client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "x"})
    note_id = created.json()["id"]
    response = client.put(
        f"/patients/patient-1/notes/{note_id}", json={"author": "Dr. Perez", "text": "y"},
    )
    assert response.status_code == 405


def test_admin_can_delete_a_note(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "x"})
    note_id = created.json()["id"]
    assert client.delete(f"/patients/patient-1/notes/{note_id}").status_code == 204
    assert client.get(f"/patients/patient-1/notes/{note_id}").status_code == 404


def test_delete_unknown_note_returns_404(client_with_patient: TestClient):
    assert client_with_patient.delete("/patients/patient-1/notes/missing").status_code == 404


def test_cannot_delete_a_patient_with_clinical_notes(client_with_patient: TestClient):
    client = client_with_patient
    client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "x"})
    response = client.delete("/patients/patient-1")
    assert response.status_code == 409


def test_can_delete_a_patient_once_their_notes_are_gone(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/notes", json={"author": "Dr. Perez", "text": "x"})
    client.delete(f"/patients/patient-1/notes/{created.json()['id']}")
    assert client.delete("/patients/patient-1").status_code == 204


def test_staff_can_create_notes_but_not_delete_them(staff_client: TestClient):
    staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    created = staff_client.post("/patients/patient-2/notes", json={
        "author": "Dr. Perez", "text": "primera consulta",
    })
    assert created.status_code == 201
    assert staff_client.delete(
        f"/patients/patient-2/notes/{created.json()['id']}",
    ).status_code == 403
