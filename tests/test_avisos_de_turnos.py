"""Los recordatorios de turno salen de verdad por WhatsApp y por mail (ADR-049, libracore ADR-090).

Hasta el ADR-049 el puerto de `libragenda` era un `LoggingNotificationPort` que escribia al log. Ahora lo es
`libracore.avisos.agenda.NotificacionPorAvisos`, con el texto y el contacto de MedLibra (`app/avisos.py`).

🔴 **Nada real sale en este archivo.** WhatsApp va por `ProveedorRegistro` (anota y no manda) o por `ProveedorEvolution` con un
`httpx.MockTransport` (no hay red); el correo, por un doble que anota. Ningun test toca un SMTP ni una URL.

🔴 **El texto no lleva datos de salud.** Cada test que mira un mensaje mira tambien que la prestacion ("Consulta oncologica"), el
nombre del paciente y su DNI no esten: es la regla de la Ley 25.326 y la 26.529 (ver `app/avisos.py`).
"""
from __future__ import annotations

import json
import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import https_client
from fastapi.testclient import TestClient
from libracore import fechas
from libracore.avisos import ESPERA_ENTRE_INTENTOS, Resultado, configuracion
from nodo_apoyo import ejecutar
from test_reminders import _inicio_sin_cruzar_medianoche

from app.avisos import ASUNTO, enviar_recordatorios, texto_del_recordatorio

#: Un jueves lejano: ningun reloj de la suite lo alcanza, y el turno se "vence" con el `ahora` que le pasa el test.
DIA = "2099-01-01"
INICIO = datetime(2099, 1, 1, 13, 0, tzinfo=UTC)  # 10:00 en la sede (UTC-3)
AHORA = INICIO - timedelta(minutes=90)  # dentro de las dos politicas: 24h y 2h

PRESTACION = "Consulta oncológica"
PACIENTE = "Ana Pérez"
DNI = "30111222"
TELEFONO = "11 5555-1234"
DESTINO_WA = "5491155551234"

#: Todo lo que no puede aparecer en un mensaje al paciente.
CLINICO = (PRESTACION, "oncol", PACIENTE, "Ana", "Pérez", DNI)


def _sin_datos_de_salud(texto: str) -> None:
    bajo = texto.lower()
    for dato in CLINICO:
        assert dato.lower() not in bajo, f"{dato!r} no puede viajar en un aviso: {texto!r}"


# ── La siembra ─────────────────────────────────────────────────────────────────────────────────────────────────────


def sembrar(client: TestClient, *, telefono: str | None = TELEFONO, email: str | None = None) -> str:
    """Una sede (con dirección y teléfono), un profesional, una sala, una prestación **clínica**, un paciente y un turno con
    sala a las 10:00 de la sede. Devuelve el id del turno."""
    assert client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte", "timezone": "America/Argentina/Buenos_Aires",
        "phone": "011 4444-5555", "address": "Av. Cabildo 1234, CABA",
    }).status_code == 201
    client.post("/resources", json={"id": "dra-vidal", "name": "Dra. Vidal", "branch_id": "sede-1"})
    client.post("/consultorios", json={"id": "cons-2", "name": "Consultorio 2", "branch_id": "sede-1"})
    client.post("/services", json={"id": "onco", "name": PRESTACION, "duration_minutes": 30})
    paciente = {"id": "p-1", "name": PACIENTE, "dni": DNI}
    if telefono is not None:
        paciente["phone"] = telefono
    if email is not None:
        paciente["email"] = email
    assert client.post("/patients", json=paciente).status_code == 201
    assert client.post("/agenda-blocks", json={
        "resource_id": "dra-vidal", "consultorio_id": "cons-2", "weekday": 3, "starts_at": "09:00:00",
        "ends_at": "13:00:00", "valid_from": "2098-12-01", "valid_to": None, "slot_minutes": 20, "modality": "turnos",
    }).status_code == 201
    creado = client.post("/appointments", json={
        "resource_id": "dra-vidal", "service_id": "onco", "client_id": "p-1", "starts_at": f"{DIA}T10:00:00",
    })
    assert creado.status_code == 201, creado.text
    return creado.json()["id"]


def avisos(client: TestClient, **filtros) -> list[dict]:
    r = client.get("/api/avisos/envios", params=filtros)
    assert r.status_code == 200, r.text
    return sorted(r.json(), key=lambda a: a["clave"])


def configurar(client: TestClient, **cuerpo) -> None:
    r = client.put("/api/avisos/config", json=cuerpo)
    assert r.status_code == 200, r.text


