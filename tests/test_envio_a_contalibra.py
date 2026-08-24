"""Mandar la consulta a Contalibra en vez de facturarla acá.

🔴 **El test que manda es el del interruptor.** Lo que no puede pasar es que se
emitan **dos comprobantes por una consulta** —uno acá y otro allá—, porque un
CAE emitido no se borra: se anula con una nota de crédito. Por eso hay un test
que verifica que con Contalibra configurada **este producto no factura**, y su
control, que sin ella **sí lo hace**.

Lo segundo que importa es que un fallo del otro lado **no rompa el completar del
turno** —la atención ya ocurrió— y que aun así **no sea invisible**: una consulta
que no se facturó y de la que nadie se entera es plata que se pierde en silencio.

El HTTP se intercepta con un doble de `enviar_consulta`. No se levanta un
Contalibra de verdad: lo que este archivo mide es la decisión de MedLibra, no el
contrato del otro lado — eso lo prueba la suite de Contalibra, contra su propia
base.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.services import contalibra


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
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
    client.put("/services/consulta/prices", json={
        "branch_id": "sede-1", "price": "2500.00",
    })
    return client


def _completar(client: TestClient, hora="10:00"):
    creado = client.post("/appointments", json={
        "resource_id": "dra-vidal", "service_id": "consulta",
        "client_id": "p-1", "starts_at": f"2099-01-01T{hora}:00",
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    assert client.post(f"/appointments/{turno}/confirm").status_code == 200
    respuesta = client.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"},
    )
    return turno, respuesta


@pytest.fixture
def con_contalibra(monkeypatch):
    """Con `CONTALIBRA_URL` puesta y el envío interceptado.

    Devuelve la lista de cuerpos enviados, para poder afirmar sobre lo que
    viajó y no sólo sobre que se llamó.
    """
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    enviados = []

    async def falso(**kwargs):
        enviados.append(kwargs)
        return {"venta": {"id": 77}, "factura": {"id": 5}, "ya_existia": False}

    monkeypatch.setattr(contalibra, "enviar_consulta", falso)
    return enviados


# ── El interruptor ─────────────────────────────────────────────────────────

def test_sin_contalibra_configurada_la_consulta_queda_SIN_FACTURAR(
    consultorio: TestClient, monkeypatch,
):
    """🔴 **Cambió de significado el 2026-08-24.** Hasta ADR-036 este test
    verificaba que sin `CONTALIBRA_URL` MedLibra facturara por su cuenta; ahora
    no queda motor local que lo haga.

    Lo que se exige es que **no sea silencioso**: el turno se completa —la
    atención ocurrió— pero la consulta queda registrada como no facturada, con
    su motivo, en vez de desaparecer. Un turno cobrado sin comprobante y sin
    rastro es plata que se pierde sin que nadie se entere."""
    monkeypatch.delenv("CONTALIBRA_URL", raising=False)
    _, respuesta = _completar(consultorio)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == "completed"
    envio = respuesta.json()["contalibra"]
    assert envio["estado"] == "sin_destino"
    assert "CONTALIBRA_URL" in envio["error"]


def test_no_queda_ningun_camino_de_facturacion_local(consultorio: TestClient):
    """🔴 **El test que manda.** Si quedara un camino de emisión acá, saldrían
    dos comprobantes por una consulta — y un CAE no se borra, se anula con una
    nota de crédito.

    Se mide sobre **el schema de OpenAPI** y no leyendo el código ni la lista
    de rutas: lo que importa no es que el archivo se haya borrado, sino que no
    quede ruta publicada que emita. (Y no todas las entradas de `app.routes`
    tienen `.path` — los routers incluidos no —, así que recorrerlas a mano
    mide de menos sin avisar.)"""
    rutas = consultorio.app.openapi()["paths"]
    # 🔴 Control positivo: un cero esperado no vale nada si la lista vino vacía
    # porque el schema no se armó.
    assert len(rutas) > 20, f"el schema trajo {len(rutas)} rutas: no se midió nada"
    assert not [r for r in rutas if "arca" in r or "billing" in r], sorted(rutas)
    assert consultorio.get("/config/arca").status_code == 404


def test_con_contalibra_configurada_se_manda(
    consultorio: TestClient, con_contalibra,
):
    _, respuesta = _completar(consultorio)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["contalibra"]["estado"] == "enviado"
    assert len(con_contalibra) == 1


def test_la_alicuota_de_la_prestacion_viaja_con_la_consulta(
    consultorio: TestClient, con_contalibra,
):
    """🔴 En salud el caso normal es el **exento**, y esa configuración es de la
    prestación (ADR-027) — vive acá, no en el negocio que factura. Sin mandarla,
    Contalibra usa su default del 21% y la feature entera queda configurable y
    sin efecto, en silencio.

    ⚠️ Este test llega hasta `enviar_consulta`, no hasta el pedido: mide que
    `complete_appointment` **resuelva** la alícuota y la pase. Que además llegue
    al cuerpo HTTP con el nombre correcto lo cubre
    `test_el_pedido_lleva_el_vocabulario_de_contalibra`, y hace falta — con el
    doble puesto acá, `"iva_rate": None` en el cuerpo pasa en verde."""
    assert consultorio.put(
        "/services/consulta/iva", json={"rate": "0"},
    ).status_code == 200
    _completar(consultorio)
    assert float(con_contalibra[0]["iva_rate"]) == 0.0


def test_sin_alicuota_propia_viaja_la_de_la_instancia(
    consultorio: TestClient, con_contalibra,
):
    """🔴 El control: si viajara siempre `None`, el test de arriba pasaría con
    la alícuota puesta en 0 por casualidad."""
    _completar(consultorio)
    assert float(con_contalibra[0]["iva_rate"]) == 0.21


def test_lo_que_viaja_es_el_turno_y_su_precio(
    consultorio: TestClient, con_contalibra,
):
    turno_id, _ = _completar(consultorio)
    enviado = con_contalibra[0]
    # La referencia es el id del turno: es lo que hace idempotente al reintento
    # del otro lado. Dos consultas del mismo paciente el mismo día son dos.
    assert enviado["appointment_id"] == turno_id
    assert float(enviado["importe"]) == 2500.0
    assert enviado["medio_pago"] == "efectivo"
    # ⚠️ Acá el paciente todavía es el dict CRUDO de MedLibra (`name`): el mapeo
    # al vocabulario de Contalibra (`nombre`) lo hace `enviar_consulta`, que en
    # estos tests está reemplazada por el doble. Ese mapeo tiene su propio test
    # más abajo, contra el cuerpo HTTP de verdad.
    assert enviado["paciente"]["name"] == "Ana"


def test_el_honorario_del_profesional_es_lo_que_viaja(
    consultorio: TestClient, con_contalibra,
):
    """🔴 Lo que se manda pasa por el MISMO resolvedor que la factura local
    (`precio_del_turno`). Si el envío leyera el precio por su cuenta, el
    honorario del profesional aplicaría facturando acá y no mandando allá."""
    consultorio.put("/resources/dra-vidal/prices", json={
        "service_id": "consulta", "price": "4000.00",
    })
    _completar(consultorio)
    assert float(con_contalibra[0]["importe"]) == 4000.0


# ── Cuando el otro lado falla ──────────────────────────────────────────────

@pytest.fixture
def contalibra_caida(monkeypatch):
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")

    async def explota(**kwargs):
        raise RuntimeError("503: Service Unavailable")

    monkeypatch.setattr(contalibra, "enviar_consulta", explota)


def test_si_contalibra_falla_el_turno_se_completa_igual(
    consultorio: TestClient, contalibra_caida,
):
    """🔴 La atención ya ocurrió. Negarse a completarla porque la contabilidad
    de otro producto no contesta sería castigar al consultorio por una falla que
    no es suya — y `COMPLETED` no admite otra transición, así que un turno que
    no se puede completar queda trabado para siempre."""
    _, respuesta = _completar(consultorio)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == "completed"


def test_pero_el_fallo_NO_es_invisible(consultorio: TestClient, contalibra_caida):
    """🔴 La otra mitad. Un turno completado y una consulta sin facturar, sin
    rastro, es plata que se pierde en silencio."""
    turno_id, respuesta = _completar(consultorio)
    assert respuesta.json()["contalibra"]["estado"] == "error"
    assert "503" in respuesta.json()["contalibra"]["error"]

    listado = consultorio.get("/facturacion-externa?solo_pendientes=true").json()
    assert listado["destino"] == "https://contalibra.example"
    assert [e["appointment_id"] for e in listado["envios"]] == [turno_id]


def test_el_listado_dice_el_destino_aunque_no_haya_envios(
    consultorio: TestClient, monkeypatch,
):
    """🔴 Una lista vacía significa cosas opuestas —"todo salió bien" contra
    "esto ni siquiera está prendido"— y sin el destino la pantalla no las puede
    distinguir."""
    monkeypatch.delenv("CONTALIBRA_URL", raising=False)
    listado = consultorio.get("/facturacion-externa").json()
    assert listado["destino"] == ""
    assert listado["envios"] == []


# ── El reintento ───────────────────────────────────────────────────────────

def test_reintentar_manda_de_nuevo_y_deja_el_envio_en_enviado(
    consultorio: TestClient, monkeypatch,
):
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    fallos = {"quedan": 1}
    enviados = []

    async def a_veces(**kwargs):
        enviados.append(kwargs)
        if fallos["quedan"]:
            fallos["quedan"] -= 1
            raise RuntimeError("503: Service Unavailable")
        return {"venta": {"id": 77}}

    monkeypatch.setattr(contalibra, "enviar_consulta", a_veces)

    turno_id, respuesta = _completar(consultorio)
    assert respuesta.json()["contalibra"]["estado"] == "error"

    reintento = consultorio.post(f"/facturacion-externa/{turno_id}/reintentar")
    assert reintento.status_code == 200, reintento.text
    assert reintento.json()["estado"] == "enviado"
    assert reintento.json()["venta_id"] == 77
    # Y quedó contado: dos intentos sobre el mismo turno, no dos filas.
    assert reintento.json()["intentos"] == 2
    assert len(enviados) == 2


def test_reintentar_recalcula_el_precio_de_hoy(consultorio: TestClient, monkeypatch):
    """🔴 No se guarda el cuerpo del envío fallido. Si entre el intento y el
    reintento cambió el honorario, lo que tiene que viajar es el precio de hoy —
    un JSON congelado facturaría el de ayer."""
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    enviados = []

    async def explota_primero(**kwargs):
        enviados.append(kwargs)
        if len(enviados) == 1:
            raise RuntimeError("503")
        return {"venta": {"id": 77}}

    monkeypatch.setattr(contalibra, "enviar_consulta", explota_primero)

    turno_id, _ = _completar(consultorio)
    assert float(enviados[0]["importe"]) == 2500.0

    consultorio.put("/resources/dra-vidal/prices", json={
        "service_id": "consulta", "price": "4000.00",
    })
    consultorio.post(f"/facturacion-externa/{turno_id}/reintentar")
    assert float(enviados[1]["importe"]) == 4000.0


def test_reintentar_sin_contalibra_configurada_se_rechaza(
    consultorio: TestClient, monkeypatch,
):
    monkeypatch.delenv("CONTALIBRA_URL", raising=False)
    rechazado = consultorio.post("/facturacion-externa/lo-que-sea/reintentar")
    assert rechazado.status_code == 409
    assert "CONTALIBRA_URL" in rechazado.json()["detail"]


def test_reintentar_un_turno_que_no_existe_da_404(
    consultorio: TestClient, monkeypatch,
):
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    assert consultorio.post(
        "/facturacion-externa/fantasma/reintentar",
    ).status_code == 404


# ── El cuerpo que sale por el cable ────────────────────────────────────────
#
# 🔴 Todo lo de arriba reemplaza `enviar_consulta` por un doble, así que **no
# mide el pedido HTTP**: el nombre de los campos, la URL y el header quedarían
# sin cubrir, y son exactamente lo que hace que el otro lado conteste 401 o 422
# sin que nada de acá se ponga rojo. Escribiendo esto ya apareció uno: el header
# se había puesto como `X-Service-Token` y el que libraauth valida es
# `x-internal-auth`.


@pytest.mark.anyio
async def test_el_pedido_lleva_el_vocabulario_de_contalibra(monkeypatch):
    import httpx

    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example/")
    monkeypatch.setenv("CONTALIBRA_SERVICE_TOKEN", "un-token")
    capturado = {}

    async def post_falso(self, url, **kwargs):
        capturado["url"] = url
        capturado["json"] = kwargs.get("json")
        capturado["headers"] = kwargs.get("headers")
        return httpx.Response(200, json={"venta": {"id": 1}})

    monkeypatch.setattr(httpx.AsyncClient, "post", post_falso)

    await contalibra.enviar_consulta(
        appointment_id="turno-1", fecha="2026-08-24", descripcion="consulta",
        importe=2500, medio_pago="efectivo",
        paciente={"name": "Ana", "cuit": "20111222333",
                  "condicion_iva": "Responsable Inscripto"},
        iva_rate=Decimal("0"),
    )

    # La barra final de la URL configurada no se duplica.
    assert capturado["url"] == "https://contalibra.example/api/integraciones/consultas"
    # El header es el que valida libraauth del otro lado, no uno inventado.
    assert capturado["headers"]["x-internal-auth"] == "un-token"

    cuerpo = capturado["json"]
    assert cuerpo["sistema"] == "medlibra"
    assert cuerpo["referencia"] == "turno-1"
    assert cuerpo["importe"] == 2500.0
    assert cuerpo["facturar"] is True
    # 🔴 **La alícuota, en el cuerpo y con el nombre que espera el otro lado.**
    # Los dos tests que la miran arriba interceptan `enviar_consulta`, o sea que
    # miden que `complete_appointment` la resuelva y la pase — no que llegue al
    # pedido. Con ese doble, escribir mal la clave acá (o mandar `None` siempre)
    # los deja en verde y la consulta exenta se declara al 21% del otro lado.
    # Verificado por mutación: forzando `"iva_rate": None` en el cuerpo, este
    # test es el único que se pone rojo.
    assert cuerpo["iva_rate"] == 0.0
    # El paciente traducido: `name` de acá es `nombre` allá.
    assert cuerpo["paciente"] == {
        "nombre": "Ana", "cuit": "20111222333",
        "condicion_iva": "Responsable Inscripto",
    }


@pytest.mark.anyio
async def test_sin_alicuota_el_cuerpo_la_manda_nula_y_no_la_omite(monkeypatch):
    """🔴 El control del de arriba, por el otro lado.

    Si `iva_rate` viajara siempre `0.0` —o el `float()` reventara con `None`—,
    aquel test pasaría igual. Y la diferencia importa: `None` significa *no
    declaro nada, usá tu default*, que del lado de Contalibra es el 21%.
    Mandar `0.0` en su lugar declararía **exento** todo lo que no tiene alícuota
    propia, que es el error inverso y peor: IVA no declarado.
    """
    import httpx

    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    capturado = {}

    async def post_falso(self, url, **kwargs):
        capturado["json"] = kwargs.get("json")
        return httpx.Response(200, json={"venta": {"id": 1}})

    monkeypatch.setattr(httpx.AsyncClient, "post", post_falso)

    await contalibra.enviar_consulta(
        appointment_id="turno-2", fecha="2026-08-24", descripcion="consulta",
        importe=2500, medio_pago="efectivo", paciente={"name": "Ana"},
    )

    assert "iva_rate" in capturado["json"], "la clave tiene que estar, aunque sea nula"
    assert capturado["json"]["iva_rate"] is None


@pytest.mark.anyio
async def test_un_error_del_otro_lado_conserva_lo_que_dijo(monkeypatch):
    """Contalibra contesta cosas accionables ("no tiene configurado el usuario
    para integraciones"). Quedarse sólo con el número de estado dejaría al
    usuario con un 409 y nada más."""
    import httpx

    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")

    async def post_falso(self, url, **kwargs):
        return httpx.Response(409, text="Esta instancia no tiene configurado el usuario")

    monkeypatch.setattr(httpx.AsyncClient, "post", post_falso)

    with pytest.raises(RuntimeError) as error:
        await contalibra.enviar_consulta(
            appointment_id="t", fecha="2026-08-24", descripcion="c",
            importe=1, medio_pago="efectivo", paciente={"name": "Ana"},
        )
    assert "409" in str(error.value)
    assert "no tiene configurado el usuario" in str(error.value)


@pytest.mark.anyio
async def test_sin_url_configurada_no_sale_ningun_pedido(monkeypatch):
    monkeypatch.delenv("CONTALIBRA_URL", raising=False)
    with pytest.raises(RuntimeError, match="CONTALIBRA_URL"):
        await contalibra.enviar_consulta(
            appointment_id="t", fecha="2026-08-24", descripcion="c",
            importe=1, medio_pago="efectivo", paciente={"name": "Ana"},
        )
