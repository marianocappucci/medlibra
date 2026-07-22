import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_patient(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    return client


def test_create_and_list_study_orders(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez",
        "items": [
            {"study_type": "Analisis de sangre", "reason": "control anual"},
            {"study_type": "Radiografia de torax", "reason": None},
        ],
    })
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "patient-1"
    assert body["author"] == "Dr. Perez"
    assert [item["study_type"] for item in body["items"]] == ["Analisis de sangre", "Radiografia de torax"]
    assert body["items"][0]["reason"] == "control anual"
    assert body["items"][0]["results"] == []

    listed = client.get("/patients/patient-1/study-orders")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/patients/patient-1/study-orders/{body['id']}")
    assert fetched.status_code == 200
    assert len(fetched.json()["items"]) == 2


def test_study_order_requires_at_least_one_item(client_with_patient: TestClient):
    response = client_with_patient.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [],
    })
    assert response.status_code == 422


def test_study_orders_for_unknown_patient_return_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing/study-orders").status_code == 404
    assert admin_client.post(
        "/patients/missing/study-orders",
        json={"author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}]},
    ).status_code == 404


def test_study_order_update_is_not_supported(client_with_patient: TestClient):
    """Los pedidos de estudios son append-only por diseno: no existe PUT."""
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    order_id = created.json()["id"]
    response = client.put(
        f"/patients/patient-1/study-orders/{order_id}",
        json={"author": "Dr. Perez", "items": [{"study_type": "Otro"}]},
    )
    assert response.status_code == 405


def test_add_and_list_results_for_an_item(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez",
        "items": [
            {"study_type": "Analisis de sangre"},
            {"study_type": "Radiografia de torax"},
        ],
    })
    order_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]

    result = client.post(
        f"/patients/patient-1/study-orders/{order_id}/items/{item_id}/results",
        json={"author": "Dr. Perez", "text": "Hemograma normal"},
    )
    assert result.status_code == 201
    assert result.json()["item_id"] == item_id
    assert result.json()["text"] == "Hemograma normal"

    fetched = client.get(f"/patients/patient-1/study-orders/{order_id}").json()
    assert len(fetched["items"][0]["results"]) == 1
    assert fetched["items"][1]["results"] == []


def test_a_single_item_can_have_multiple_results(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    order_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]

    client.post(
        f"/patients/patient-1/study-orders/{order_id}/items/{item_id}/results",
        json={"author": "Dr. Perez", "text": "Primer resultado"},
    )
    client.post(
        f"/patients/patient-1/study-orders/{order_id}/items/{item_id}/results",
        json={"author": "Dr. Perez", "text": "Resultado ampliado"},
    )
    fetched = client.get(f"/patients/patient-1/study-orders/{order_id}").json()
    assert [r["text"] for r in fetched["items"][0]["results"]] == ["Primer resultado", "Resultado ampliado"]


def test_result_for_unknown_item_returns_404(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    order_id = created.json()["id"]
    response = client.post(
        f"/patients/patient-1/study-orders/{order_id}/items/missing/results",
        json={"author": "Dr. Perez", "text": "x"},
    )
    assert response.status_code == 404


def test_admin_can_delete_a_study_order(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    order_id = created.json()["id"]
    assert client.delete(f"/patients/patient-1/study-orders/{order_id}").status_code == 204
    assert client.get(f"/patients/patient-1/study-orders/{order_id}").status_code == 404


def test_admin_can_delete_a_result(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    order_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]
    result = client.post(
        f"/patients/patient-1/study-orders/{order_id}/items/{item_id}/results",
        json={"author": "Dr. Perez", "text": "x"},
    )
    result_id = result.json()["id"]
    deleted = client.delete(
        f"/patients/patient-1/study-orders/{order_id}/items/{item_id}/results/{result_id}",
    )
    assert deleted.status_code == 204
    fetched = client.get(f"/patients/patient-1/study-orders/{order_id}").json()
    assert fetched["items"][0]["results"] == []


def test_cannot_delete_a_patient_with_study_orders(client_with_patient: TestClient):
    client = client_with_patient
    client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    response = client.delete("/patients/patient-1")
    assert response.status_code == 409


def test_can_delete_a_patient_once_their_study_orders_are_gone(client_with_patient: TestClient):
    client = client_with_patient
    created = client.post("/patients/patient-1/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    client.delete(f"/patients/patient-1/study-orders/{created.json()['id']}")
    assert client.delete("/patients/patient-1").status_code == 204


def test_staff_can_create_orders_and_results_but_not_delete_them(staff_client: TestClient):
    staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    created = staff_client.post("/patients/patient-2/study-orders", json={
        "author": "Dr. Perez", "items": [{"study_type": "Analisis de sangre"}],
    })
    assert created.status_code == 201
    order_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]

    result = staff_client.post(
        f"/patients/patient-2/study-orders/{order_id}/items/{item_id}/results",
        json={"author": "Dr. Perez", "text": "x"},
    )
    assert result.status_code == 201

    assert staff_client.delete(f"/patients/patient-2/study-orders/{order_id}").status_code == 403
    assert staff_client.delete(
        f"/patients/patient-2/study-orders/{order_id}/items/{item_id}/results/{result.json()['id']}",
    ).status_code == 403
