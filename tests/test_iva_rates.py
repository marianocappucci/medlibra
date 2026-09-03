"""Alícuota de IVA configurable por servicio.

El caso que motiva la feature es el exento: en salud es el normal, y hasta la
migración 0012 la facturación lo declaraba al 21%.

🔴 **Lo que este archivo dejó de probar el 2026-08-24.** La mitad de estos tests
medía `_split_iva` y el XML que salía a ARCA — el contrato del motor de
facturación local, que se fue con ADR-036. Ese contrato ahora es de Contalibra y
tiene su propia suite allá; sostenerlo acá sería probar código que este producto
ya no tiene.

Lo que queda vivo es **la configuración** (qué alícuota le corresponde a cada
prestación) y **que esa alícuota llegue a Contalibra**, que es quien la usa. Sin
eso último la feature entera quedaría configurable y sin efecto: una prestación
exenta se facturaría al 21% del otro lado, **en silencio**. Ese test está en
`test_envio_a_contalibra.py`.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services.iva_rates import ALLOWED_RATES, InvalidIvaRate, validate_rate

# --- que alicuota se acepta ----------------------------------------------

@pytest.mark.parametrize("rate", [Decimal("0.13"), Decimal("0.05"), Decimal("1")])
def test_alicuota_que_arca_no_mapea_es_rechazada(rate):
    """ de libracore cae silenciosamente a 21% ante un porcentaje
    desconocido, asi que una alicuota invalida no fallaria: se declararia
    mal. Por eso se valida antes."""
    with pytest.raises(InvalidIvaRate):
        validate_rate(rate)


@pytest.mark.parametrize("rate", ALLOWED_RATES)
def test_las_permitidas_pasan(rate):
    assert validate_rate(rate) == rate


def test_el_mensaje_de_rechazo_lista_las_alicuotas_legibles():
    """El 422 lo lee una persona.  sobre Decimal dejaba "10.500%" y
    "27." -- encontrado al ejercitarlo contra dev, no por los tests."""
    with pytest.raises(InvalidIvaRate) as exc:
        validate_rate(Decimal("0.13"))
    assert "0%, 10.5%, 21%, 27%" in str(exc.value)


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


