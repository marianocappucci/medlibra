from fastapi.testclient import TestClient


def test_patient_crud_round_trip(admin_client: TestClient):
    client = admin_client
    created = client.post("/patients", json={
        "id": "patient-1", "name": "Ana", "phone": "123",
        "dni": "30111222", "birth_date": "1990-05-01",
    })
    assert created.status_code == 201
    assert created.json() == {
        "id": "patient-1", "name": "Ana", "phone": "123", "email": None,
        "active": True, "dni": "30111222", "birth_date": "1990-05-01",
    }

    fetched = client.get("/patients/patient-1")
    assert fetched.status_code == 200
    assert fetched.json()["dni"] == "30111222"

    assert len(client.get("/patients").json()) == 1

    updated = client.put("/patients/patient-1", json={
        "name": "Ana Renombrada", "dni": "30111222", "birth_date": "1990-05-02",
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ana Renombrada"
    assert updated.json()["birth_date"] == "1990-05-02"

    assert client.delete("/patients/patient-1").status_code == 204
    assert client.get("/patients/patient-1").status_code == 404


def test_patient_dni_and_birth_date_are_optional(admin_client: TestClient):
    created = admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    assert created.status_code == 201
    assert created.json()["dni"] is None
    assert created.json()["birth_date"] is None


def test_patient_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing").status_code == 404
    assert admin_client.put("/patients/missing", json={"name": "x"}).status_code == 404
    assert admin_client.delete("/patients/missing").status_code == 404


def test_patient_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    response = admin_client.post("/patients", json={"id": "patient-1", "name": "Otra"})
    assert response.status_code == 409


def test_patient_rejects_invalid_data(admin_client: TestClient):
    response = admin_client.post("/patients", json={"id": "", "name": "Ana"})
    assert response.status_code == 422


def test_staff_can_create_and_read_patients_but_not_delete(staff_client: TestClient):
    created = staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    assert created.status_code == 201
    assert staff_client.get("/patients/patient-2").status_code == 200
    assert staff_client.delete("/patients/patient-2").status_code == 403
