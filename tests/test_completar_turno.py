"""Completar un turno: el medio de pago, la seña y la transición.

🔴 **Estos tests venían de `test_billing.py`, que se borró con el motor de
facturación local (ADR-036).** Lo que medían no se fue con el motor: la
validación del medio de pago, la seña que descuenta del saldo y que un turno no
se pueda completar dos veces siguen viviendo en `complete_appointment`, y
borrarlos junto al archivo habría dejado ese comportamiento sin una sola
aserción encima.

Los que sí se fueron con el motor son los del comprobante —tipo A contra tipo B
según la condición del paciente, el CAE— porque acá ya no hay comprobante que
emitir. Ese contrato ahora es de [[contalibra]].

La validación del medio de pago corre **antes** de completar el turno, y el
orden importa: `COMPLETED` no admite otra transición, así que si corriera después
un turno con el pedido mal armado quedaría completado, sin cobrar y sin forma de
reintentar.
"""
import pytest
from fastapi.testclient import TestClient


def _turno(
    client: TestClient, patient: dict | None = None, price: str | None = "1000.00",
) -> str:
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={
        "id": "resource-1", "name": "Dra. Vidal", "branch_id": "branch-1",
    })
    client.post("/services", json={
        "id": "service-1", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json=patient or {"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    if price is not None:
        client.put("/services/service-1/prices", json={
            "branch_id": "branch-1", "price": price,
        })
    creado = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": (patient or {}).get("id", "patient-1"),
        "starts_at": "2099-01-01T10:00:00",
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    assert client.post(f"/appointments/{turno}/confirm").status_code == 200
    return turno


def _senar(client: TestClient, turno: str, monto: str, medio: str) -> None:
    sena = client.post(f"/appointments/{turno}/deposit", json={"amount": monto})
    assert sena.status_code in (200, 201), sena.text
    pagada = client.post(
        f"/deposits/{sena.json()['id']}/mark-paid", json={"medio_pago": medio},
    )
    assert pagada.status_code == 200, pagada.text


# ── El medio de pago ───────────────────────────────────────────────────────

def test_sin_precio_configurado_no_hace_falta_medio_de_pago(admin_client: TestClient):
    """Un turno sin precio se completa y no cobra nada. Es el caso de las
    prestaciones que el consultorio no factura."""
    turno = _turno(admin_client, price=None)
    respuesta = admin_client.post(f"/appointments/{turno}/complete")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "completed"
    assert respuesta.json()["contalibra"] is None


def test_con_precio_y_sin_sena_el_medio_de_pago_es_obligatorio(admin_client: TestClient):
    turno = _turno(admin_client)
    assert admin_client.post(f"/appointments/{turno}/complete").status_code == 422


def test_una_sena_que_cubre_todo_el_precio_no_pide_medio_de_pago(
    admin_client: TestClient,
):
    """🔴 El control del de arriba: sin esto, "pedir siempre medio_pago" pasaría
    aquel test — y el mostrador tendría que inventar un medio de pago para un
    turno que ya está cobrado entero."""
    turno = _turno(admin_client)
    _senar(admin_client, turno, "1000.00", "transferencia")
    assert admin_client.post(f"/appointments/{turno}/complete").status_code == 200


def test_una_sena_parcial_sigue_pidiendo_el_medio_de_pago_del_saldo(
    admin_client: TestClient,
):
    turno = _turno(admin_client)
    _senar(admin_client, turno, "400.00", "mercadopago")

    sin_medio = admin_client.post(f"/appointments/{turno}/complete")
    assert sin_medio.status_code == 422
    assert "600" in sin_medio.json()["detail"], "el mensaje dice cuánto falta"

    con_medio = admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )
    assert con_medio.status_code == 200


# ── La transición ──────────────────────────────────────────────────────────

def test_completar_dos_veces_se_rechaza(admin_client: TestClient):
    """`COMPLETED` no admite otra transición. Antes esto también protegía de
    facturar dos veces; hoy protege de **mandar dos veces** — aunque Contalibra
    sea idempotente por `(sistema, referencia)`, no se apoya en eso."""
    turno = _turno(admin_client)
    primera = admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )
    assert primera.status_code == 200

    segunda = admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )
    assert segunda.status_code == 409


