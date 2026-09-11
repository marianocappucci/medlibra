"""Las rutas de MedLibra que tocan algo sincrónico no frenan el loop de uvicorn.

🔴 El producto corre uvicorn con **un solo proceso**. Una ruta `async def` que
llama sincrónico a la base —un repositorio, una sesión de SQLAlchemy— o al
disco frena el loop entero mientras dura: ningún otro request avanza,
`/health` incluido. En un test común no se ve, porque la ruta contesta bien: lo
que hace mal es retener a los demás. Acá se mide eso y nada más.

Cómo: una llamada de cada ruta se reemplaza por una que duerme con
`time.sleep` —bloquea el hilo donde corre, como la consulta real— y, mientras
duerme, se pide `/health` por el **mismo loop**. Si la ruta corre fuera del
loop, `/health` termina antes de que la llamada lenta se despierte; si lo
bloquea, `/health` no puede ni empezar hasta entonces. Se compara contra el
instante en que la llamada lenta **se despertó**, no contra un umbral de
tiempo, así que el resultado no depende de lo rápida que sea la máquina.

🔑 Donde la ruta manda la consulta a Contalibra, lo lento va **adentro** de
`contalibra.enviar_consulta`, que es corrutina: pasar la ruta a `def` sin sacar
esa corrutina del loop de uvicorn dejaría el test en rojo igual.

Es la misma medición que `tests/test_rutas_no_bloquean_el_loop.py` de
Contalibra, Restolibra y LibraCore. Cada test se probó contra la ruta como
estaba en `origin/develop`: se ponen rojos, por el bloqueo.
"""
import asyncio
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import contalibra
from app.services.clinical_documents import ClinicalDocumentRepository

#: Lo que duerme la llamada reemplazada. Alcanza con que sea mucho más que lo
#: que tarda un `/health` sin carga.
LENTO = 0.5

#: El host con punto y en https: la cookie de sesión es `Secure` y el cookie
#: jar de httpx no la devuelve por http ni a un host de una sola etiqueta. Es
#: el mismo de `https_client` en `conftest.py`.
BASE = "https://medlibra.test"


class _Lento:
    """Una llamada sincrónica que tarda.

    `time.sleep` y no `asyncio.sleep` es el punto entero: una consulta a la
    base o una escritura a disco no le ceden el control a nadie.
    """

    def __init__(self):
        self.entro = threading.Event()
        self.desperto_en: float | None = None

    def dormir(self):
        self.entro.set()
        time.sleep(LENTO)
        if self.desperto_en is None:
            self.desperto_en = time.monotonic()


def _mientras_duerme(cliente: TestClient, lento: _Lento, pedir):
    """Corre `pedir(c)` con la sesión de `cliente` y, con la llamada lenta ya
    adentro, un `/health` anónimo por el MISMO loop.

    La app es la misma que la de `cliente` —la real, con sus middlewares— pero
    se le pide por `httpx.ASGITransport` desde un loop propio: el `TestClient`
    atiende cada request en su portal y no deja medir dos a la vez.

    Devuelve la respuesta del pedido, la de `/health` y el instante en que
    `/health` terminó.
    """

    async def _correr():
        transporte = httpx.ASGITransport(app=cliente.app)
        async with (
            httpx.AsyncClient(transport=transporte, base_url=BASE,
                              cookies=cliente.cookies) as quien_pide,
            httpx.AsyncClient(transport=transporte, base_url=BASE) as anonimo,
        ):
            tarea = asyncio.create_task(pedir(quien_pide))
            # La espera va a un hilo para no ocupar el loop con la espera misma.
            assert await asyncio.to_thread(lento.entro.wait, 10), (
                "la llamada lenta nunca empezó: el parche no intercepta la ruta")
            health = await anonimo.get("/health")
            health_termino = time.monotonic()
            respuesta = await asyncio.wait_for(tarea, 30)
        return respuesta, health, health_termino

    return asyncio.run(_correr())


def _no_bloqueo(lento: _Lento, health, health_termino: float):
    assert health.status_code == 200, health.text
    # Sin esto el test pasaría si el parche no interceptara nada: sin llamada
    # lenta, no hay nada que bloquee.
    assert lento.desperto_en is not None, "la parte lenta no llegó a correr"
    assert health_termino < lento.desperto_en, (
        f"/health terminó {health_termino - lento.desperto_en:.2f}s DESPUÉS de "
        "que se despertara la llamada lenta: la ruta bloqueó el loop mientras dormía"
    )