def tanda(client: TestClient, ahora: datetime = AHORA):
    """Una tanda de recordatorios con el reloj fijo: lo mismo que hace `POST /reminders/dispatch`, sin depender de la hora."""
    app = client.app
    return enviar_recordatorios(app.state.reminder_dispatcher, app.state.proveedores_de_avisos, ahora)


# ── Los dobles: ningún proveedor real ──────────────────────────────────────────────────────────────────────────────


class EvolutionSimulado:
    """Un Evolution que no existe: un `httpx.MockTransport` que anota cada pedido y contesta con la lista de estados dada."""

    def __init__(self, estados=(200,)):
        self.estados = list(estados)
        self.pedidos: list[dict] = []
        self.transporte = httpx.MockTransport(self._atender)

    def _atender(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append({"url": str(request.url), "apikey": request.headers.get("apikey"),
                             "cuerpo": json.loads(request.content)})
        estado = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        return httpx.Response(estado, json={"key": {"id": f"wamid-{len(self.pedidos)}"}} if estado < 300 else {})

    @property
    def textos(self) -> list[str]:
        return [p["cuerpo"]["text"] for p in self.pedidos]


@pytest.fixture
def evolution(admin_client: TestClient, monkeypatch):
    """Evolution configurado por la API (el camino real de la pantalla) y con el transporte de mentira."""
    def instalar(estados=(200,)) -> EvolutionSimulado:
        falso = EvolutionSimulado(estados)
        configurar(admin_client, modo="evolution", url="https://evolution.ejemplo.example", instancia="consultorio-demo",
                   apikey="clave-de-prueba")
        original = configuracion.proveedor_whatsapp
        monkeypatch.setattr(configuracion, "proveedor_whatsapp", lambda **_: original(transporte=falso.transporte))
        return falso

    return instalar


class CorreoSimulado:
    """El canal de mail: disponible, y anota lo que se le manda en vez de abrir un SMTP."""

    canal = "email"
    nombre = "correo-simulado"
    simulado = False

    def __init__(self):
        self.mensajes = []

    def disponible(self) -> bool:
        return True

    def enviar(self, mensaje):
        self.mensajes.append(mensaje)
        return Resultado.enviado("correo-1")


@pytest.fixture
def correo(monkeypatch) -> CorreoSimulado:
    falso = CorreoSimulado()
    monkeypatch.setattr(configuracion, "proveedor_email", lambda smtp_config=None, **_: falso)
    return falso


# ── El motor despacha el recordatorio ──────────────────────────────────────────────────────────────────────────────


def test_con_registro_el_recordatorio_se_anota_y_no_sale_nada(admin_client: TestClient):
    turno = sembrar(admin_client)
    configurar(admin_client, modo="registro")

    vencidos = tanda(admin_client)

    assert {(n.appointment_id, n.policy_id) for n in vencidos} == {(turno, "24h"), (turno, "2h")}
    filas = avisos(admin_client)
    assert [(f["clave"], f["canal"], f["estado"], f["proveedor"], f["tipo"], f["destino"]) for f in filas] == [
        (f"agenda:{turno}:24h", "whatsapp", "registrado", "registro", "recordatorio", DESTINO_WA),
        (f"agenda:{turno}:2h", "whatsapp", "registrado", "registro", "recordatorio", DESTINO_WA),
    ]
    texto = filas[0]["cuerpo"]
    assert texto == (
        "*Recordatorio de turno*\n"
        "Tenés un turno el jueves 01/01/2099 a las 10:00 hs.\n"  # la hora de la SEDE (UTC-3), no la del instante (13:00 UTC)
        "Lugar: Consultorio Norte\nProfesional: Dra. Vidal\nConsultorio: Consultorio 2\n"
        "Dirección: Av. Cabildo 1234, CABA\n"
        "Para cambiarlo o cancelarlo, comunicate al 011 4444-5555."
    )
    _sin_datos_de_salud(texto)


def test_con_evolution_simulado_sale_un_mensaje_por_politica_y_nunca_a_la_red(admin_client: TestClient, evolution):
    turno = sembrar(admin_client)
    wa = evolution()

    tanda(admin_client)

    assert len(wa.pedidos) == 2
    for pedido in wa.pedidos:
        assert pedido["url"] == "https://evolution.ejemplo.example/message/sendText/consultorio-demo"
        assert pedido["apikey"] == "clave-de-prueba"
        assert pedido["cuerpo"]["number"] == DESTINO_WA
    for texto in wa.textos:
        assert "Dra. Vidal" in texto and "10:00 hs" in texto
        _sin_datos_de_salud(texto)
    filas = avisos(admin_client)
    assert [(f["clave"], f["estado"], f["proveedor"], f["intentos"]) for f in filas] == [
        (f"agenda:{turno}:24h", "enviado", "evolution", 1),
        (f"agenda:{turno}:2h", "enviado", "evolution", 1),
    ]


def test_el_mismo_recordatorio_no_sale_dos_veces_aunque_dispatch_lo_repita(admin_client: TestClient, evolution):
    """La clave es `agenda:{turno}:{política}`. Se prueba por abajo del libro de `libragenda`: se borra `sent_reminders`, o sea
    que `dispatch` vuelve a ver los dos recordatorios como vencidos, y aun así no sale ningún mensaje más."""
    sembrar(admin_client)
    wa = evolution()
    tanda(admin_client)
    assert len(wa.pedidos) == 2

    ejecutar("DELETE FROM sent_reminders")
    vencidos = tanda(admin_client)

    assert len(vencidos) == 2, "control: dispatch sí volvió a ver los dos recordatorios"
    assert len(wa.pedidos) == 2, "y el motor no los mandó de nuevo"
    assert len(avisos(admin_client)) == 2


def test_un_paciente_sin_telefono_queda_omitido_y_no_se_le_escribe_a_nadie(admin_client: TestClient, evolution):
    turno = sembrar(admin_client, telefono=None)
    wa = evolution()

    tanda(admin_client)

    assert wa.pedidos == []
    filas = avisos(admin_client)
    assert [(f["clave"], f["estado"]) for f in filas] == [
        (f"agenda:{turno}:24h", "omitido"), (f"agenda:{turno}:2h", "omitido"),
    ]
    assert "teléfono" in filas[0]["detalle"]


def test_un_telefono_que_whatsapp_no_reconoce_tambien_queda_omitido(admin_client: TestClient, evolution):
    """«15 5555-1234» (el 15 sin característica) no es un número completo: ante la duda, no se manda."""
    sembrar(admin_client, telefono="15 5555-1234")
    wa = evolution()

    tanda(admin_client)

    assert wa.pedidos == []
    assert {f["estado"] for f in avisos(admin_client)} == {"omitido"}


def test_el_mail_sale_por_su_canal_con_el_mismo_texto_sin_formato_de_whatsapp(admin_client: TestClient, correo):
    """Con WhatsApp apagado (el default) y el correo disponible: un mail por política, a la casilla del paciente."""
    sembrar(admin_client, telefono=None, email="ana@ejemplo.example")

    tanda(admin_client)

    assert len(correo.mensajes) == 2
    for m in correo.mensajes:
        assert m.destino == "ana@ejemplo.example"
        assert m.asunto == ASUNTO
        assert m.cuerpo.startswith("Recordatorio de turno\n"), "el mail va en texto plano: sin los asteriscos de WhatsApp"
        assert "Dra. Vidal" in m.cuerpo
        _sin_datos_de_salud(m.cuerpo)
        _sin_datos_de_salud(m.asunto)
    assert {f["canal"] for f in avisos(admin_client)} == {"email"}


def test_con_los_dos_canales_un_paciente_recibe_un_aviso_por_cada_uno(admin_client: TestClient, evolution, correo):
    sembrar(admin_client, email="ana@ejemplo.example")
    wa = evolution()

    tanda(admin_client)

    assert len(wa.pedidos) == 2 and len(correo.mensajes) == 2
    assert sorted((f["canal"], f["estado"]) for f in avisos(admin_client)) == [("email", "enviado")] * 2 + [
        ("whatsapp", "enviado")] * 2


def test_con_todo_apagado_no_se_escribe_nada_y_el_recordatorio_se_da_por_visto(admin_client: TestClient):
    """Es lo que pasa en toda instancia hasta que alguien prende un canal: igual que el log de antes, no rompe ni acumula."""
    sembrar(admin_client)

    vencidos = tanda(admin_client)

    assert len(vencidos) == 2
    assert avisos(admin_client) == []
    assert tanda(admin_client) == [], "el libro de libragenda los marcó enviados: prender un canal después no reenvía lo viejo"


# ── Un fallo se reintenta después de dispatch ──────────────────────────────────────────────────────────────────────


def test_dispatch_reintenta_lo_que_fallo_en_la_pasada_siguiente(admin_client: TestClient, evolution, monkeypatch):
    """Evolution falla el primer mensaje (500) y anda después: el aviso de 24h queda `fallido` con un solo intento, y el cron lo
    reintenta en la pasada siguiente, pasados 5 minutos (`ESPERA_ENTRE_INTENTOS`, libracore v1.202.1): una pasada enseguida no lo
    toca, para que un fallo de Evolution no gaste dos de los tres intentos en el mismo segundo. El reloj se adelanta, no se duerme.
    Va por HTTP para cubrir la ruta: el turno es de dentro de 90 minutos."""
    inicio = _inicio_sin_cruzar_medianoche(90)
    admin_client.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte", "timezone": "UTC"})
    admin_client.post("/resources", json={"id": "dra-vidal", "name": "Dra. Vidal", "branch_id": "sede-1"})
    admin_client.post("/services", json={"id": "onco", "name": PRESTACION, "duration_minutes": 30})
    admin_client.post("/patients", json={"id": "p-1", "name": PACIENTE, "phone": TELEFONO})
    for weekday in range(7):
        admin_client.post("/resources/dra-vidal/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00"})
    creado = admin_client.post("/appointments", json={
        "resource_id": "dra-vidal", "service_id": "onco", "client_id": "p-1",
        "starts_at": inicio.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    wa = evolution(estados=[500, 200, 200])  # 24h falla, 2h sale, y el reintento del 24h sale

    r = admin_client.post("/reminders/dispatch")

    assert r.status_code == 200, r.text
    assert len(r.json()) == 2
    assert len(wa.pedidos) == 2, "dos mensajes y ningún reintento: el fallo espera a la pasada siguiente"
    assert [(f["clave"], f["estado"], f["intentos"]) for f in avisos(admin_client)] == [
        (f"agenda:{turno}:24h", "fallido", 1), (f"agenda:{turno}:2h", "enviado", 1),
    ]

    # Enseguida, todavía no: faltan los 5 minutos.
    assert admin_client.post("/reminders/dispatch").json() == []
    assert len(wa.pedidos) == 2

    # Pasados los 5 minutos, la pasada siguiente reintenta el 24h (los recordatorios ya están dados por enviados: `dispatch` no encuentra nada).
    ahora = fechas.ahora()
    monkeypatch.setattr(fechas, "ahora", lambda: ahora + ESPERA_ENTRE_INTENTOS + timedelta(seconds=1))
    assert admin_client.post("/reminders/dispatch").json() == []
    assert len(wa.pedidos) == 3, "el reintento del que falló"
    assert [(f["clave"], f["estado"], f["intentos"]) for f in avisos(admin_client)] == [
        (f"agenda:{turno}:24h", "enviado", 2), (f"agenda:{turno}:2h", "enviado", 1),
    ]


def test_un_fallo_del_reintento_no_rompe_la_tanda(admin_client: TestClient, monkeypatch):
    """`dispatch` ya dio los recordatorios por enviados: si `reintentar_fallidos` levantara, la ruta no puede devolver 500."""
    sembrar(admin_client)
    configurar(admin_client, modo="registro")
    import app.avisos as modulo

    def explota(*_a, **_k):
        raise RuntimeError("la base se cayó")

    monkeypatch.setattr(modulo, "reintentar_fallidos", explota)

    assert len(tanda(admin_client)) == 2


# ── El texto ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_el_texto_no_tiene_donde_poner_la_prestacion():
    """La función pura no recibe prestación, paciente ni DNI: no es que las filtre, es que no puede decirlas."""
    import inspect

    parametros = set(inspect.signature(texto_del_recordatorio).parameters)
    assert parametros == {"instante_local", "sede", "profesional", "consultorio", "direccion", "telefono_de_la_sede",
                          "con_formato"}


def test_lo_que_falta_no_deja_renglones_vacios():
    texto = texto_del_recordatorio(datetime(2026, 11, 3, 8, 5), profesional="Dr. Molina")
    assert texto == "Recordatorio de turno\nTenés un turno el martes 03/11/2026 a las 08:05 hs.\nProfesional: Dr. Molina"


@pytest.mark.parametrize(("dia", "nombre"), [(2, "lunes"), (3, "martes"), (4, "miércoles"), (5, "jueves"), (6, "viernes"),
                                              (7, "sábado"), (8, "domingo")])
def test_los_dias_salen_en_castellano_aunque_el_locale_no_lo_sea(dia, nombre):
    assert f"el {nombre} {dia:02d}/11/2026" in texto_del_recordatorio(datetime(2026, 11, dia, 9, 0))


# ── La API de /api/avisos: quién entra ─────────────────────────────────────────────────────────────────────────────

#: (método, ruta, cuerpo) y lo que contesta un admin con WhatsApp apagado. `probar` da 409 `no_disponible`: pasó la guarda y el
#: motor dijo que el canal no está; es la respuesta de un admin, no un rechazo de rol.
RUTAS = [
    ("GET", "/api/avisos/config", None, 200),
    ("PUT", "/api/avisos/config", {"modo": "registro"}, 200),
    ("POST", "/api/avisos/probar", {"canal": "whatsapp", "destino": TELEFONO}, 409),
    ("GET", "/api/avisos/envios", None, 200),
]


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "admin"), RUTAS)
def test_matriz_de_roles_de_la_api_de_avisos(admin_client: TestClient, staff_client: TestClient, metodo, ruta, cuerpo, admin):
    """El registro tiene el teléfono, el mail y el texto de cada aviso a un paciente, y la configuración dice con qué cuenta de
    WhatsApp habla el consultorio: sólo admin. Sin sesión, 401; staff (los médicos y el mostrador), 403."""
    anonimo = https_client(admin_client.app)
    assert anonimo.request(metodo, ruta, json=cuerpo).status_code == 401
    assert staff_client.request(metodo, ruta, json=cuerpo).status_code == 403
    assert admin_client.request(metodo, ruta, json=cuerpo).status_code == admin


