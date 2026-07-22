from fastapi.testclient import TestClient


def test_resource_crud_round_trip(admin_client: TestClient):
    client = admin_client
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    created = client.post("/resources", json={
        "id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1",
    })
    assert created.status_code == 201
    assert created.json()["branch_id"] == "branch-1"

    assert client.get("/resources/resource-1").json()["name"] == "Consultorio 1"
    assert len(client.get("/resources").json()) == 1

    updated = client.put("/resources/resource-1", json={"name": "Consultorio renombrado", "active": False})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Consultorio renombrado"
    assert updated.json()["branch_id"] is None
    assert updated.json()["active"] is False

    assert client.delete("/resources/resource-1").status_code == 204
    assert client.get("/resources/resource-1").status_code == 404


def test_resource_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/resources/missing").status_code == 404
    assert admin_client.put("/resources/missing", json={"name": "x"}).status_code == 404
    assert admin_client.delete("/resources/missing").status_code == 404


def test_resource_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1"})
    response = admin_client.post("/resources", json={"id": "resource-1", "name": "Otro"})
    assert response.status_code == 409