# ── El consultorio: un turno con precio, listo para completar ──────────────


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
    precio = client.put("/services/consulta/prices", json={
        "branch_id": "sede-1", "price": "2500.00",
    })
    assert precio.status_code == 200, precio.text
    return client


def _turno_confirmado(client: TestClient) -> str:
    creado = client.post("/appointments", json={
        "resource_id": "dra-vidal", "service_id": "consulta",
        "client_id": "p-1", "starts_at": "2099-01-01T10:00:00",
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    assert client.post(f"/appointments/{turno}/confirm").status_code == 200
    return turno


# ── POST /appointments/{id}/complete ───────────────────────────────────────


@pytest.mark.parametrize("destino", ["con-contalibra", "sin-destino"])
def test_completar_el_turno_no_frena_el_loop(consultorio, monkeypatch, destino):
    """🔑 Con destino, lo lento va ADENTRO de `enviar_consulta`, que es
    corrutina: es el caso que la ruta como `def` no resuelve si la corrutina
    vuelve al loop de uvicorn. Sin destino, lo lento es el registro de la
    consulta como no facturada, que es la base."""
    lento = _Lento()
    if destino == "con-contalibra":
        monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")

        async def enviar_lento(**kwargs):
            lento.dormir()
            return {"venta": {"id": 77}}

        monkeypatch.setattr(contalibra, "enviar_consulta", enviar_lento)
        estado = contalibra.ENVIADO
    else:
        monkeypatch.delenv("CONTALIBRA_URL", raising=False)
        real = contalibra.EnvioRepository.registrar

        def registrar_lento(self, *a, **k):
            lento.dormir()
            return real(self, *a, **k)

        monkeypatch.setattr(contalibra.EnvioRepository, "registrar", registrar_lento)
        estado = contalibra.SIN_DESTINO

    turno = _turno_confirmado(consultorio)
    respuesta, health, fin = _mientras_duerme(consultorio, lento, lambda c: c.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"}))

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == "completed"
    assert respuesta.json()["contalibra"]["estado"] == estado
    _no_bloqueo(lento, health, fin)


# ── POST /facturacion-externa/{id}/reintentar ──────────────────────────────


def test_reintentar_el_envio_no_frena_el_loop(consultorio, monkeypatch):
    """🔑 Lo lento va ADENTRO de `enviar_consulta`, igual que al completar."""
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")

    async def explota(**kwargs):
        raise RuntimeError("503: Service Unavailable")

    monkeypatch.setattr(contalibra, "enviar_consulta", explota)
    turno = _turno_confirmado(consultorio)
    completado = consultorio.post(
        f"/appointments/{turno}/complete", json={"medio_pago": "efectivo"})
    assert completado.json()["contalibra"]["estado"] == contalibra.ERROR, completado.text

    lento = _Lento()

    async def enviar_lento(**kwargs):
        lento.dormir()
        return {"venta": {"id": 77}}

    monkeypatch.setattr(contalibra, "enviar_consulta", enviar_lento)
    respuesta, health, fin = _mientras_duerme(consultorio, lento, lambda c: c.post(
        f"/facturacion-externa/{turno}/reintentar"))

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == contalibra.ENVIADO
    assert respuesta.json()["venta_id"] == 77
    _no_bloqueo(lento, health, fin)


# ── POST /patients/{id}/documents ──────────────────────────────────────────


def test_subir_un_documento_clinico_no_frena_el_loop(admin_client, monkeypatch):
    """Lo lento es el alta del documento: la fila en la base y el archivo en
    disco."""
    creado = admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    assert creado.status_code in (200, 201), creado.text
    lento = _Lento()
    real = ClinicalDocumentRepository.create

    def crear_lento(self, *a, **k):
        lento.dormir()
        return real(self, *a, **k)

    monkeypatch.setattr(ClinicalDocumentRepository, "create", crear_lento)
    contenido = b"%PDF-1.4 contenido de prueba"
    respuesta, health, fin = _mientras_duerme(admin_client, lento, lambda c: c.post(
        "/patients/patient-1/documents",
        data={"author": "Dr. Perez", "title": "Informe de cardiologia"},
        files={"file": ("informe.pdf", contenido, "application/pdf")}))

    assert respuesta.status_code == 201, respuesta.text
    # El archivo tiene que llegar entero: leerlo del `SpooledTemporaryFile` y no
    # con `await file.read()` no puede cambiar lo que se guarda.
    assert respuesta.json()["size_bytes"] == len(contenido)
    _no_bloqueo(lento, health, fin)
