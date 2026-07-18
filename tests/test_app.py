from fastapi.testclient import TestClient

from app.main import create_app


def test_medlibra_creates_and_confirms_appointment():
    client = TestClient(create_app("sqlite:///:memory:"))
    seed = client.post("/demo/seed", json={
        "resource_id": "resource-1", "resource_name": "Consultorio 1",
        "service_id": "service-1", "service_name": "Consulta clinica",
        "client_id": "client-1", "client_name": "Ana",
    })
    assert seed.status_code == 200
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "client-1", "starts_at": "2026-07-20T10:00:00",
    })
    assert created.status_code == 201
    confirmed = client.post(f"/appointments/{created.json()['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
