import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_patient(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def _upload(
    client: TestClient, patient_id: str = "patient-1", *,
    filename: str = "informe.pdf", content: bytes = b"%PDF-1.4 contenido de prueba",
    content_type: str = "application/pdf",
    author: str = "Dr. Perez", title: str = "Informe de cardiologia",
    description: str | None = "control de rutina",
):
    data = {"author": author, "title": title}
    if description is not None:
        data["description"] = description
    return client.post(
        f"/patients/{patient_id}/documents",
        data=data, files={"file": (filename, content, content_type)},
    )


def test_upload_and_list_documents(client_with_patient: TestClient):
    client = client_with_patient
    created = _upload(client)
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "patient-1"
    assert body["title"] == "Informe de cardiologia"
    assert body["description"] == "control de rutina"
    assert body["original_filename"] == "informe.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(b"%PDF-1.4 contenido de prueba")

    listed = client.get("/patients/patient-1/documents")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/patients/patient-1/documents/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Informe de cardiologia"


def test_download_document_returns_original_bytes(client_with_patient: TestClient):
    client = client_with_patient
    created = _upload(client, content=b"contenido binario de prueba")
    document_id = created.json()["id"]

    downloaded = client.get(f"/patients/patient-1/documents/{document_id}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"contenido binario de prueba"
    assert downloaded.headers["content-type"] == "application/pdf"


def test_upload_rejects_unsupported_extension(client_with_patient: TestClient):
    response = _upload(
        client_with_patient, filename="virus.exe", content_type="application/octet-stream",
    )
    assert response.status_code == 422


def test_upload_rejects_oversized_file(client_with_patient: TestClient):
    huge = b"0" * (20 * 1024 * 1024 + 1)
    response = _upload(client_with_patient, content=huge)
    assert response.status_code == 422


def test_upload_without_description_is_optional(client_with_patient: TestClient):
    response = _upload(client_with_patient, description=None)
    assert response.status_code == 201
    assert response.json()["description"] is None


def test_documents_for_unknown_patient_return_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing/documents").status_code == 404
    assert _upload(admin_client, patient_id="missing").status_code == 404


def test_document_update_is_not_supported(client_with_patient: TestClient):
    """Documentos clinicos son append-only por diseno: no existe PUT."""
    client = client_with_patient
    created = _upload(client)
    document_id = created.json()["id"]
    response = client.put(
        f"/patients/patient-1/documents/{document_id}", json={"title": "otro"},
    )
    assert response.status_code == 405


def test_admin_can_delete_a_document(client_with_patient: TestClient):
    client = client_with_patient
    created = _upload(client)
    document_id = created.json()["id"]
    assert client.delete(f"/patients/patient-1/documents/{document_id}").status_code == 204
    assert client.get(f"/patients/patient-1/documents/{document_id}").status_code == 404
    assert client.get(f"/patients/patient-1/documents/{document_id}/file").status_code == 404


def test_delete_unknown_document_returns_404(client_with_patient: TestClient):
    assert client_with_patient.delete("/patients/patient-1/documents/missing").status_code == 404


def test_cannot_delete_a_patient_with_documents(client_with_patient: TestClient):
    client = client_with_patient
    _upload(client)
    response = client.delete("/patients/patient-1")
    assert response.status_code == 409


def test_can_delete_a_patient_once_their_documents_are_gone(client_with_patient: TestClient):
    client = client_with_patient
    created = _upload(client)
    client.delete(f"/patients/patient-1/documents/{created.json()['id']}")
    assert client.delete("/patients/patient-1").status_code == 204


def test_staff_can_upload_documents_but_not_delete_them(staff_client: TestClient):
    staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    created = _upload(staff_client, patient_id="patient-2")
    assert created.status_code == 201
    assert staff_client.delete(
        f"/patients/patient-2/documents/{created.json()['id']}",
    ).status_code == 403
