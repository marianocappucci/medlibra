from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _inicio_sin_cruzar_medianoche(minutos_adelante, duracion_minutos=30):
    """Momento de inicio para una cita futura que NO cruce la medianoche.

    La disponibilidad se declara por dia de semana y termina a las 23:59, asi
    que un turno que arranca 23:30 o mas tarde termina al dia siguiente y el
    alta lo rechaza con 409 `appointment unavailable`. Sin esto el test
    fallaba en una franja de media hora de cada dia, invisible el resto del
    tiempo (bug real, 2026-07-28).
    """
    ahora = datetime.now(timezone.utc)
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
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    return client


def _today_range():
    today = datetime.now(timezone.utc).date()
    return today.isoformat(), today.isoformat()


def test_dashboard_with_no_data_returns_zeros(admin_client: TestClient):
    date_from, date_to = _today_range()
    response = admin_client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    body = response.json()
    assert body["turnos"]["total_en_periodo"] == 0
    assert body["turnos"]["hoy"] == 0
    assert body["pacientes"]["total_activos"] == 0
    assert body["pacientes"]["nuevos_en_periodo"] == 0
    assert body["recordatorios_enviados_en_periodo"] == 0
    assert body["senas_pendientes"] == 0


def test_dashboard_counts_appointments_by_status_and_today(admin_client: TestClient):
    # A small offset that can still cross midnight in the rare case the
    # test runs right around 23:59 UTC -- the query range below is
    # derived from the appointment's own date, not from a separate
    # "today" assumption, so it stays correct either way.
    client = _seeded_client(admin_client)
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})

    starts_at_dt = _inicio_sin_cruzar_medianoche(10)
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": starts_at_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]
    client.post(f"/appointments/{appointment_id}/confirm")

    appointment_date = starts_at_dt.date().isoformat()
    response = client.get(f"/dashboard?date_from={appointment_date}&date_to={appointment_date}")
    assert response.status_code == 200
    body = response.json()
    assert body["turnos"]["total_en_periodo"] == 1
    assert body["turnos"]["por_estado"]["confirmed"] == 1
    assert body["turnos"]["por_estado"]["pending"] == 0
    if starts_at_dt.date() == datetime.now(timezone.utc).date():
        assert body["turnos"]["hoy"] == 1


def test_dashboard_excludes_appointments_outside_the_range(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })

    date_from, date_to = _today_range()
    response = client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    assert response.json()["turnos"]["total_en_periodo"] == 0
    # Still counts for "hoy" only if it's actually today -- 2099 is not.
    assert response.json()["turnos"]["hoy"] == 0


def test_dashboard_counts_active_patients_and_new_in_period(admin_client: TestClient):
    client = admin_client
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    client.post("/patients", json={"id": "patient-2", "name": "Beto", "active": False})

    date_from, date_to = _today_range()
    response = client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    body = response.json()
    assert body["pacientes"]["total_activos"] == 1  # Beto esta inactivo
    assert body["pacientes"]["nuevos_en_periodo"] == 2  # ambos se dieron de alta hoy


def test_dashboard_counts_reminders_sent_in_period(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    starts_at = (datetime.now(timezone.utc) + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S")
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": starts_at,
    })
    dispatched = client.post("/reminders/dispatch")
    assert dispatched.status_code == 200
    assert len(dispatched.json()) == 2  # politicas 24h y 2h, ambas vencidas

    date_from, date_to = _today_range()
    response = client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.status_code == 200
    assert response.json()["recordatorios_enviados_en_periodo"] == 2


def test_dashboard_counts_pending_deposits(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    created = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2099-01-01T10:00:00",
    })
    appointment_id = created.json()["id"]
    deposit = client.post(f"/appointments/{appointment_id}/deposit", json={"amount": "500.00"})
    deposit_id = deposit.json()["id"]

    date_from, date_to = _today_range()
    response = client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.json()["senas_pendientes"] == 1

    client.post(f"/deposits/{deposit_id}/mark-paid", json={"medio_pago": "efectivo"})
    response = client.get(f"/dashboard?date_from={date_from}&date_to={date_to}")
    assert response.json()["senas_pendientes"] == 0


def test_dashboard_requires_admin(staff_client: TestClient):
    date_from, date_to = _today_range()
    assert staff_client.get(f"/dashboard?date_from={date_from}&date_to={date_to}").status_code == 403
