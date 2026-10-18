"""El consultorio, con dos pedidos a la vez.

🔴 **El defecto que cierra este archivo** (cola autónoma 2026-10-17, ítem 2).
Hasta acá el choque de sala lo chequeaba `AppointmentService` **antes** de
llamar al motor: leía los turnos, veía el consultorio libre y recién después
`reserve()` abría su transacción. Entre una cosa y la otra cabía el pedido del
otro profesional: los dos veían la sala libre, los dos reservaban su turno (cada
uno sobre su propia fila de recurso, sin cruzarse), y la Dra. Vidal y el Dr.
Molina terminaban en el Consultorio 1 a las 10. Los tests de `test_agenda_blocks`
corren de a un pedido por vez y no lo ven nunca.

**Cómo se hace determinista** sin dormir y cruzar los dedos: el repositorio de
turnos se envuelve con un punto de encuentro de dos hilos, en los dos lugares
donde el servicio puede estar "entre leer y escribir":

- `list()`: lo que hacía el chequeo viejo de la sala, afuera de la transacción;
- el validador de `reserve()`/`relocate()`: adentro de la transacción del motor.

Con el chequeo afuera, los dos hilos se encuentran en `list()` habiendo leído
ambos la sala libre, y los dos escriben. Con la sala como recurso del motor, el
chequeo vive en la transacción: el segundo hilo se queda esperando el candado de
la fila de la sala mientras el primero está en su validador, el encuentro se
vence por tiempo y el primero termina de escribir; el segundo entra recién
después y **sí lo ve**. El tope es de falla, no una espera esperada.

Sólo corre contra PostgreSQL (la suite entera lo exige): en SQLite no hay
candados de fila y esto no diría nada.
"""
import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.services.appointments import ConsultorioOcupado

LUNES = "2026-07-20"

#: Cuánto espera un hilo a que el otro llegue al punto de encuentro. Con el
#: candado puesto el otro nunca llega (está bloqueado), así que es lo que dura
#: el test; sin candado llegan los dos y no se espera nada.
ENCUENTRO = 1.5


class _Encuentro:
    """Dos hilos se esperan; si el otro no viene, sigue igual."""

    def __init__(self) -> None:
        self._barrera = threading.Barrier(2)

    def esperar(self) -> None:
        try:
            self._barrera.wait(ENCUENTRO)
        except threading.BrokenBarrierError:
            pass


class _TurnosConEncuentro:
    """El repositorio de turnos del servicio, con un encuentro en cada punto
    donde se puede estar entre leer el estado y escribir sobre él."""

    def __init__(self, base, encuentro: _Encuentro) -> None:
        self._base = base
        self._encuentro = encuentro

    def list(self):
        turnos = self._base.list()
        self._encuentro.esperar()
        return turnos

    def reserve(self, appointment, validator):
        def validar(existentes):
            validado = validator(existentes)
            self._encuentro.esperar()
            return validado
        return self._base.reserve(appointment, validar)

    def relocate(self, appointment, validator):
        def validar(existentes):
            validado = validator(existentes)
            self._encuentro.esperar()
            return validado
        return self._base.relocate(appointment, validar)

    def __getattr__(self, nombre):
        return getattr(self._base, nombre)


@pytest.fixture
def servicio(admin_client: TestClient):
    client = admin_client
    client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Buenos_Aires",
    })
    client.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })
    for id_, nombre in (("dr-molina", "Dr. Molina"), ("dra-vidal", "Dra. Vidal")):
        client.post("/resources", json={"id": id_, "name": nombre, "branch_id": "sede-1"})
        creado = client.post("/agenda-blocks", json={
            "resource_id": id_, "consultorio_id": "cons-1",
            "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
            "valid_from": "2026-07-01", "valid_to": None,
            "slot_minutes": 20, "modality": "turnos",
        })
        assert creado.status_code == 201, creado.text
    client.post("/services", json={"id": "consulta", "name": "Consulta", "duration_minutes": 30})
    for id_ in ("p-1", "p-2"):
        client.post("/patients", json={"id": id_, "name": id_})

    servicio = client.app.state.appointment_service
    encuentro = _Encuentro()
    servicio.appointments = _TurnosConEncuentro(servicio.appointments, encuentro)
    return servicio


