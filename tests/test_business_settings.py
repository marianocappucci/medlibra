from decimal import Decimal

from fastapi.testclient import TestClient


def test_business_settings_defaults(admin_client: TestClient):
    response = admin_client.get("/business")
    assert response.status_code == 200
    body = response.json()
    assert body["business_name"] is None
    assert body["currency"] == "ARS"
    # 21% arranca como default de la instancia: es el valor que estaba
    # hardcodeado en billing antes de la migracion 0012, asi que la feature
    # de alicuota configurable no le cambia la facturacion a nadie.
    # Ver test_iva_rates.py.
    assert Decimal(body["default_iva_rate"]) == Decimal("0.21")


def test_business_settings_update_round_trip(admin_client: TestClient):
    updated = admin_client.put("/business", json={
        "business_name": "Consultorio Dr. Perez", "currency": "USD",
    })
    assert updated.status_code == 200
    assert updated.json()["business_name"] == "Consultorio Dr. Perez"
    assert updated.json()["currency"] == "USD"

    fetched = admin_client.get("/business").json()
    assert fetched["business_name"] == "Consultorio Dr. Perez"
    assert fetched["currency"] == "USD"


def test_business_settings_requires_admin(staff_client: TestClient):
    assert staff_client.get("/business").status_code == 403