def test_la_apikey_no_vuelve_por_la_api(admin_client: TestClient):
    configurar(admin_client, modo="evolution", url="https://evolution.ejemplo.example", instancia="x", apikey="secreta-123")
    r = admin_client.get("/api/avisos/config")
    assert "secreta-123" not in r.text
    assert r.json()["whatsapp"]["apikey_cargada"] is True


def test_el_registro_no_se_espeja_al_nodo():
    """`avisos_envios` es del central (el nodo no manda avisos): ni `EXCLUIDAS` ni `offline` la tienen que espejar. Lo decide
    `test_nodo_aprovisionamiento.py`; acá se deja dicho que el aprovisionamiento no la nombra."""
    from app import offline

    assert "avisos_envios" not in offline.aprovisionamiento.nombres
    assert "avisos_envios" not in offline.TABLAS_DE_REFERENCIA


# ── El script del cron ─────────────────────────────────────────────────────────────────────────────────────────────

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "enviar_recordatorios.py"


def _correr_script(app, monkeypatch, capsys) -> str:
    """Corre `main()` del script con la app de la suite en lugar de `app.asgi` (que se arma desde el entorno del contenedor)."""
    monkeypatch.setitem(sys.modules, "app.asgi", SimpleNamespace(app=app))
    espacio = runpy.run_path(str(SCRIPT), run_name="enviar_recordatorios")
    assert espacio["main"]() == 0
    return capsys.readouterr().out


