"""Las rutas de la costura con LibraView no frenan el loop de uvicorn (ADR-051).

Es la misma medición que `test_rutas_no_bloquean_el_loop.py` (ver ahí el porqué): una llamada de la ruta se reemplaza por una que
duerme con `time.sleep` y, mientras duerme, se pide `/health` por el mismo loop. Acá hay dos cosas lentas: la base (sincrónica) y el
HTTP a LibraView, que va ADENTRO de una corrutina que la ruta corre con `asyncio.run` en su hilo. Si alguien pasa la ruta a `async def`
esa corrutina vuelve al loop de uvicorn, y estos tests se ponen rojos.
"""
# ruff: noqa: F811 -- las fixtures de `test_libraview` se importan y se piden por nombre, como en `tests/nodo_apoyo.py`.
import json
import time

import httpx
from conftest import https_client  # noqa: F401 — mismo host con punto que el resto de la suite
from test_libraview import (  # noqa: F401 — las fixtures se piden por nombre
    LibraViewFalso,
    _avisar,
    _datos,
    _enviar,
    _evento,
    _firma,
    _pedido,
    consultorio,
    enviado,
    lv,
)
from test_rutas_no_bloquean_el_loop import _Lento, _mientras_duerme, _no_bloqueo

from app.services import libraview


def _con_http_lento(lv: LibraViewFalso, lento: _Lento, monkeypatch) -> None:
    """Cada llamada a LibraView tarda `LENTO` segundos bloqueando el hilo, como una red lenta no lo haría pero un handler sí."""
    original = lv.handler

    def lento_handler(request: httpx.Request) -> httpx.Response:
        lento.dormir()
        return original(request)

    monkeypatch.setattr(
        libraview, "_nuevo_cliente",
        lambda timeout=libraview.TIMEOUT_SEGUNDOS: httpx.AsyncClient(transport=httpx.MockTransport(lento_handler), timeout=timeout),
    )


def test_mandar_el_pedido_no_frena_el_loop(consultorio, lv, monkeypatch):
    pedido = _pedido(consultorio)
    lento = _Lento()
    _con_http_lento(lv, lento, monkeypatch)
    respuesta, health, fin = _mientras_duerme(consultorio, lento, lambda c: c.post(
        f"/patients/p-1/study-orders/{pedido['id']}/libraview", json=_datos(pedido)))
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["estado"] == "enviado"
    _no_bloqueo(lento, health, fin)


def test_reintentar_no_frena_el_loop(consultorio, lv, monkeypatch):
    lv.forzar_orden = (503, {"detail": "caído"})
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).json()["estado"] == "error"
    lv.forzar_orden = None
    lento = _Lento()
    _con_http_lento(lv, lento, monkeypatch)
    respuesta, health, fin = _mientras_duerme(consultorio, lento, lambda c: c.post(
        f"/patients/p-1/study-orders/{pedido['id']}/libraview/reintentar"))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "enviado"
    _no_bloqueo(lento, health, fin)


def test_el_catalogo_no_frena_el_loop(consultorio, lv, monkeypatch):
    lento = _Lento()
    _con_http_lento(lv, lento, monkeypatch)
    respuesta, health, fin = _mientras_duerme(consultorio, lento, lambda c: c.get("/integraciones/libraview/practicas"))
    assert respuesta.status_code == 200, respuesta.text
    _no_bloqueo(lento, health, fin)


def test_el_webhook_no_frena_el_loop(enviado, lv, monkeypatch):
    """Lo lento: bajar el informe y el PDF (HTTP dentro de la corrutina) y grabar (la base y el disco, sincrónicos)."""
    client, pedido, (acceso, _) = enviado
    lento = _Lento()
    _con_http_lento(lv, lento, monkeypatch)
    real = libraview.EnvioRepository.grabar_informe

    def grabar_lento(self, **k):
        time.sleep(0.2)
        return real(self, **k)

    monkeypatch.setattr(libraview.EnvioRepository, "grabar_informe", grabar_lento)
    cuerpo = json.dumps(_evento(pedido, acceso)).encode()
    respuesta, health, fin = _mientras_duerme(client, lento, lambda c: c.post(
        "/integraciones/libraview/resultados", content=cuerpo,
        headers={"X-LibraView-Firma": _firma(cuerpo, int(time.time()))}))
    assert respuesta.status_code == 200, respuesta.text
    _no_bloqueo(lento, health, fin)
