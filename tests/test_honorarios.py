"""Honorarios: el valor de la consulta por profesional.

Pedido del humano (2026-08-22): *"agregar cobro de honorarios por médico,
permitiendo setear valor de la consulta por profesional"*.

🔴 **Lo que hay que probar no es el CRUD, es qué se termina cobrando.** Guardar
un número y releerlo es lo barato; lo que importa es que el honorario del
profesional **pise** al precio de lista de la sede en lo que se cobra de verdad,
y que sacarlo lo devuelva al precio de lista en vez de dejar la prestación sin
precio. Por eso el test que manda completa un turno y **mira el importe que
viaja a la contabilidad**, no la fila de la tabla.
"""
import pytest
from fastapi.testclient import TestClient

from app.services import contalibra


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
    """Dos profesionales en la misma sede, una prestación, y el precio de lista
    de la sede en 1000. Todo lo que sigue mide contra ese 1000."""
    client = admin_client
    client.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte"})
    client.post("/resources", json={
        "id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1",
    })
    client.post("/resources", json={
        "id": "dra-vidal", "name": "Dra. Vidal", "branch_id": "sede-1",
    })
    client.post("/services", json={
        "id": "consulta", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json={"id": "p-1", "name": "Ana"})
    for profesional in ["dr-molina", "dra-vidal"]:
        for weekday in range(7):
            client.post(f"/resources/{profesional}/availability", json={
                "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
            })
    client.put("/services/consulta/prices", json={
        "branch_id": "sede-1", "price": "1000.00",
    })
    return client


def _honorario(client: TestClient, profesional: str, precio: str):
    return client.put(f"/resources/{profesional}/prices", json={
        "service_id": "consulta", "price": precio,
    })


def _completar(client: TestClient, profesional: str, hora="10:00"):
    """Da un turno, lo confirma y lo completa."""
    creado = client.post("/appointments", json={
        "resource_id": profesional, "service_id": "consulta",
        "client_id": "p-1", "starts_at": f"2099-01-01T{hora}:00",
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    assert client.post(f"/appointments/{turno}/confirm").status_code == 200
    return client.post(f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"})


@pytest.fixture
def enviados(monkeypatch):
    """Lo que sale hacia Contalibra, interceptado.

    🔴 **Estos tests asertaban sobre el total de la factura local hasta el
    2026-08-24**, cuando este producto dejó de facturar (ADR-036). La propiedad
    que miden no cambió —qué importe se termina cobrando— pero el lugar donde se
    mide sí: ahora es el **importe que viaja a la contabilidad**, que es el único
    número que existe. Medirlo en la respuesta de completar sería medir un dato
    de tránsito; esto es lo que llega.
    """
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    capturados = []

    async def falso(**kwargs):
        capturados.append(kwargs)
        return {"venta": {"id": 1}}

    monkeypatch.setattr(contalibra, "enviar_consulta", falso)
    return capturados


def _cobrado(capturados) -> float:
    """El importe del último envío."""
    assert capturados, "no salió ninguna consulta hacia Contalibra"
    return float(capturados[-1]["importe"])


# ── El CRUD ────────────────────────────────────────────────────────────────

def test_honorario_crud_round_trip(consultorio: TestClient):
    client = consultorio
    puesto = _honorario(client, "dra-vidal", "2500.00")
    assert puesto.status_code == 200, puesto.text
    assert puesto.json()["resource_id"] == "dra-vidal"
    assert float(puesto.json()["price"]) == 2500.0

    listado = client.get("/resources/dra-vidal/prices").json()
    assert len(listado) == 1
    # El otro profesional no lo hereda: el honorario es de quien lo tiene.
    assert client.get("/resources/dr-molina/prices").json() == []

    # Volver a ponerlo actualiza, no duplica.
    _honorario(client, "dra-vidal", "3000.00")
    listado = client.get("/resources/dra-vidal/prices").json()
    assert len(listado) == 1
    assert float(listado[0]["price"]) == 3000.0

    assert client.delete("/resources/dra-vidal/prices/consulta").status_code == 204
    assert client.get("/resources/dra-vidal/prices").json() == []


def test_borrar_un_honorario_que_no_existe_da_404(consultorio: TestClient):
    assert consultorio.delete("/resources/dra-vidal/prices/consulta").status_code == 404


def test_un_honorario_negativo_se_rechaza(consultorio: TestClient):
    assert _honorario(consultorio, "dra-vidal", "-100.00").status_code == 422


# ── Lo que se termina cobrando ─────────────────────────────────────────────

def test_sin_honorario_se_cobra_el_precio_de_la_sede(consultorio: TestClient, enviados):
    """🔴 El control de todo lo que sigue, y el compromiso de compatibilidad:
    una instancia que no cargue ningún honorario tiene que facturar exactamente
    como antes."""
    respuesta = _completar(consultorio, "dra-vidal")
    assert respuesta.status_code == 200, respuesta.text
    assert _cobrado(enviados) == 1000.0


def test_el_honorario_del_profesional_pisa_al_precio_de_la_sede(
    consultorio: TestClient, enviados,
):
    """El caso del pedido: la consulta con la Dra. Vidal sale 2500 aunque el
    precio de lista de la sede sea 1000."""
    _honorario(consultorio, "dra-vidal", "2500.00")
    respuesta = _completar(consultorio, "dra-vidal")
    assert respuesta.status_code == 200, respuesta.text
    assert _cobrado(enviados) == 2500.0


def test_el_honorario_es_de_UN_profesional_y_no_de_todos(consultorio: TestClient, enviados):
    """🔴 El control que distingue "pisa el precio" de "cambió el precio".

    Con las dos filas cargadas y distintas: el turno de la Dra. Vidal sale 2500
    y el del Dr. Molina —que no tiene honorario propio— sigue en los 1000 de la
    sede. Con una sola fila, un bug que aplicara el honorario a todo el mundo
    pasaría el test de arriba sin problema."""
    _honorario(consultorio, "dra-vidal", "2500.00")
    _completar(consultorio, "dra-vidal", "10:00")
    assert _cobrado(enviados) == 2500.0
    _completar(consultorio, "dr-molina", "11:00")
    assert _cobrado(enviados) == 1000.0


def test_dos_profesionales_con_honorarios_distintos(consultorio: TestClient, enviados):
    """Y cada uno el suyo, que es de lo que se trata todo esto."""
    _honorario(consultorio, "dra-vidal", "2500.00")
    _honorario(consultorio, "dr-molina", "1800.00")
    _completar(consultorio, "dra-vidal", "10:00")
    assert _cobrado(enviados) == 2500.0
    _completar(consultorio, "dr-molina", "11:00")
    assert _cobrado(enviados) == 1800.0


def test_sacar_el_honorario_devuelve_al_precio_de_la_sede(consultorio: TestClient, enviados):
    """🔴 Borrar el honorario **no deja la prestación sin precio**: vuelve a
    cobrarse la de lista. Si dejara un hueco, el turno se completaría sin
    facturar y el consultorio perdería la consulta sin que nada avise."""
    client = consultorio
    _honorario(client, "dra-vidal", "2500.00")
    _completar(client, "dra-vidal", "10:00")
    assert _cobrado(enviados) == 2500.0

    client.delete("/resources/dra-vidal/prices/consulta")
    _completar(client, "dra-vidal", "11:00")
    assert _cobrado(enviados) == 1000.0


def test_con_honorario_pero_sin_precio_de_sede_igual_se_factura(
    admin_client: TestClient, enviados,
):
    """El honorario **alcanza solo**: no es un descuento sobre un precio de
    lista que tenga que existir. Un consultorio que cobra distinto por
    profesional y no maneja precio de lista es un caso normal."""
    client = admin_client
    client.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte"})
    client.post("/resources", json={
        "id": "dra-vidal", "name": "Dra. Vidal", "branch_id": "sede-1",
    })
    client.post("/services", json={
        "id": "consulta", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json={"id": "p-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/dra-vidal/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    # Sin `PUT /services/consulta/prices`: la sede no tiene precio de lista.
    _honorario(client, "dra-vidal", "2500.00")

    respuesta = _completar(client, "dra-vidal")
    assert respuesta.status_code == 200, respuesta.text
    assert _cobrado(enviados) == 2500.0
