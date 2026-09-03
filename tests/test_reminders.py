from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _inicio_sin_cruzar_medianoche(minutos_adelante, duracion_minutos=30):
    """Momento de inicio para una cita futura que NO cruce la medianoche.

    La disponibilidad se declara por dia de semana y termina a las 23:59, asi
    que un turno que arranca 23:30 o mas tarde termina al dia siguiente y el
    alta lo rechaza con 409 `appointment unavailable`. Sin esto el test
    fallaba en una franja de media hora de cada dia, invisible el resto del
    tiempo (bug real, 2026-07-28).
    """
    ahora = datetime.now(UTC)
    inicio = ahora + timedelta(minutes=minutos_adelante)
    ultimo_del_dia = inicio.replace(
        hour=23, minute=59, second=0, microsecond=0
    ) - timedelta(minutes=duracion_minutos)
    if inicio > ultimo_del_dia:
        # Recortar al ultimo hueco del dia solo sirve si sigue siendo futuro;
        # si ya paso, se arranca el dia siguiente.
        inicio = ultimo_del_dia if ultimo_del_dia > ahora else (
            inicio + timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio


def _seeded_client(client: TestClient):
    # 🔴 **La sucursal va en UTC a proposito**, aunque el default del alta sea
    # Argentina. Este archivo mide plazos de recordatorio contra `now()`, y
    # `_inicio_sin_cruzar_medianoche` arma la hora futura en UTC: con la
    # sucursal en UTC-3 esa hora se leeria como hora de pared y el turno
    # quedaria tres horas mas lejos de lo pedido, cayendo fuera de la ventana
    # de 2 h que el test necesita. El huso no es lo que este archivo prueba
    # -- lo prueban `test_agenda.py` y `test_availability.py`, cuyas sucursales
    # si estan en UTC-3.
    client.post("/branches", json={
        "id": "branch-1", "name": "Consultorio demo", "timezone": "UTC",
    })
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    return client


def test_dispatch_with_no_appointments_returns_empty_list(admin_client: TestClient):
    response = admin_client.post("/reminders/dispatch")
    assert response.status_code == 200
    assert response.json() == []


def test_dispatch_does_not_send_reminders_far_in_the_future(admin_client: TestClient):
    """Neither default policy (24h, 2h) is due for an appointment years away."""
    client = _seeded_client(admin_client)
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })
    response = client.post("/reminders/dispatch")
    assert response.status_code == 200
    assert response.json() == []


def test_dispatch_sends_due_reminders_and_is_idempotent(admin_client: TestClient):
    client = _seeded_client(admin_client)
    # Dentro de ambos plazos (24h y 2h): los dos disparan juntos en el primer
    # dispatch, porque ninguno se envio antes.
    starts_at = _inicio_sin_cruzar_medianoche(90).strftime("%Y-%m-%dT%H:%M:%S")
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": starts_at,
    })
    assert created.status_code == 201
    appointment_id = created.json()["id"]

    first = client.post("/reminders/dispatch")
    assert first.status_code == 200
    sent = first.json()
    assert {(item["appointment_id"], item["policy_id"]) for item in sent} == {
        (appointment_id, "24h"), (appointment_id, "2h"),
    }

    second = client.post("/reminders/dispatch")
    assert second.json() == []  # ya enviados, el ledger evita un duplicado


def test_dispatch_requires_admin(staff_client: TestClient):
    assert staff_client.post("/reminders/dispatch").status_code == 403