# ── Lo que viaja cuando hubo seña ──────────────────────────────────────────

@pytest.fixture
def enviados(monkeypatch):
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    capturados = []

    async def falso(**kwargs):
        capturados.append(kwargs)
        return {"venta": {"id": 1}, "factura": None, "ya_existia": False}

    from app.services import contalibra

    monkeypatch.setattr(contalibra, "enviar_consulta", falso)
    return capturados


def _pagos(capturado: dict) -> dict:
    """`{medio: monto}` de lo que viajó."""
    return {p["medio"]: float(p["monto"]) for p in capturado["pagos"]}


def test_con_sena_parcial_viajan_DOS_pagos_con_su_medio_cada_uno(
    admin_client: TestClient, enviados,
):
    """🔴 **La seña y el saldo son dos cobros distintos.**

    Hasta el 2026-08-24 acá viajaba el precio entero con un solo medio —el del
    saldo—, así que con 400 de seña por MercadoPago y 600 en efectivo, en
    Contalibra entraban **1000 en efectivo**. La venta cerraba por el total
    correcto —la plata bien contada— y **el reparto de la caja quedaba mal**: el
    cierre no cuadra contra el arqueo y la diferencia no tiene de dónde salir.

    El motor de facturación local que se borró (ADR-036) sí repartía. Esto lo
    devuelve.

    Este test **estaba escrito al revés**: asertaba el defecto tal cual era, con
    una nota de que el día que se tocara se pondría rojo y obligaría a decidir.
    Es exactamente lo que pasó.
    """
    turno = _turno(admin_client)
    _senar(admin_client, turno, "400.00", "mercadopago")
    admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )

    assert len(enviados) == 1
    assert float(enviados[0]["importe"]) == 1000.0
    assert _pagos(enviados[0]) == {"mercadopago": 400.0, "efectivo": 600.0}


def test_sin_sena_viaja_un_solo_pago_por_el_total(
    admin_client: TestClient, enviados,
):
    """🔴 El control. Sin esto, "mandar siempre dos pagos" pasaría el test de
    arriba — y una consulta sin seña viajaría con un pago fantasma de cero, que
    del otro lado es un movimiento de caja vacío."""
    turno = _turno(admin_client)
    admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "transferencia"},
    )
    assert _pagos(enviados[0]) == {"transferencia": 1000.0}


def test_una_sena_que_cubre_todo_no_manda_un_saldo_en_cero(
    admin_client: TestClient, enviados,
):
    """🔴 El otro control. Un pago de 0 crearía un movimiento de caja vacío en
    la contabilidad de allá, y Contalibra lo rechaza (`monto: float = Field(gt=0)`)
    — así que además de sucio, tumbaría el envío entero."""
    turno = _turno(admin_client)
    _senar(admin_client, turno, "1000.00", "transferencia")
    admin_client.post(f"/appointments/{turno}/complete")

    assert _pagos(enviados[0]) == {"transferencia": 1000.0}
    assert len(enviados[0]["pagos"]) == 1


def test_los_pagos_suman_el_importe(admin_client: TestClient, enviados):
    """🔴 Contalibra **rechaza con 422** un pedido cuyos pagos no sumen el
    importe: una venta que se marca cobrada tiene que estar cobrada entera. Acá
    cierran por construcción —el saldo es `importe - seña`, no un número
    aparte—, y este test lo deja fijado."""
    turno = _turno(admin_client)
    _senar(admin_client, turno, "333.33", "mercadopago")
    admin_client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )
    enviado = enviados[0]
    assert sum(float(p["monto"]) for p in enviado["pagos"]) == float(enviado["importe"])
