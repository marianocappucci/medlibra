from fastapi.testclient import TestClient


def test_business_settings_defaults(admin_client: TestClient):
    response = admin_client.get("/business")
    assert response.status_code == 200
    assert response.json() == {"business_name": None, "currency": "ARS"}


def test_business_settings_update_round_trip(admin_client: TestClient):
    updated = admin_client.put("/business", json={
        "business_name": "Consultorio Dr. Perez", "currency": "USD",
    })
    assert updated.status_code == 200
    assert updated.json() == {"business_name": "Consultorio Dr. Perez", "currency": "USD"}

    fetched = admin_client.get("/business")
    assert fetched.json() == {"business_name": "Consultorio Dr. Perez", "currency": "USD"}


def test_business_settings_requires_admin(staff_client: TestClient):
    assert staff_client.get("/business").status_code == 403
