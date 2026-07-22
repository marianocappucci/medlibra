from fastapi.testclient import TestClient


def _seeded_client(client: TestClient):
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    client.post("/branches", json={"id": "branch-2", "name": "Norte"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    return client


def test_set_and_list_prices_per_branch(admin_client: TestClient):
    client = _seeded_client(admin_client)
    created = client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": "5000.00"})
    assert created.status_code == 200
    assert created.json()["branch_id"] == "branch-1"
    assert created.json()["price"] == "5000.00"

    client.put("/services/service-1/prices", json={"branch_id": "branch-2", "price": "5500.50"})

    listed = client.get("/services/service-1/prices").json()
    assert {item["branch_id"]: item["price"] for item in listed} == {
        "branch-1": "5000.00", "branch-2": "5500.50",
    }


def test_setting_price_twice_for_same_branch_updates_it(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": "5000.00"})
    updated = client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": "6000.00"})
    assert updated.status_code == 200
    listed = client.get("/services/service-1/prices").json()
    assert len(listed) == 1
    assert listed[0]["price"] == "6000.00"


def test_delete_price(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": "5000.00"})
    assert client.delete("/services/service-1/prices/branch-1").status_code == 204
    assert client.get("/services/service-1/prices").json() == []


def test_delete_unknown_price_returns_404(admin_client: TestClient):
    client = _seeded_client(admin_client)
    assert client.delete("/services/service-1/prices/branch-1").status_code == 404
