from fastapi.testclient import TestClient


def test_branch_crud_round_trip(admin_client: TestClient):
    client = admin_client
    created = client.post("/branches", json={
        "id": "branch-1", "name": "Centro", "phone": "011-1234", "address": "Av. Siempre Viva 742",
    })
    assert created.status_code == 201
    assert created.json() == {
        # El huso por defecto es el de Argentina, no UTC: es la regla de
        # arranque de la familia y ademas UTC esconde los defectos de
        # conversion, porque con offset cero validar en el terreno equivocado
        # da el mismo resultado que validar en el correcto.
        "id": "branch-1", "name": "Centro", "active": True,
        "timezone": "America/Argentina/Buenos_Aires",
        "phone": "011-1234", "address": "Av. Siempre Viva 742",
    }

    assert client.get("/branches/branch-1").json()["name"] == "Centro"
    assert len(client.get("/branches").json()) == 1

    updated = client.put("/branches/branch-1", json={
        "name": "Centro renombrado", "active": False, "timezone": "America/Argentina/Buenos_Aires",
        "phone": "011-5678",
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Centro renombrado"
    assert updated.json()["active"] is False
    assert updated.json()["phone"] == "011-5678"
    assert updated.json()["address"] is None

    assert client.delete("/branches/branch-1").status_code == 204
    assert client.get("/branches/branch-1").status_code == 404


def test_branch_contact_fields_are_optional(admin_client: TestClient):
    created = admin_client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    assert created.status_code == 201
    assert created.json()["phone"] is None
    assert created.json()["address"] is None


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


def test_cannot_delete_a_branch_with_a_resource_pointing_at_it(admin_client: TestClient):
    client = admin_client
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    response = client.delete("/branches/branch-1")
    assert response.status_code == 409