def test_el_script_del_cron_corre_y_deja_su_linea(admin_client: TestClient, evolution, monkeypatch, capsys):
    """El turno es de 2099: el script usa el reloj real, así que no vence nada. Se prueba que corre y deja su línea; lo que
    sale se prueba arriba con el reloj fijo."""
    sembrar(admin_client)
    evolution()
    salida = _correr_script(admin_client.app, monkeypatch, capsys)
    assert "recordatorios · vencidos: 0" in salida


def test_el_script_respeta_el_modulo_recordatorios_del_plan(admin_client: TestClient, monkeypatch, capsys):
    """La ruta da 403 sin el módulo; el script no pasa por la ruta, así que lo mira él: un plan Básico no manda nada."""
    admin_client.app.state.modules.set_enabled("recordatorios", False)
    llamadas = []
    monkeypatch.setattr(admin_client.app.state.reminder_dispatcher, "dispatch", lambda ahora: llamadas.append(ahora) or [])

    salida = _correr_script(admin_client.app, monkeypatch, capsys)

    assert "el plan de esta instancia no incluye el modulo" in salida
    assert llamadas == []


def test_el_script_no_manda_desde_un_nodo(admin_client: TestClient, monkeypatch, capsys):
    from app import offline

    llamadas = []
    monkeypatch.setattr(admin_client.app.state.reminder_dispatcher, "dispatch", lambda ahora: llamadas.append(ahora) or [])
    monkeypatch.setattr(offline, "en_un_nodo", lambda: True)

    salida = _correr_script(admin_client.app, monkeypatch, capsys)

    assert "es un nodo" in salida
    assert llamadas == []
