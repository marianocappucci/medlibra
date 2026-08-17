from datetime import datetime, time, timedelta, timezone

from fastapi.testclient import TestClient
from libragenda import ReminderPolicy

# 🔴 Los horarios de los turnos de este archivo NO salen del reloj.
#
# La disponibilidad se declara por dia de semana y su `ends_at` es un `time`,
# asi que lo mas tarde que puede terminar es 23:59 y `Availability.contains`
# exige ademas que el turno empiece y termine el MISMO dia. Un turno que cruza
# la medianoche es irrepresentable: el alta lo rechaza con 409 "no atiende en
# ese horario", por mas que la disponibilidad diga 00:00-23:59 los siete dias.
#
# Cualquier horario calculado como "ahora + N minutos" cae en ese agujero en
# una franja de media hora del dia y pasa el resto del tiempo. Este archivo se
# rompio asi tres veces (2026-07-28, 2026-08-11 y 2026-08-16) y las tres se
# parcheo corriendo el calculo, que mueve la franja en vez de sacarla. Ahora la
# hora de cada turno es FIJA y la corrida es la misma a las 03:00 que a las
# 22:00.
#
# Un turno **futuro** en una fecha fija, para lo que necesita un turno por
# venir. 2099-01-01 es jueves; el arnes abre los siete dias, asi que el dia de
# semana da igual.
TURNO_FUTURO = "2099-01-01T10:00:00"
#: Hora del dia (UTC) de los turnos que tienen que caer HOY. Al mediodia no hay
#: medianoche cerca por ningun lado.
HORA_DEL_TURNO_DE_HOY = time(12, 0)


def _turno_de_hoy() -> datetime:
    """Hoy al mediodia UTC. La FECHA sale del reloj -- no hay otra forma de
    pedir "hoy" -- pero la HORA no, que es de donde venia el problema."""
    return datetime.combine(
        datetime.now(timezone.utc).date(), HORA_DEL_TURNO_DE_HOY, tzinfo=timezone.utc
    )


def _politicas_ya_vencidas(client: TestClient) -> None:
    """Deja el dispatcher con dos politicas vencidas para `TURNO_FUTURO`.

    Las del producto son 24h y 2h antes del turno (`app/notifications.py`), o
    sea que para que disparen las dos el turno tiene que caer dentro de las dos
    horas siguientes a "ahora" -- y ES ESA regla la que ataba el horario del
    turno al reloj de la corrida, porque en la franja previa a la medianoche no
    queda ningun hueco valido dentro de esas dos horas.
    Lo que mide el test de abajo es el CONTADOR del dashboard, no los plazos:
    con el turno en una fecha fija, las politicas se declaran con un anticipo
    largo. Los plazos reales (`24h`/`2h`, por nombre) los aserta
    `tests/test_reminders.py`, que es donde corresponde.
    """
    client.app.state.reminder_dispatcher.policies = [
        # ~110 y ~137 anios de anticipo: con el turno en 2099 las dos ya
        # vencieron para cualquier "ahora" real.
        ReminderPolicy("primera", timedelta(days=40_000)),
        ReminderPolicy("segunda", timedelta(days=50_000)),
    ]


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
    # El turno va HOY al mediodia: tiene que contarlo `turnos.hoy`, y el alta
    # no mira el reloj (no hay regla de "no agendar en el pasado"), asi que
    # sirve igual si la corrida es a las 03:00 o a las 22:00.
    client = _seeded_client(admin_client)
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})

    starts_at_dt = _turno_de_hoy()
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
    alta = client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    assert alta.status_code < 300, alta.text
    _politicas_ya_vencidas(client)
    # 🔴 La creacion se aserta. Sin esto, un turno que no se crea -- por lo que
    # sea: validacion, solapamiento, horario del recurso -- aparece como
    # `assert 0 == 2` en el dispatch, que es un sintoma que no nombra la causa.
    # Paso en CI el 2026-08-11 en este mismo test de los DOS productos, y el
    # rojo no alcanzo para diagnosticar nada.
    turno = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": TURNO_FUTURO,
    })
    assert turno.status_code < 300, f"el turno no se creo ({turno.status_code}): {turno.text}"

    # El `sent_at` del ledger es el reloj del servidor, asi que el rango se
    # abre ANTES del dispatch y se cierra DESPUES: si la corrida cruza la
    # medianoche justo en el medio, el rango la cubre igual. Con un unico
    # `hoy` calculado despues, ese caso daria 0 recordatorios en el periodo.
    dia_antes = datetime.now(timezone.utc).date().isoformat()
    dispatched = client.post("/reminders/dispatch")
    assert dispatched.status_code == 200
    assert len(dispatched.json()) == 2  # las dos politicas de arriba, ya vencidas
    dia_despues = datetime.now(timezone.utc).date().isoformat()

    response = client.get(f"/dashboard?date_from={dia_antes}&date_to={dia_despues}")
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
