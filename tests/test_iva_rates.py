"""Alicuota de IVA configurable por servicio.

El caso que motiva todo esto es el exento: en salud es el normal, y hasta
la 0012 la facturacion lo declaraba al 21%.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.billing import _split_iva
from app.services.iva_rates import ALLOWED_RATES, InvalidIvaRate, validate_rate

from test_billing import _seeded_appointment


# --- la separacion en si -------------------------------------------------

def test_exento_manda_todo_a_subtotal_y_cero_de_iva():
    """Con alicuota 0 el total va entero al subtotal. Eso es lo que hace que
    libracore declare el comprobante en ImpOpEx -- ver el test de abajo."""
    assert _split_iva(Decimal("1000.00"), Decimal("0")) == (Decimal("1000.00"), Decimal("0"))


def test_veintiuno_separa_como_antes():
    subtotal, iva = _split_iva(Decimal("1210.00"), Decimal("0.21"))
    assert (subtotal, iva) == (Decimal("1000.00"), Decimal("210.00"))
    assert subtotal + iva == Decimal("1210.00")


def test_diez_y_medio():
    subtotal, iva = _split_iva(Decimal("1105.00"), Decimal("0.105"))
    assert (subtotal, iva) == (Decimal("1000.00"), Decimal("105.00"))
    assert subtotal + iva == Decimal("1105.00")


def test_el_default_sigue_siendo_veintiuno():
    """Sin alicuota explicita se comporta igual que antes de la 0012 -- la
    migracion no le cambia la facturacion a nadie."""
    assert _split_iva(Decimal("1210.00")) == (Decimal("1000.00"), Decimal("210.00"))


@pytest.mark.parametrize("rate", [Decimal("0.13"), Decimal("0.05"), Decimal("1")])
def test_alicuota_que_arca_no_mapea_es_rechazada(rate):
    """`_iva_id()` de libracore cae silenciosamente a 21% ante un porcentaje
    desconocido, asi que una alicuota invalida no fallaria: se declararia
    mal. Por eso se valida antes."""
    with pytest.raises(InvalidIvaRate):
        validate_rate(rate)


@pytest.mark.parametrize("rate", ALLOWED_RATES)
def test_las_permitidas_pasan(rate):
    assert validate_rate(rate) == rate


def test_el_mensaje_de_rechazo_lista_las_alicuotas_legibles():
    """El 422 lo lee una persona. `:g` sobre Decimal dejaba "10.500%" y
    "27." -- encontrado al ejercitarlo contra dev, no por los tests."""
    with pytest.raises(InvalidIvaRate) as exc:
        validate_rate(Decimal("0.13"))
    assert "0%, 10.5%, 21%, 27%" in str(exc.value)


# --- el contrato con ARCA ------------------------------------------------

def _xml_enviado_a_arca(total: str, rate: Decimal) -> str:
    """Corre el `solicitar_cae` real de libracore con el transporte SOAP
    interceptado, y devuelve el XML que habria salido. Es la unica forma de
    responder por lo que ARCA recibe sin asumirlo del mapa de alicuotas."""
    import asyncio
    import xml.etree.ElementTree as ET

    from libracore import arca_wsfe

    capturado = {}

    async def _fake_soap(url, action, body):
        capturado["body"] = body
        return ET.fromstring(
            "<r><FECAEDetResponse><Resultado>A</Resultado>"
            "<CAE>70000000000001</CAE><CAEFchVto>20260901</CAEFchVto>"
            "</FECAEDetResponse></r>"
        )

    original, arca_wsfe._soap = arca_wsfe._soap, _fake_soap
    try:
        subtotal, iva = _split_iva(Decimal(total), rate)
        factura = {
            "fecha": "2026-08-02", "concepto": 1, "tipo": 6, "punto_venta": 1,
            "numero": 1, "cliente_cuit": "", "subtotal": float(subtotal),
            "iva_amount": float(iva), "total": float(Decimal(total)),
        }
        resultado = asyncio.run(
            arca_wsfe.solicitar_cae(factura, "20111222339", "tok", "sig", "homologacion")
        )
        assert resultado["cae"] == "70000000000001", "control: se ejercito el camino real"
    finally:
        arca_wsfe._soap = original
    return capturado["body"]


def test_un_exento_viaja_a_arca_como_operacion_exenta():
    """El test que justifica la feature. Una prestacion exenta tiene que
    salir con el importe en ImpOpEx, ImpNeto en 0 y **sin** bloque
    <AlicIva>. Se inspecciona el XML que libracore genera de verdad."""
    xml = _xml_enviado_a_arca("1000.00", Decimal("0"))
    assert "<ImpOpEx>1000.00</ImpOpEx>" in xml
    assert "<ImpNeto>0.00</ImpNeto>" in xml
    assert "<ImpIVA>0.00</ImpIVA>" in xml
    assert "<AlicIva>" not in xml, "un exento no lleva alicuota declarada"
    assert "<ImpTotal>1000.00</ImpTotal>" in xml


def test_el_veintiuno_sigue_viajando_como_gravado():
    """La contracara: sin esta comprobacion, un bug que mandara todo a
    ImpOpEx tambien pasaria el test de arriba."""
    xml = _xml_enviado_a_arca("1210.00", Decimal("0.21"))
    assert "<ImpNeto>1000.00</ImpNeto>" in xml
    assert "<ImpIVA>210.00</ImpIVA>" in xml
    assert "<ImpOpEx>0.00</ImpOpEx>" in xml
    assert "<AlicIva><Id>5</Id>" in xml, "21% es el Id 5 de ARCA"


def test_el_diez_y_medio_se_declara_con_su_propio_id():
    xml = _xml_enviado_a_arca("1105.00", Decimal("0.105"))
    assert "<AlicIva><Id>4</Id>" in xml, "10,5% es el Id 4 de ARCA"
    assert "<ImpNeto>1000.00</ImpNeto>" in xml
    assert "<ImpIVA>105.00</ImpIVA>" in xml


# --- los endpoints -------------------------------------------------------

def test_servicio_sin_alicuota_propia_hereda_la_de_la_instancia(admin_client: TestClient):
    admin_client.post("/services", json={"id": "s1", "name": "Consulta", "duration_minutes": 30})
    response = admin_client.get("/services/s1/iva")
    assert response.status_code == 200
    body = response.json()
    assert body["inherited"] is True
    assert Decimal(body["rate"]) == Decimal("0.21")


def test_set_get_y_borrado_de_la_alicuota_propia(admin_client: TestClient):
    admin_client.post("/services", json={"id": "s1", "name": "Consulta", "duration_minutes": 30})

    put = admin_client.put("/services/s1/iva", json={"rate": "0"})
    assert put.status_code == 200
    assert put.json()["inherited"] is False
    assert Decimal(put.json()["rate"]) == Decimal("0")

    got = admin_client.get("/services/s1/iva")
    assert got.json()["inherited"] is False
    assert Decimal(got.json()["rate"]) == Decimal("0")

    assert admin_client.delete("/services/s1/iva").status_code == 204
    assert admin_client.get("/services/s1/iva").json()["inherited"] is True


def test_borrar_una_alicuota_que_no_existe_es_404(admin_client: TestClient):
    admin_client.post("/services", json={"id": "s1", "name": "Consulta", "duration_minutes": 30})
    assert admin_client.delete("/services/s1/iva").status_code == 404


def test_endpoint_rechaza_alicuota_invalida(admin_client: TestClient):
    admin_client.post("/services", json={"id": "s1", "name": "Consulta", "duration_minutes": 30})
    response = admin_client.put("/services/s1/iva", json={"rate": "0.13"})
    assert response.status_code == 422
    assert "no permitida" in response.json()["detail"]


def test_default_de_la_instancia_es_configurable(admin_client: TestClient):
    response = admin_client.put("/business", json={
        "business_name": "Consultorio", "currency": "ARS", "default_iva_rate": "0",
    })
    assert response.status_code == 200
    assert Decimal(response.json()["default_iva_rate"]) == Decimal("0")

    admin_client.post("/services", json={"id": "s1", "name": "Consulta", "duration_minutes": 30})
    heredada = admin_client.get("/services/s1/iva").json()
    assert heredada["inherited"] is True
    assert Decimal(heredada["rate"]) == Decimal("0")


def test_un_put_sin_alicuota_no_le_mueve_la_alicuota_al_consultorio(admin_client: TestClient):
    """Regresion: `default_iva_rate` es opcional, y omitirla tiene que dejar
    la que estaba -- no volver al 21% del modulo."""
    admin_client.put("/business", json={
        "business_name": "Consultorio", "currency": "ARS", "default_iva_rate": "0",
    })
    response = admin_client.put("/business", json={
        "business_name": "Consultorio Renombrado", "currency": "ARS",
    })
    assert response.status_code == 200
    assert Decimal(response.json()["default_iva_rate"]) == Decimal("0")


def test_default_invalido_es_rechazado(admin_client: TestClient):
    response = admin_client.put("/business", json={
        "business_name": "C", "currency": "ARS", "default_iva_rate": "0.13",
    })
    assert response.status_code == 422


# --- de punta a punta ----------------------------------------------------

def test_turno_de_prestacion_exenta_factura_sin_iva(admin_client: TestClient):
    """El caso real completo: consulta medica exenta, facturada al
    completar el turno. La factura tiene que salir con IVA 0 y el total
    entero como subtotal."""
    appointment_id = _seeded_appointment(admin_client, price="1000.00")
    assert admin_client.put("/services/service-1/iva", json={"rate": "0"}).status_code == 200

    response = admin_client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert response.status_code == 200, response.text
    factura = response.json()["factura"]
    assert factura is not None
    assert Decimal(str(factura["iva_amount"])) == Decimal("0")
    assert Decimal(str(factura["subtotal"])) == Decimal("1000.00")
    assert Decimal(str(factura["total"])) == Decimal("1000.00")


def test_turno_sin_alicuota_configurada_factura_al_veintiuno_como_antes(admin_client: TestClient):
    """Linea de base: sin tocar nada, la facturacion se comporta igual que
    antes de esta feature."""
    appointment_id = _seeded_appointment(admin_client, price="1210.00")
    response = admin_client.post(
        f"/appointments/{appointment_id}/complete", json={"medio_pago": "efectivo"},
    )
    assert response.status_code == 200, response.text
    factura = response.json()["factura"]
    assert Decimal(str(factura["subtotal"])) == Decimal("1000.00")
    assert Decimal(str(factura["iva_amount"])) == Decimal("210.00")
