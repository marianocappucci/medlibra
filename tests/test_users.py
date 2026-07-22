from fastapi.testclient import TestClient

from conftest import https_client


def test_admin_can_create_list_and_get_a_staff_user(admin_client: TestClient):
    client = admin_client
    created = client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    assert created.status_code == 201
    assert created.json() == {
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "role": "staff", "active": True,
    }
    assert "password" not in created.json()
    assert "password_hash" not in created.json()

    listed = client.get("/users").json()
    assert {item["username"] for item in listed} == {"admin", "staff-1"}

    fetched = client.get("/users/staff-1")
    assert fetched.status_code == 200
    assert fetched.json()["role"] == "staff"


def test_create_user_rejects_invalid_role(admin_client: TestClient):
    response = admin_client.post("/users", json={
        "id": "u1", "username": "u1", "name": "X", "password": "pw", "role": "owner",
    })
    assert response.status_code == 422


def test_create_user_duplicate_username_returns_409(admin_client: TestClient):
    admin_client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    response = admin_client.post("/users", json={
        "id": "staff-2", "username": "staff-1", "name": "Otro",
        "password": "s3cret", "role": "staff",
    })
    assert response.status_code == 409


def test_update_user_role_and_deactivate(admin_client: TestClient):
    client = admin_client
    client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    updated = client.put("/users/staff-1", json={
        "name": "Dr. Perez (jefe)", "role": "admin", "active": False,
    })
    assert updated.status_code == 200
    assert updated.json() == {
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez (jefe)",
        "role": "admin", "active": False,
    }


def test_update_user_not_found_returns_404(admin_client: TestClient):
    response = admin_client.put("/users/missing", json={
        "name": "X", "role": "staff", "active": True,
    })
    assert response.status_code == 404


def test_deactivated_user_cannot_log_in(admin_client: TestClient):
    client = admin_client
    client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    client.put("/users/staff-1", json={"name": "Dr. Perez", "role": "staff", "active": False})

    other = https_client(client.app)
    response = other.post("/auth/login", json={"username": "staff-1", "password": "s3cret"})
    assert response.status_code == 401


def test_update_password_then_login_with_new_password(admin_client: TestClient):
    client = admin_client
    client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "old-pass", "role": "staff",
    })
    assert client.put("/users/staff-1/password", json={"password": "new-pass"}).status_code == 204

    other = https_client(client.app)
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "old-pass"},
    ).status_code == 401
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "new-pass"},
    ).status_code == 200


def test_delete_user(admin_client: TestClient):
    client = admin_client
    client.post("/users", json={
        "id": "staff-1", "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    assert client.delete("/users/staff-1").status_code == 204
    assert client.get("/users/staff-1").status_code == 404


def test_delete_user_not_found_returns_404(admin_client: TestClient):
    assert admin_client.delete("/users/missing").status_code == 404


def test_staff_cannot_manage_users(staff_client: TestClient):
    assert staff_client.get("/users").status_code == 403
    assert staff_client.post("/users", json={
        "id": "x", "username": "x", "name": "X", "password": "pw", "role": "staff",
    }).status_code == 403
