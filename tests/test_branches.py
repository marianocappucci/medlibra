from fastapi.testclient import TestClient


def test_branch_crud_round_trip(admin_client: TestClient):
    client = admin_client
    created = client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    assert created.status_code == 201
    assert created.json() == {"id": "branch-1", "name": "Centro", "active": True, "timezone": "UTC"}

    assert client.get("/branches/branch-1").json()["name"] == "Centro"
    assert len(client.get("/branches").json()) == 1

    updated = client.put("/branches/branch-1", json={
        "name": "Centro renombrado", "active": False, "timezone": "America/Argentina/Buenos_Aires",
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Centro renombrado"
    assert updated.json()["active"] is False

    assert client.delete("/branches/branch-1").status_code == 204
    assert client.get("/branches/branch-1").status_code == 404


def test_branch_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/branches/missing").status_code == 404
    assert admin_client.put("/branches/missing", json={"name": "x"}).status_code == 404
    assert admin_client.delete("/branches/missing").status_code == 404


def test_branch_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    response = admin_client.post("/branches", json={"id": "branch-1", "name": "Otro"})
    assert response.status_code == 409


def test_branch_rejects_invalid_data(admin_client: TestClient):
    response = admin_client.post("/branches", json={"id": "", "name": "Centro"})
    assert response.status_code == 422
