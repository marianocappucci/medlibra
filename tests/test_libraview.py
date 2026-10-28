"""La costura con LibraView, el RIS de imágenes (ADR-050): el pedido de estudios sale como orden y el informe vuelve como resultado.

LibraView no se levanta: el HTTP lo contesta un `httpx.MockTransport` que **se comporta como el de verdad en lo que importa acá** —es
idempotente por `id_externo` (mismo contenido: `200 repetida`; otro contenido: `409`) y reparte números de acceso en el orden de las
prácticas—. Con eso los tests de reintento miden el invariante real (el reintento reenvía el MISMO cuerpo) y no un doble que dice que
sí a todo. El contrato exacto del otro lado lo prueba la suite de LibraView, contra su propia base.

🔴 **Lo que más pesa acá** es lo que no se debe romper en silencio:
- el webhook **no pide sesión** (lo llama LibraView) y por eso se prueba con un cliente sin cookie y con la SPA montada;
- un aviso que no se pudo procesar **no deja nada grabado** (ni resultado, ni documento, ni archivo en disco, ni el evento): si dejara
  el evento, el reintento de LibraView sería un «duplicado» y el informe se perdería;
- el reintento no puede convertirse en un 409.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from conftest import https_client
from fastapi.testclient import TestClient
from libracore.fechas import ZONA_AR

from app import offline
from app.services import libraview
from app.spa import montar_spa

URL = "https://libraview.example"
TOKEN = "lvi_1_secreto-de-prueba"
SECRETO = "lvw_whsec_de_prueba"
PDF = b"%PDF-1.4\n% informe ficticio\n%%EOF\n"


# ── LibraView de mentira ─────────────────────────────────────────────────────


class LibraViewFalso:
    """Contesta como LibraView en lo que MedLibra usa. Guarda cada llamada para poder afirmar sobre lo que viajó."""

    def __init__(self):
        self.llamadas: list[dict] = []
        self._ordenes: dict[str, tuple[dict, dict]] = {}
        #: Si se pone, `POST /ordenes` contesta eso sin mirar nada (`(status, json)`).
        self.forzar_orden: tuple[int, object] | None = None
        self.red_caida = False
        self.informe_status = 200
        self.informe = {
            "numero_acceso": "x", "publicado_en": "2026-10-28T12:00:00-03:00", "firmado_por": "Dra. Ficticia Ruiz",
            "texto": "Sin hallazgos patológicos.", "adendas": [],
        }
        self.pdf_status = 200
        self.pdf = PDF
        self.catalogo = [
            {"codigo": "RX-TORAX", "nombre": "Radiografía de tórax", "modalidad": "DX", "codigo_nomenclador": None, "preparacion": ""},
            {"codigo": "ECO-ABD", "nombre": "Ecografía abdominal", "modalidad": "US", "codigo_nomenclador": "430101", "preparacion": "Ayuno de 6 horas"},
        ]
        self._siguiente = 202600000050

    # lo que se ve de afuera
    def ordenes_enviadas(self) -> list[dict]:
        return [c for c in self.llamadas if c["metodo"] == "POST"]

    def rutas(self) -> list[str]:
        return [c["ruta"] for c in self.llamadas]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.llamadas.append({
            "metodo": request.method, "ruta": request.url.path, "host": request.url.host,
            "auth": request.headers.get("authorization"), "cuerpo": request.content,
        })
        if self.red_caida:
            raise httpx.ConnectError("sin red", request=request)
        ruta = request.url.path
        if request.method == "GET" and ruta == "/api/integracion/v1/practicas":
            return httpx.Response(200, json=self.catalogo)
        if request.method == "POST" and ruta == "/api/integracion/v1/ordenes":
            return self._orden(request)
        if request.method == "GET" and ruta.endswith("/informe.pdf"):
            return httpx.Response(self.pdf_status, content=self.pdf, headers={"content-type": "application/pdf"})
        if request.method == "GET" and ruta.endswith("/informe"):
            return httpx.Response(self.informe_status, json=self.informe)
        return httpx.Response(404, json={"detail": "no existe"})

    def _orden(self, request: httpx.Request) -> httpx.Response:
        if self.forzar_orden is not None:
            status, cuerpo = self.forzar_orden
            return httpx.Response(status, json=cuerpo)
        datos = json.loads(request.content)
        id_externo = datos["id_externo"]
        # Lo que LibraView compara es el contenido, no los bytes: se normaliza igual que él.
        contenido = json.loads(json.dumps(datos, sort_keys=True))
        if id_externo in self._ordenes:
            previo, respuesta = self._ordenes[id_externo]
            if previo != contenido:
                return httpx.Response(409, json={"detail": "Ya hay una orden con ese id_externo y otro contenido."})
            return httpx.Response(200, json={**respuesta, "repetida": True})
        estudios = []
        for codigo in datos["practicas"]:
            self._siguiente += 1
            estudios.append({
                "numero_acceso": str(self._siguiente), "estudio_id": self._siguiente - 202600000000,
                "practica": codigo, "estado": "solicitado",
            })
        respuesta = {"id_externo": id_externo, "orden_id": 41, "repetida": False, "estudios": estudios}
        self._ordenes[id_externo] = (contenido, respuesta)
        return httpx.Response(201, json=respuesta)


@pytest.fixture
def lv(monkeypatch) -> LibraViewFalso:
    """LibraView configurado (URL, token y secreto) y reemplazado por el doble."""
    falso = LibraViewFalso()
    monkeypatch.setenv("LIBRAVIEW_URL", URL)
    monkeypatch.setenv("LIBRAVIEW_TOKEN", TOKEN)
    monkeypatch.setenv("LIBRAVIEW_WEBHOOK_SECRET", SECRETO)

    def cliente(timeout: float = libraview.TIMEOUT_SEGUNDOS):
        return httpx.AsyncClient(transport=httpx.MockTransport(falso.handler), timeout=timeout)

    monkeypatch.setattr(libraview, "_nuevo_cliente", cliente)
    return falso


@pytest.fixture
def consultorio(admin_client: TestClient):
    """Una paciente sin DNI ni fecha de nacimiento, con un pedido de dos estudios."""
    r = admin_client.post("/patients", json={
        "id": "p-1", "name": "Ficticia Ana María", "phone": "11 5555-0100", "email": "ana.ficticia@example.com",
    })
    assert r.status_code == 201, r.text
    return admin_client


def _pedido(client: TestClient, patient_id="p-1") -> dict:
    r = client.post(f"/patients/{patient_id}/study-orders", json={
        "author": "Dr. Ficticio Gómez",
        "items": [
            {"study_type": "Radiografía de tórax", "reason": "Tos persistente"},
            {"study_type": "Ecografía abdominal"},
        ],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _datos(pedido: dict, **cambios) -> dict:
    """El cuerpo del `POST .../libraview` que mandaría el diálogo."""
    datos = {
        "items": [
            {"item_id": pedido["items"][0]["id"], "codigo_practica": "RX-TORAX"},
            {"item_id": pedido["items"][1]["id"], "codigo_practica": "ECO-ABD"},
        ],
        "paciente": {
            "apellido": "Ficticia", "nombres": "Ana María", "sexo": "F",
            "numero_documento": "99100001", "fecha_nacimiento": "1975-03-02",
        },
        "medico_solicitante": "Dr. Ficticio Gómez",
        "matricula_solicitante": "MP 99999",
        "diagnostico_presuntivo": "Tos persistente",
        "prioridad": "rutina",
    }
    datos.update(cambios)
    return datos


def _enviar(client: TestClient, pedido: dict, patient_id="p-1", **cambios):
    return client.post(f"/patients/{patient_id}/study-orders/{pedido['id']}/libraview", json=_datos(pedido, **cambios))


def _reintentar(client: TestClient, pedido: dict, patient_id="p-1"):
    return client.post(f"/patients/{patient_id}/study-orders/{pedido['id']}/libraview/reintentar")


# ── La firma ─────────────────────────────────────────────────────────────────


def _firma(cuerpo: bytes, instante: int, secreto: str = SECRETO) -> str:
    v1 = hmac.new(secreto.encode(), f"{instante}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return f"t={instante},v1={v1}"


def test_la_firma_buena_verifica():
    cuerpo = b'{"id_evento":"e1"}'
    assert libraview.verificar_firma(SECRETO, cuerpo, _firma(cuerpo, 1_793_200_000), ahora=1_793_200_100)


def test_la_firma_se_calcula_sobre_el_cuerpo_crudo():
    """🔴 Un espacio de diferencia es otra firma: se verifica sobre los bytes que llegaron, no sobre el JSON vuelto a armar."""
    firmado = b'{"id_evento":"e1"}'
    recibido = b'{"id_evento": "e1"}'
    assert not libraview.verificar_firma(SECRETO, recibido, _firma(firmado, 1_793_200_000), ahora=1_793_200_000)


def test_la_firma_mala_no_verifica():
    cuerpo = b'{"id_evento":"e1"}'
    assert not libraview.verificar_firma(SECRETO, cuerpo, _firma(cuerpo, 1_793_200_000, "otro-secreto"), ahora=1_793_200_000)
    assert not libraview.verificar_firma(SECRETO, cuerpo + b" ", _firma(cuerpo, 1_793_200_000), ahora=1_793_200_000)
    # El instante va DENTRO de lo firmado: cambiarlo en la cabecera invalida la firma.
    adulterada = _firma(cuerpo, 1_793_200_000).replace("t=1793200000", "t=1793200001")
    assert not libraview.verificar_firma(SECRETO, cuerpo, adulterada, ahora=1_793_200_000)


def test_la_firma_vieja_no_verifica_pero_la_del_borde_si():
    cuerpo = b"{}"
    firma = _firma(cuerpo, 1_793_200_000)
    assert libraview.verificar_firma(SECRETO, cuerpo, firma, ahora=1_793_200_000 + 300)
    assert not libraview.verificar_firma(SECRETO, cuerpo, firma, ahora=1_793_200_000 + 301)
    # Un cuerpo capturado y reenviado una semana después.
    assert not libraview.verificar_firma(SECRETO, cuerpo, firma, ahora=1_793_200_000 + 7 * 86400)
    # Y una del futuro lejano (reloj del emisor corrido) tampoco.
    assert not libraview.verificar_firma(SECRETO, cuerpo, firma, ahora=1_793_200_000 - 301)


@pytest.mark.parametrize("cabecera", [
    None, "", "basura", "t=,v1=", "t=abc,v1=00", "t=1793200000", "v1=00", "t=1793200000,v1=", "t=1793200000,v1=ñandú",
    ",,,", "t=1793200000,v1", "t=99999999999999999999999,v1=00",
])
def test_la_cabecera_mal_formada_es_falso_y_no_una_excepcion(cabecera):
    assert libraview.verificar_firma(SECRETO, b"{}", cabecera, ahora=1_793_200_000) is False


def test_sin_secreto_nada_verifica():
    cuerpo = b"{}"
    assert not libraview.verificar_firma("", cuerpo, _firma(cuerpo, 1_793_200_000, ""), ahora=1_793_200_000)


# ── El cuerpo de la orden ────────────────────────────────────────────────────


def test_el_cuerpo_respeta_el_orden_de_las_practicas_y_omite_las_claves_vacias():
    cuerpo = libraview.armar_cuerpo(
        order_id="7b0f3c1e-0000-4000-8000-000000000001", codigos=["ECO-ABD", "RX-TORAX"],
        creado=datetime(2026, 10, 28, 15, 0, tzinfo=UTC),
        paciente={
            "apellido": "Ficticia", "nombres": "Ana María", "sexo": "F", "numero_documento": "99100001",
            "fecha_nacimiento": date(1975, 3, 2), "telefono": "  ", "email": None,
        },
        medico_solicitante="Dr. Ficticio Gómez", matricula_solicitante="", diagnostico_presuntivo=None,
    )
    assert cuerpo["practicas"] == ["ECO-ABD", "RX-TORAX"]
    assert cuerpo["id_externo"] == "7b0f3c1e-0000-4000-8000-000000000001"
    assert cuerpo["prioridad"] == "rutina"
    assert cuerpo["paciente"] == {
        "tipo_documento": "DNI", "numero_documento": "99100001", "apellido": "Ficticia", "nombres": "Ana María",
        "fecha_nacimiento": "1975-03-02", "sexo": "F",
    }
    for omitida in ("matricula_solicitante", "diagnostico_presuntivo"):
        assert omitida not in cuerpo
    assert "telefono" not in cuerpo["paciente"] and "email" not in cuerpo["paciente"]


def test_la_fecha_de_la_orden_es_la_del_dia_en_argentina():
    """🔴 Un pedido de las 22:30 del 28 (UTC-3) son las 01:30 del 29 en UTC. LibraView rechaza una fecha futura y el día de la orden
    es el que vivió la persona."""
    comun = dict(
        order_id="o", codigos=["RX-TORAX"], medico_solicitante="Dr. X",
        paciente={"apellido": "A", "nombres": "B", "sexo": "O", "numero_documento": "1", "fecha_nacimiento": date(2000, 1, 1)},
    )
    de_noche = libraview.armar_cuerpo(creado=datetime(2026, 10, 29, 1, 30, tzinfo=UTC), **comun)
    assert de_noche["fecha_orden"] == "2026-10-28"
    de_dia = libraview.armar_cuerpo(creado=datetime(2026, 10, 28, 12, 0, tzinfo=UTC), **comun)
    assert de_dia["fecha_orden"] == "2026-10-28"
    # Una base sin zona se lee como UTC.
    assert libraview.armar_cuerpo(creado=datetime(2026, 10, 29, 1, 30), **comun)["fecha_orden"] == "2026-10-28"


# ── Sin configurar ───────────────────────────────────────────────────────────


@pytest.fixture
def sin_libraview(monkeypatch):
    for nombre in ("LIBRAVIEW_URL", "LIBRAVIEW_TOKEN", "LIBRAVIEW_WEBHOOK_SECRET"):
        monkeypatch.delenv(nombre, raising=False)


def test_sin_configurar_el_estado_lo_dice_y_nada_mas_funciona(consultorio, sin_libraview):
    assert consultorio.get("/integraciones/libraview/estado").json() == {"configurado": False, "recibe_resultados": False}
    pedido = _pedido(consultorio)
    assert consultorio.get("/integraciones/libraview/practicas").status_code == 503
    assert _enviar(consultorio, pedido).status_code == 503
    assert _reintentar(consultorio, pedido).status_code == 503
    # Y no queda ninguna fila: «apagado» es no tocar nada.
    assert consultorio.get("/integraciones/libraview/envios", params={"patient_id": "p-1"}).json() == []


@pytest.mark.parametrize("falta", ["LIBRAVIEW_URL", "LIBRAVIEW_TOKEN"])
def test_con_la_url_o_el_token_solos_sigue_apagado(consultorio, lv, monkeypatch, falta):
    monkeypatch.delenv(falta)
    assert consultorio.get("/integraciones/libraview/estado").json()["configurado"] is False


def test_el_estado_distingue_si_el_resultado_vuelve_solo(consultorio, lv, monkeypatch):
    assert consultorio.get("/integraciones/libraview/estado").json() == {"configurado": True, "recibe_resultados": True}
    monkeypatch.delenv("LIBRAVIEW_WEBHOOK_SECRET")
    assert consultorio.get("/integraciones/libraview/estado").json() == {"configurado": True, "recibe_resultados": False}


def test_el_estado_pide_sesion(admin_client, lv):
    assert https_client(admin_client.app).get("/integraciones/libraview/estado").status_code == 401


def test_en_un_nodo_la_integracion_no_existe(consultorio, lv, monkeypatch):
    """ADR-045: el envío y el webhook son sólo del central. En la PC del consultorio la pantalla no ofrece nada y la ruta contesta 409."""
    pedido = _pedido(consultorio)
    monkeypatch.setattr(offline, "en_un_nodo", lambda: True)
    assert consultorio.get("/integraciones/libraview/estado").json()["configurado"] is False
    assert _enviar(consultorio, pedido).status_code == 409
    assert lv.llamadas == []


# ── El catálogo ──────────────────────────────────────────────────────────────


def test_el_catalogo_sale_de_libraview_con_el_token(consultorio, lv):
    r = consultorio.get("/integraciones/libraview/practicas")
    assert r.status_code == 200, r.text
    assert [p["codigo"] for p in r.json()] == ["RX-TORAX", "ECO-ABD"]
    assert r.json()[1]["preparacion"] == "Ayuno de 6 horas"
    assert lv.llamadas[0]["auth"] == f"Bearer {TOKEN}"


def test_si_libraview_falla_el_catalogo_es_502(consultorio, lv):
    lv.red_caida = True
    assert consultorio.get("/integraciones/libraview/practicas").status_code == 502


# ── Mandar el pedido ─────────────────────────────────────────────────────────


def test_el_envio_ok_guarda_los_numeros_de_acceso_en_el_orden_de_los_items(consultorio, lv):
    pedido = _pedido(consultorio)
    r = _enviar(consultorio, pedido)
    assert r.status_code == 201, r.text
    envio = r.json()
    assert envio["estado"] == "enviado" and envio["error"] == "" and envio["intentos"] == 1
    assert envio["order_id"] == pedido["id"]
    assert [(i["item_id"], i["codigo_practica"]) for i in envio["items"]] == [
        (pedido["items"][0]["id"], "RX-TORAX"), (pedido["items"][1]["id"], "ECO-ABD"),
    ]
    assert [i["numero_acceso"] for i in envio["items"]] == ["202600000051", "202600000052"]
    # Lo que viajó: el id del pedido, las prácticas en el orden de los ítems, la credencial y nada de más.
    (llamada,) = lv.ordenes_enviadas()
    assert llamada["auth"] == f"Bearer {TOKEN}"
    cuerpo = json.loads(llamada["cuerpo"])
    assert cuerpo["id_externo"] == pedido["id"]
    assert cuerpo["practicas"] == ["RX-TORAX", "ECO-ABD"]
    assert cuerpo["paciente"]["telefono"] == "11 5555-0100"
    assert cuerpo["paciente"]["email"] == "ana.ficticia@example.com"
    assert cuerpo["fecha_orden"] == datetime.now(ZONA_AR).date().isoformat()
    assert cuerpo["matricula_solicitante"] == "MP 99999" and cuerpo["prioridad"] == "rutina"
    # Los envíos del paciente lo muestran, sin el cuerpo (tiene datos del paciente).
    (listado,) = consultorio.get("/integraciones/libraview/envios", params={"patient_id": "p-1"}).json()
    assert listado["estado"] == "enviado" and "cuerpo" not in listado
    assert listado["items"][0]["numero_acceso"] == "202600000051"


def test_las_practicas_van_en_el_orden_de_los_items_aunque_el_pedido_llegue_desordenado(consultorio, lv):
    pedido = _pedido(consultorio)
    datos = _datos(pedido)
    datos["items"].reverse()
    r = consultorio.post(f"/patients/p-1/study-orders/{pedido['id']}/libraview", json=datos)
    assert r.status_code == 201, r.text
    assert json.loads(lv.ordenes_enviadas()[0]["cuerpo"])["practicas"] == ["RX-TORAX", "ECO-ABD"]


def test_un_error_de_libraview_queda_visible_y_el_envio_devuelve_201(consultorio, lv):
    lv.forzar_orden = (503, {"detail": "en mantenimiento"})
    pedido = _pedido(consultorio)
    r = _enviar(consultorio, pedido)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "error" and r.json()["intentos"] == 1
    assert r.json()["error"].startswith("503: ")
    assert [i["numero_acceso"] for i in r.json()["items"]] == [None, None]


def test_un_error_de_red_queda_como_error(consultorio, lv):
    lv.red_caida = True
    r = _enviar(consultorio, _pedido(consultorio))
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "error" and "ConnectError" in r.json()["error"]


def test_los_mensajes_de_error_dicen_lo_que_se_puede_hacer(consultorio, lv):
    pedido = _pedido(consultorio)
    lv.forzar_orden = (401, {"detail": "Credencial inválida"})
    assert "LIBRAVIEW_TOKEN" in _enviar(consultorio, pedido).json()["error"]
    lv.forzar_orden = (409, {"detail": "otro contenido"})
    assert _enviar(consultorio, pedido).json()["error"] == "409: LibraView ya tiene otra orden con este id."
    lv.forzar_orden = (422, {"detail": [{"loc": ["body", "paciente", "numero_documento"], "msg": "DNI de 6 a 9 dígitos", "type": "x"}]})
    assert _enviar(consultorio, pedido).json()["error"] == "422: paciente.numero_documento: DNI de 6 a 9 dígitos"


def test_el_reintento_reenvia_el_mismo_cuerpo_y_libraview_contesta_200_repetida(consultorio, lv):
    """🔴 El invariante de la costura. El primer intento llega a LibraView pero la respuesta se pierde; entre un intento y otro el
    paciente cambió de teléfono. Si el reintento armara el cuerpo de nuevo, LibraView vería otro contenido con el mismo id: 409.
    Reenviando el guardado es un 200 `repetida`."""
    pedido = _pedido(consultorio)
    # El POST llega y se registra del lado de LibraView, pero MedLibra se queda sin respuesta.
    original = lv.handler

    def pierde_la_respuesta(request):
        original(request)
        raise httpx.ReadTimeout("se perdió la respuesta", request=request)

    lv_handler = lv.handler
    lv.handler = pierde_la_respuesta
    primero = _enviar(consultorio, pedido).json()
    lv.handler = lv_handler
    assert primero["estado"] == "error" and "ReadTimeout" in primero["error"]

    # Cambia un dato de la ficha: el cuerpo recalculado ya no sería igual.
    consultorio.put("/patients/p-1", json={
        "name": "Ficticia Ana María", "phone": "11 9999-0000", "email": "otro@example.com",
        "dni": "99100001", "birth_date": "1975-03-02",
    })
    r = _reintentar(consultorio, pedido)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "enviado" and r.json()["intentos"] == 2 and r.json()["error"] == ""
    primero_enviado, segundo_enviado = (c["cuerpo"] for c in lv.ordenes_enviadas())
    assert primero_enviado == segundo_enviado
    assert json.loads(segundo_enviado)["paciente"]["telefono"] == "11 5555-0100"
    assert [i["numero_acceso"] for i in r.json()["items"]] == ["202600000051", "202600000052"]


def test_reintentar_un_error_de_libraview_lo_deja_enviado(consultorio, lv):
    lv.forzar_orden = (503, {"detail": "en mantenimiento"})
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).json()["estado"] == "error"
    lv.forzar_orden = None
    r = _reintentar(consultorio, pedido)
    assert r.json()["estado"] == "enviado" and r.json()["intentos"] == 2
    assert len({c["cuerpo"] for c in lv.ordenes_enviadas()}) == 1


def test_un_pedido_ya_enviado_no_se_vuelve_a_mandar_ni_a_reintentar(consultorio, lv):
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).json()["estado"] == "enviado"
    assert _enviar(consultorio, pedido).status_code == 409
    assert _reintentar(consultorio, pedido).status_code == 409
    assert len(lv.ordenes_enviadas()) == 1


def test_reintentar_sin_envio_previo_es_404(consultorio, lv):
    assert _reintentar(consultorio, _pedido(consultorio)).status_code == 404


def test_se_puede_corregir_un_pedido_con_error_y_volver_a_mandarlo(consultorio, lv):
    """Un 422 por un dato mal escrito no se arregla reintentando el mismo cuerpo: el diálogo vuelve a mandar el pedido y pisa el cuerpo."""
    pedido = _pedido(consultorio)
    lv.forzar_orden = (422, {"detail": "DNI mal"})
    assert _enviar(consultorio, pedido).json()["estado"] == "error"
    lv.forzar_orden = None
    r = _enviar(consultorio, pedido, paciente={**_datos(pedido)["paciente"], "numero_documento": "99100002"})
    assert r.status_code == 201 and r.json()["estado"] == "enviado"
    assert json.loads(lv.ordenes_enviadas()[-1]["cuerpo"])["paciente"]["numero_documento"] == "99100002"


def test_el_pedido_de_otro_paciente_o_inexistente_es_404(consultorio, lv):
    consultorio.post("/patients", json={"id": "p-2", "name": "Ficticio Otro"})
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido, patient_id="p-2").status_code == 404
    assert _enviar(consultorio, pedido, patient_id="p-9").status_code == 404
    assert consultorio.post("/patients/p-1/study-orders/no-existe/libraview", json=_datos(pedido)).status_code == 404
    assert consultorio.get("/integraciones/libraview/envios", params={"patient_id": "p-9"}).status_code == 404


# ── Validar lo que llega del diálogo ─────────────────────────────────────────


def test_cada_item_del_pedido_tiene_que_aparecer_exactamente_una_vez(consultorio, lv):
    pedido = _pedido(consultorio)
    a, b = (i["id"] for i in pedido["items"])
    casos = {
        "falta uno": [{"item_id": a, "codigo_practica": "RX-TORAX"}],
        "uno repetido": [{"item_id": a, "codigo_practica": "RX-TORAX"}, {"item_id": a, "codigo_practica": "ECO-ABD"}],
        "uno de más": [
            {"item_id": a, "codigo_practica": "RX-TORAX"}, {"item_id": b, "codigo_practica": "ECO-ABD"},
            {"item_id": "otro", "codigo_practica": "RX-TORAX"},
        ],
        "uno ajeno": [{"item_id": a, "codigo_practica": "RX-TORAX"}, {"item_id": "otro", "codigo_practica": "ECO-ABD"}],
    }
    for nombre, items in casos.items():
        assert _enviar(consultorio, pedido, items=items).status_code == 422, nombre
    assert _enviar(consultorio, pedido, items=[]).status_code == 422
    assert lv.llamadas == []
    assert consultorio.get("/integraciones/libraview/envios", params={"patient_id": "p-1"}).json() == []


@pytest.mark.parametrize("cambio", [
    {"numero_documento": ""}, {"numero_documento": "   "}, {"fecha_nacimiento": None}, {"fecha_nacimiento": "no-es-fecha"},
    {"fecha_nacimiento": (date.today() + timedelta(days=2)).isoformat()},
    {"sexo": "X"}, {"apellido": " "}, {"nombres": ""},
])
def test_el_documento_y_la_fecha_son_obligatorios_y_el_resto_tiene_que_ser_valido(consultorio, lv, cambio):
    pedido = _pedido(consultorio)
    paciente = {**_datos(pedido)["paciente"], **cambio}
    assert _enviar(consultorio, pedido, paciente=paciente).status_code == 422
    assert lv.llamadas == []


def test_sin_medico_o_con_prioridad_inventada_es_422(consultorio, lv):
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido, medico_solicitante=" ").status_code == 422
    assert _enviar(consultorio, pedido, prioridad="cuando-puedan").status_code == 422
    assert lv.llamadas == []


def test_completa_el_dni_y_la_fecha_vacios_de_la_ficha(consultorio, lv):
    pedido = _pedido(consultorio)
    assert consultorio.get("/patients/p-1").json()["dni"] is None
    assert _enviar(consultorio, pedido).status_code == 201
    ficha = consultorio.get("/patients/p-1").json()
    assert ficha["dni"] == "99100001" and ficha["birth_date"] == "1975-03-02"
    assert ficha["name"] == "Ficticia Ana María"  # el nombre de la ficha no se toca


def test_no_pisa_el_dni_ni_la_fecha_ya_cargados(consultorio, lv):
    """La ficha gana lo que le faltaba, y sólo eso. A LibraView va lo del diálogo, pero un dato ya cargado se corrige editando la ficha."""
    consultorio.put("/patients/p-1", json={
        "name": "Ficticia Ana María", "dni": "11222333", "birth_date": "1980-01-15", "phone": None, "email": None,
    })
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).status_code == 201
    ficha = consultorio.get("/patients/p-1").json()
    assert ficha["dni"] == "11222333" and ficha["birth_date"] == "1980-01-15"


def test_completa_solo_lo_que_falta(consultorio, lv):
    consultorio.put("/patients/p-1", json={"name": "Ficticia Ana María", "dni": "11222333", "birth_date": None})
    assert _enviar(consultorio, _pedido(consultorio)).status_code == 201
    ficha = consultorio.get("/patients/p-1").json()
    assert ficha["dni"] == "11222333" and ficha["birth_date"] == "1975-03-02"


# ── Borrar el pedido ─────────────────────────────────────────────────────────


def test_un_pedido_enviado_no_se_borra(consultorio, lv):
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).json()["estado"] == "enviado"
    r = consultorio.delete(f"/patients/p-1/study-orders/{pedido['id']}")
    assert r.status_code == 409, r.text
    assert "LibraView" in r.json()["detail"]
    assert consultorio.get(f"/patients/p-1/study-orders/{pedido['id']}").status_code == 200


def test_un_pedido_con_el_envio_en_error_se_borra_con_sus_filas(consultorio, lv):
    lv.forzar_orden = (503, {"detail": "caído"})
    pedido = _pedido(consultorio)
    assert _enviar(consultorio, pedido).json()["estado"] == "error"
    assert consultorio.delete(f"/patients/p-1/study-orders/{pedido['id']}").status_code == 204
    assert consultorio.get(f"/patients/p-1/study-orders/{pedido['id']}").status_code == 404
    assert consultorio.app.state.envios_libraview.get(pedido["id"]) is None


def test_un_pedido_sin_envio_se_borra_como_siempre(consultorio, lv):
    pedido = _pedido(consultorio)
    assert consultorio.delete(f"/patients/p-1/study-orders/{pedido['id']}").status_code == 204


# ── El webhook ───────────────────────────────────────────────────────────────


def _evento(pedido: dict, numero_acceso: str, **cambios) -> dict:
    evento = {
        "adendas": 0, "creado_en": "2026-10-28T12:00:00-03:00", "estado_estudio": "informado", "evento": "informe.publicado",
        "id_evento": "8f0c9d2e-0000-4000-8000-000000000001", "id_externo": pedido["id"], "numero_acceso": numero_acceso,
        "practica": "RX-TORAX", "publicado_en": "2026-10-28T12:00:00-03:00",
        "recursos": {"informe": f"/api/integracion/v1/ordenes/{pedido['id']}/estudios/{numero_acceso}/informe"},
    }
    evento.update(cambios)
    return evento


def _avisar(client: TestClient, evento, *, instante=None, secreto=SECRETO, cuerpo: bytes | None = None, headers=None):
    """Lo que hace LibraView: un POST firmado sobre el cuerpo crudo, sin cookie de sesión."""
    cuerpo = cuerpo if cuerpo is not None else json.dumps(evento, sort_keys=True, separators=(",", ":")).encode()
    instante = int(time.time()) if instante is None else instante
    cabeceras = {"X-LibraView-Firma": _firma(cuerpo, instante, secreto), "Content-Type": "application/json"}
    cabeceras.update(headers or {})
    return https_client(client.app).post("/integraciones/libraview/resultados", content=cuerpo, headers=cabeceras)


@pytest.fixture
def enviado(consultorio, lv):
    """Un pedido ya enviado: `(cliente, pedido, [números de acceso])`."""
    pedido = _pedido(consultorio)
    envio = _enviar(consultorio, pedido).json()
    assert envio["estado"] == "enviado"
    return consultorio, pedido, [i["numero_acceso"] for i in envio["items"]]


def _resultados(client: TestClient, pedido: dict) -> list[dict]:
    orden = client.get(f"/patients/p-1/study-orders/{pedido['id']}").json()
    return [r for item in orden["items"] for r in item["results"]]


def _documentos(client: TestClient) -> list[dict]:
    return client.get("/patients/p-1/documents").json()


def _eventos() -> int:
    # La base viva del test: se pide por la app (el engine global de LibraGenda).
    from libragenda.database import get_session_factory
    from sqlalchemy import func, select

    from app.services.libraview import EventoDeLibraViewRow

    with get_session_factory()() as session:
        return session.scalar(select(func.count()).select_from(EventoDeLibraViewRow))


def _archivos(client: TestClient) -> list[str]:
    carpeta = client.app.state.clinical_documents.documents_dir
    return sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []


def test_el_informe_publicado_graba_el_resultado_el_documento_y_el_evento(enviado, lv):
    client, pedido, (acceso, _) = enviado
    r = _avisar(client, _evento(pedido, acceso))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "duplicado": False}

    (resultado,) = _resultados(client, pedido)
    assert resultado["text"] == "Sin hallazgos patológicos."
    assert resultado["author"] == "Dra. Ficticia Ruiz (LibraView)"
    assert resultado["item_id"] == pedido["items"][0]["id"]  # el de la primera práctica

    (documento,) = _documentos(client)
    assert documento["title"] == f"Informe de RX-TORAX — N.º de acceso {acceso}"
    assert documento["content_type"] == "application/pdf" and documento["size_bytes"] == len(PDF)
    assert documento["author"] == "Dra. Ficticia Ruiz (LibraView)"
    descargado = client.get(f"/patients/p-1/documents/{documento['id']}/file")
    assert descargado.status_code == 200 and descargado.content == PDF
    assert _eventos() == 1

    # Pidió el informe y el PDF con la credencial y por rutas armadas acá.
    rutas = lv.rutas()[-2:]
    base = f"/api/integracion/v1/ordenes/{pedido['id']}/estudios/{acceso}"
    assert rutas == [f"{base}/informe", f"{base}/informe.pdf"]
    assert all(c["auth"] == f"Bearer {TOKEN}" for c in lv.llamadas[-2:])


def test_el_resultado_va_al_item_que_corresponde_al_numero_de_acceso(enviado, lv):
    client, pedido, (_, acceso_eco) = enviado
    assert _avisar(client, _evento(pedido, acceso_eco, practica="ECO-ABD")).status_code == 200
    (resultado,) = _resultados(client, pedido)
    assert resultado["item_id"] == pedido["items"][1]["id"]
    assert _documentos(client)[0]["title"].startswith("Informe de ECO-ABD")


def test_el_mismo_evento_dos_veces_no_graba_dos_veces(enviado, lv):
    """LibraView entrega al menos una vez: un 2xx que se pierde se reintenta con el mismo `id_evento`."""
    client, pedido, (acceso, _) = enviado
    assert _avisar(client, _evento(pedido, acceso)).json() == {"ok": True, "duplicado": False}
    llamadas = len(lv.llamadas)
    r = _avisar(client, _evento(pedido, acceso))
    assert r.status_code == 200 and r.json() == {"ok": True, "duplicado": True}
    assert len(_resultados(client, pedido)) == 1 and len(_documentos(client)) == 1 and len(_archivos(client)) == 1
    assert _eventos() == 1
    assert len(lv.llamadas) == llamadas  # ni siquiera volvió a pedir el informe


def test_dos_entregas_a_la_vez_del_mismo_evento_dejan_uno_solo(enviado, lv):
    """La carrera en el PK del evento: la segunda transacción pierde, borra su archivo y cuenta como duplicado."""
    client, pedido, (acceso, _) = enviado
    repo = client.app.state.envios_libraview
    estudio = repo.estudio_por_acceso(acceso, pedido["id"])
    comun = dict(
        estudio=estudio, id_evento="carrera", evento="informe.publicado", numero_acceso=acceso, autor="LibraView",
        texto="x", titulo="t", nombre_pdf="x.pdf", pdf=PDF,
    )
    assert repo.grabar_informe(**comun) == libraview.PROCESADO
    assert repo.grabar_informe(**comun) == libraview.DUPLICADO
    assert len(_resultados(client, pedido)) == 1 and len(_documentos(client)) == 1
    assert len(_archivos(client)) == 1, "el archivo de la entrega perdedora quedó huérfano en disco"


def test_la_adenda_es_un_resultado_mas(enviado, lv):
    client, pedido, (acceso, _) = enviado
    assert _avisar(client, _evento(pedido, acceso)).status_code == 200
    lv.informe["adendas"] = [
        {"texto": "Primera aclaración.", "fecha": "2026-10-29T09:00:00-03:00", "firmado_por": "Dr. Otro"},
        {"texto": "Segunda aclaración.", "fecha": "2026-10-30T09:00:00-03:00", "firmado_por": ""},
    ]
    r = _avisar(client, _evento(pedido, acceso, evento="informe.adenda", id_evento="adenda-1", adendas=1))
    assert r.status_code == 200, r.text
    r = _avisar(client, _evento(pedido, acceso, evento="informe.adenda", id_evento="adenda-2", adendas=2))
    assert r.status_code == 200, r.text

    informe, primera, segunda = sorted(_resultados(client, pedido), key=lambda x: x["created_at"])
    assert informe["text"] == "Sin hallazgos patológicos."  # append-only: el informe no se tocó
    assert (primera["text"], primera["author"]) == ("Adenda 1: Primera aclaración.", "Dr. Otro (LibraView)")
    assert (segunda["text"], segunda["author"]) == ("Adenda 2: Segunda aclaración.", "LibraView")
    titulos = sorted(d["title"] for d in _documentos(client))
    assert titulos[1].endswith("(adenda 1)") and titulos[2].endswith("(adenda 2)")


def test_si_la_adenda_del_aviso_no_coincide_se_toma_la_ultima(enviado, lv):
    client, pedido, (acceso, _) = enviado
    lv.informe["adendas"] = [{"texto": "Única.", "fecha": "x", "firmado_por": "Dr. Otro"}]
    assert _avisar(client, _evento(pedido, acceso, evento="informe.adenda", adendas=7)).status_code == 200
    (resultado,) = _resultados(client, pedido)
    assert resultado["text"] == "Adenda 1: Única."


def test_una_adenda_sin_adendas_en_el_informe_es_502_y_no_graba(enviado, lv):
    client, pedido, (acceso, _) = enviado
    lv.informe["adendas"] = []
    assert _avisar(client, _evento(pedido, acceso, evento="informe.adenda", adendas=1)).status_code == 502
    assert _resultados(client, pedido) == [] and _eventos() == 0


def test_un_estudio_desconocido_es_404_y_no_graba_nada(enviado, lv):
    client, pedido, (acceso, _) = enviado
    assert _avisar(client, _evento(pedido, "999999999999")).status_code == 404
    # El número es de este pedido, pero el aviso dice que es de otro: no coinciden.
    assert _avisar(client, _evento(pedido, acceso, id_externo="otro-pedido")).status_code == 404
    assert _resultados(client, pedido) == [] and _documentos(client) == [] and _eventos() == 0
    assert not [c for c in lv.llamadas if c["metodo"] == "GET"], "pidió un informe de un estudio que no es nuestro"


def test_firma_mala_es_401_con_el_mismo_mensaje_para_todo(enviado, lv):
    client, pedido, (acceso, _) = enviado
    evento = _evento(pedido, acceso)
    mensajes = set()
    for r in (
        _avisar(client, evento, secreto="otro-secreto"),
        _avisar(client, evento, instante=int(time.time()) - 3600),
        _avisar(client, evento, headers={"X-LibraView-Firma": "basura"}),
        _avisar(client, evento, headers={"X-LibraView-Firma": ""}),
    ):
        assert r.status_code == 401, r.text
        mensajes.add(r.text)
    assert len(mensajes) == 1
    sin_cabecera = https_client(client.app).post("/integraciones/libraview/resultados", content=b"{}")
    assert sin_cabecera.status_code == 401 and sin_cabecera.text in mensajes
    assert _resultados(client, pedido) == [] and _eventos() == 0


def test_sin_secreto_el_webhook_es_503_y_no_mira_la_firma(enviado, lv, monkeypatch):
    client, pedido, (acceso, _) = enviado
    monkeypatch.delenv("LIBRAVIEW_WEBHOOK_SECRET")
    assert _avisar(client, _evento(pedido, acceso), secreto="").status_code == 503
    assert _resultados(client, pedido) == []


def test_firmado_pero_sin_lo_necesario_es_422(enviado, lv):
    client, pedido, (acceso, _) = enviado
    assert _avisar(client, None, cuerpo=b"esto no es json").status_code == 422
    assert _avisar(client, [1, 2]).status_code == 422
    for quitar in ("id_evento", "id_externo", "numero_acceso", "evento"):
        evento = _evento(pedido, acceso)
        del evento[quitar]
        assert _avisar(client, evento).status_code == 422, quitar
    assert _avisar(client, _evento(pedido, acceso, evento="informe.cancelado")).status_code == 422
    assert _avisar(client, _evento(pedido, acceso, adendas="uno")).status_code == 422
    assert _resultados(client, pedido) == [] and _eventos() == 0


@pytest.mark.parametrize("campo,valor", [
    ("numero_acceso", "../../etc/passwd"), ("numero_acceso", "2026 0001"), ("numero_acceso", "a/b"),
    ("id_externo", "x?y=1"), ("id_externo", "a" * 101), ("id_evento", "con espacio"),
])
def test_lo_que_entra_a_una_url_se_valida_antes(enviado, lv, campo, valor):
    client, pedido, (acceso, _) = enviado
    evento = {**_evento(pedido, acceso), campo: valor}
    assert _avisar(client, evento).status_code == 422
    assert not [c for c in lv.llamadas if c["metodo"] == "GET"]


def test_nunca_se_siguen_las_urls_que_vienen_en_el_aviso(enviado, lv):
    """El aviso trae `recursos` con rutas. Usarlas sería dejar que quien firma elija a dónde sale un pedido con el token."""
    client, pedido, (acceso, _) = enviado
    evento = _evento(pedido, acceso, recursos={
        "informe": "https://atacante.example/robar", "pdf": "https://atacante.example/robar.pdf",
    })
    assert _avisar(client, evento).status_code == 200
    pedidos = [c for c in lv.llamadas if c["metodo"] == "GET"]
    assert len(pedidos) == 2 and {c["host"] for c in pedidos} == {"libraview.example"}


def test_si_libraview_no_contesta_es_502_y_no_queda_nada_grabado(enviado, lv):
    """🔴 Ni resultado, ni documento, ni archivo en disco, ni el evento: si quedara el evento, el reintento de LibraView sería un
    «duplicado» y el informe se perdería para siempre."""
    client, pedido, (acceso, _) = enviado
    for falla in ("red", "informe", "pdf", "pdf_no_es_pdf"):
        lv.red_caida = falla == "red"
        lv.informe_status = 500 if falla == "informe" else 200
        lv.pdf_status = 500 if falla == "pdf" else 200
        lv.pdf = b"<html>no soy un pdf</html>" if falla == "pdf_no_es_pdf" else PDF
        r = _avisar(client, _evento(pedido, acceso))
        assert r.status_code == 502, (falla, r.text)
        assert _resultados(client, pedido) == [] and _documentos(client) == [], falla
        assert _eventos() == 0 and _archivos(client) == [], falla
    # Y cuando LibraView vuelve, el reintento del MISMO aviso se procesa.
    lv.red_caida = False
    lv.informe_status = lv.pdf_status = 200
    lv.pdf = PDF
    assert _avisar(client, _evento(pedido, acceso)).json() == {"ok": True, "duplicado": False}


def test_si_falla_la_transaccion_no_queda_el_archivo(enviado, lv, monkeypatch, tmp_path):
    client, pedido, (acceso, _) = enviado
    # El 500 a propósito deja su línea en el registro de errores: que sea la carpeta del test y no la del repo.
    monkeypatch.setenv("LIBRA_ERRORES_DIR", str(tmp_path / "errores"))
    repo = client.app.state.envios_libraview
    original = repo.session_factory

    class Rota:
        def begin(self):
            raise RuntimeError("la base se cayó")

        def __call__(self):
            return original()

    monkeypatch.setattr(repo, "session_factory", Rota())
    with pytest.raises(RuntimeError):
        # `raise_server_exceptions` del cliente de prueba: el 500 llega como excepción.
        _avisar(client, _evento(pedido, acceso))
    monkeypatch.setattr(repo, "session_factory", original)
    assert _archivos(client) == []


def test_un_pdf_que_pasa_del_tope_graba_el_resultado_sin_el_documento(enviado, lv, monkeypatch):
    client, pedido, (acceso, _) = enviado
    monkeypatch.setattr(libraview, "MAX_PDF_BYTES", len(PDF) - 1)
    assert _avisar(client, _evento(pedido, acceso)).status_code == 200
    assert len(_resultados(client, pedido)) == 1 and _documentos(client) == [] and _archivos(client) == []


def test_un_aviso_enorme_se_rechaza_sin_leerlo_entero(enviado, lv):
    client, pedido, (acceso, _) = enviado
    relleno = _evento(pedido, acceso, relleno="x" * 70_000)
    assert _avisar(client, relleno).status_code == 413


def test_el_webhook_no_pide_sesion(enviado, lv):
    """🔴 Lo llama LibraView, que no tiene cookie. Si alguien lo cuelga de `staff_or_admin` este test se pone rojo: contestaría 401 con
    una firma buena."""
    client, pedido, (acceso, _) = enviado
    anonimo = https_client(client.app)
    assert anonimo.get("/patients").status_code == 401  # el control: la API del personal sí pide sesión
    cuerpo = json.dumps(_evento(pedido, acceso)).encode()
    r = anonimo.post(
        "/integraciones/libraview/resultados", content=cuerpo,
        headers={"X-LibraView-Firma": _firma(cuerpo, int(time.time()))},
    )
    assert r.status_code == 200, r.text


def test_el_webhook_no_cae_en_la_spa_y_las_rutas_del_personal_siguen_pidiendo_sesion(enviado, lv, tmp_path):
    """Con la SPA montada como en producción, `/integraciones/...` es de la API y no el `index.html` de fallback."""
    client, pedido, (acceso, _) = enviado
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>spa</html>")
    montar_spa(client.app, tmp_path)
    anonimo = https_client(client.app)
    estado = anonimo.get("/integraciones/libraview/estado")
    assert estado.status_code == 401 and estado.headers["content-type"].startswith("application/json")
    sin_firma = anonimo.post("/integraciones/libraview/resultados", content=b"{}")
    assert sin_firma.status_code == 401
    cuerpo = json.dumps(_evento(pedido, acceso)).encode()
    firmado = anonimo.post(
        "/integraciones/libraview/resultados", content=cuerpo,
        headers={"X-LibraView-Firma": _firma(cuerpo, int(time.time()))},
    )
    assert firmado.status_code == 200, firmado.text


def test_en_un_nodo_el_webhook_tampoco_existe(enviado, lv, monkeypatch):
    client, pedido, (acceso, _) = enviado
    monkeypatch.setattr(offline, "en_un_nodo", lambda: True)
    assert _avisar(client, _evento(pedido, acceso)).status_code == 409
    assert _eventos() == 0


# ── Quién puede ──────────────────────────────────────────────────────────────


def test_un_usuario_de_staff_puede_mandar_y_reintentar(staff_client, lv):
    staff_client.post("/patients", json={"id": "p-1", "name": "Ficticia Ana María"})
    pedido = _pedido(staff_client)
    r = _enviar(staff_client, pedido)
    assert r.status_code == 201 and r.json()["estado"] == "enviado"
    (llamada,) = lv.ordenes_enviadas()
    assert json.loads(llamada["cuerpo"])["id_externo"] == pedido["id"]
    assert staff_client.app.state.envios_libraview.get(pedido["id"])["estado"] == "enviado"


def test_sin_sesion_no_se_puede_mandar(admin_client, lv):
    assert https_client(admin_client.app).post("/patients/p-1/study-orders/x/libraview", json={}).status_code == 401
    assert https_client(admin_client.app).get("/integraciones/libraview/practicas").status_code == 401
    assert https_client(admin_client.app).get("/integraciones/libraview/envios", params={"patient_id": "p-1"}).status_code == 401


# ── El cuerpo del envío no se filtra ─────────────────────────────────────────


def test_el_cuerpo_con_datos_del_paciente_no_llega_al_log_de_actividad(consultorio, lv):
    """El log lo lee cualquier admin. El JSON con el nombre, el documento y la fecha de nacimiento no tiene por qué quedar copiado ahí."""
    _enviar(consultorio, _pedido(consultorio))
    filas = consultorio.get("/logs", params={"limit": 200})
    assert filas.status_code == 200, filas.text
    assert "99100001" not in filas.text and "RX-TORAX" not in filas.text and "MP 99999" not in filas.text
    assert "envio a LibraView" in filas.text, "el control: el envío sí se audita, sólo que sin el cuerpo"