def _a_la_vez(*llamadas):
    """Corre cada llamada en su hilo y devuelve `(resultado, error)` de cada una."""
    salidas: list[tuple] = [(None, None)] * len(llamadas)

    def correr(indice, llamada):
        try:
            salidas[indice] = (llamada(), None)
        except BaseException as exc:  # noqa: BLE001 - se reporta tal cual
            salidas[indice] = (None, exc)

    hilos = [threading.Thread(target=correr, args=(i, f)) for i, f in enumerate(llamadas)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert not any(hilo.is_alive() for hilo in hilos), "un hilo quedó colgado"
    return salidas


def _ocupan(servicio, hora_utc: int) -> list[str]:
    """Los turnos vivos que arrancan a esa hora UTC, sea cual sea el profesional."""
    return sorted(
        t.id for t in servicio.appointments.list()
        if t.status.value not in {"cancelled", "no_show"} and t.starts_at.astimezone(UTC).hour == hora_utc
    )


def test_dos_altas_a_la_vez_en_el_mismo_consultorio_no_entran_las_dos(servicio):
    """🔴 Dos profesionales, un consultorio, la misma hora, a la vez."""
    salidas = _a_la_vez(
        lambda: servicio.create("dr-molina", "consulta", "p-1", datetime(2026, 7, 20, 10, 0)),
        lambda: servicio.create("dra-vidal", "consulta", "p-2", datetime(2026, 7, 20, 10, 0)),
    )

    errores = [error for _, error in salidas if error is not None]
    assert len(errores) == 1, f"entraron los dos al mismo consultorio: {salidas}"
    assert isinstance(errores[0], ConsultorioOcupado), errores[0]
    # 10:00 en Buenos Aires son las 13:00 UTC: es lo que quedó guardado.
    assert len(_ocupan(servicio, 13)) == 1


def test_dos_reagendados_a_la_vez_al_mismo_consultorio_no_entran_los_dos(servicio):
    """🔴 El camino espejo: mover dos turnos al mismo rato de la misma sala."""
    molina = servicio.create("dr-molina", "consulta", "p-1", datetime(2026, 7, 20, 9, 0))
    vidal = servicio.create("dra-vidal", "consulta", "p-2", datetime(2026, 7, 20, 11, 0))

    salidas = _a_la_vez(
        lambda: servicio.reschedule(molina.id, datetime(2026, 7, 20, 10, 0)),
        lambda: servicio.reschedule(vidal.id, datetime(2026, 7, 20, 10, 0)),
    )

    errores = [error for _, error in salidas if error is not None]
    assert len(errores) == 1, f"entraron los dos al mismo consultorio: {salidas}"
    assert isinstance(errores[0], ConsultorioOcupado), errores[0]
    assert len(_ocupan(servicio, 13)) == 1


def test_a_la_vez_pero_en_consultorios_distintos_entran_los_dos(admin_client: TestClient):
    """🔴 El control: el candado de la sala no puede volverse un candado global."""
    client = admin_client
    client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Buenos_Aires",
    })
    for sala in ("cons-1", "cons-2"):
        client.post("/consultorios", json={"id": sala, "name": sala, "branch_id": "sede-1"})
    for id_, sala in (("dr-molina", "cons-1"), ("dra-vidal", "cons-2")):
        client.post("/resources", json={"id": id_, "name": id_, "branch_id": "sede-1"})
        assert client.post("/agenda-blocks", json={
            "resource_id": id_, "consultorio_id": sala,
            "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
            "valid_from": "2026-07-01", "valid_to": None,
            "slot_minutes": 20, "modality": "turnos",
        }).status_code == 201
    client.post("/services", json={"id": "consulta", "name": "Consulta", "duration_minutes": 30})
    for id_ in ("p-1", "p-2"):
        client.post("/patients", json={"id": id_, "name": id_})
    servicio = client.app.state.appointment_service
    servicio.appointments = _TurnosConEncuentro(servicio.appointments, _Encuentro())

    salidas = _a_la_vez(
        lambda: servicio.create("dr-molina", "consulta", "p-1", datetime(2026, 7, 20, 10, 0)),
        lambda: servicio.create("dra-vidal", "consulta", "p-2", datetime(2026, 7, 20, 10, 0)),
    )

    assert [error for _, error in salidas if error is not None] == [], salidas
    assert len(_ocupan(servicio, 13)) == 2
