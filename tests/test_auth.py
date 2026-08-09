from fastapi.testclient import TestClient

from app.main import create_app
from conftest import https_client
from tests.motor import fresh_database_url


def test_login_with_bootstrap_admin_succeeds():
    client = https_client(create_app(fresh_database_url()))
    response = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"


def test_login_with_wrong_password_returns_401():
    client = https_client(create_app(fresh_database_url()))
    response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401


def test_login_with_unknown_username_returns_401():
    client = https_client(create_app(fresh_database_url()))
    response = client.post("/auth/login", json={"username": "missing", "password": "whatever"})
    assert response.status_code == 401


def test_me_without_login_returns_401():
    client = https_client(create_app(fresh_database_url()))
    assert client.get("/auth/me").status_code == 401


def test_me_after_login_returns_current_user(admin_client: TestClient):
    response = admin_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_clears_the_session(admin_client: TestClient):
    assert admin_client.get("/auth/me").status_code == 200
    assert admin_client.post("/auth/logout").status_code == 200
    assert admin_client.get("/auth/me").status_code == 401


def test_health_does_not_require_authentication():
    client = https_client(create_app(fresh_database_url()))
    assert client.get("/health").status_code == 200
