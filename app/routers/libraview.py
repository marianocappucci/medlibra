"""La costura con LibraView (ADR-050): el pedido de estudios sale como orden y el informe vuelve como resultado.

Dos routers con dos guardas distintas, y es lo que importa de este archivo:

- `router` — lo que usa el personal. Se monta con la guarda de sesión (`require_staff`), como el resto de la historia clínica.
- `webhook_router` — `POST /integraciones/libraview/resultados`, lo que llama **LibraView**. **Sin sesión a propósito**: quien llama
  no es una persona. Lo protege la firma HMAC del cuerpo crudo con `LIBRAVIEW_WEBHOOK_SECRET`. Se monta **sin** `staff_or_admin` y
  sin el gate de módulos (en `app/main.py`); no hay CSRF en este producto (la sesión es una cookie `SameSite` y la API no acepta
  formularios), así que no hay nada más que eximir.

En un nodo de LibraEdge (ADR-045) ni el envío ni el webhook existen: la misma guarda de «sólo central» que los resultados de los
estudios (`historia_en_nodo.exigir_central_para_resultados`). El webhook en un nodo es un caso teórico (LibraView no lo conoce), pero
dejarlo sin guarda sería la única escritura de resultados que no la tiene.
"""
import asyncio
import json
import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from libracore.fechas import hoy
from pydantic import BaseModel, Field

from .. import offline
from ..auth import get_current_user
from ..dependencies import (
    get_envio_libraview_repository,
    get_patient_repository,
    get_study_order_repository,
)
from ..services import historia_en_nodo, libraview
from ..services.patients import PatientRepository
from ..services.study_orders import StudyOrderRepository
from ._instantes import InstanteUTC

_log = logging.getLogger(__name__)

router = APIRouter(tags=["libraview"])
webhook_router = APIRouter(tags=["libraview"])

#: El aviso de LibraView es chico (ids, sin texto clínico). Un tope antes de verificar la firma: esta ruta no pide sesión y no hay por
#: qué leer megas de cualquiera.
MAX_BYTES_AVISO = 64 * 1024

_SOLO_CENTRAL = [Depends(historia_en_nodo.exigir_central_para_resultados)]


class EstadoOut(BaseModel):
    #: Hay con quién hablar: `LIBRAVIEW_URL` y `LIBRAVIEW_TOKEN` (y no es un nodo). La pantalla no muestra nada si es falso.
    configurado: bool
    #: Además, está el secreto del webhook: el informe vuelve solo.
    recibe_resultados: bool


class PracticaOut(BaseModel):
    codigo: str
    nombre: str
    modalidad: str | None = None
    codigo_nomenclador: str | None = None
    preparacion: str | None = None


class EstudioEnvioOut(BaseModel):
    item_id: str
    codigo_practica: str
    numero_acceso: str | None


class EnvioOut(BaseModel):
    order_id: str
    estado: str
    error: str
    intentos: int
    actualizado: InstanteUTC
    items: list[EstudioEnvioOut]


class ItemEnvio(BaseModel):
    item_id: str
    codigo_practica: str = Field(min_length=1, max_length=100)


class PacienteEnvio(BaseModel):
    apellido: str = Field(min_length=1, max_length=100)
    nombres: str = Field(min_length=1, max_length=100)
    sexo: Literal["F", "M", "O"]
    numero_documento: str = Field(min_length=1, max_length=20)
    fecha_nacimiento: date


class EnvioCreate(BaseModel):
    items: list[ItemEnvio] = Field(min_length=1)
    paciente: PacienteEnvio
    medico_solicitante: str = Field(min_length=1, max_length=200)
    matricula_solicitante: str | None = Field(default=None, max_length=100)
    diagnostico_presuntivo: str | None = Field(default=None, max_length=500)
    prioridad: Literal["rutina", "urgente"] = "rutina"


# ── El personal ──────────────────────────────────────────────────────────────


def _en_este_nodo() -> bool:
    return offline.en_un_nodo()


@router.get("/integraciones/libraview/estado", response_model=EstadoOut)
def estado():
    """Si la integración está prendida. En un nodo, no: el envío es sólo del central."""
    prendida = libraview.configurado() and not _en_este_nodo()
    return {"configurado": prendida, "recibe_resultados": prendida and libraview.recibe_resultados()}


def _exigir_configurado() -> None:
    if not libraview.configurado():
        raise HTTPException(503, "LibraView no está configurado en esta instancia (faltan LIBRAVIEW_URL y LIBRAVIEW_TOKEN).")


@router.get("/integraciones/libraview/practicas", response_model=list[PracticaOut], dependencies=_SOLO_CENTRAL)
def practicas():
    """El catálogo de prácticas de LibraView, para elegir la de cada ítem del pedido."""
    _exigir_configurado()
    try:
        return asyncio.run(libraview.practicas())
    except libraview.LibraViewNoDisponible as exc:
        raise HTTPException(502, str(exc))


@router.get("/integraciones/libraview/envios", response_model=list[EnvioOut])
def envios(
    patient_id: str = Query(...),
    repo: libraview.EnvioRepository = Depends(get_envio_libraview_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    """Los envíos de los pedidos de un paciente: estado, error, intentos y el número de acceso de cada ítem."""
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")
    return repo.listar_por_paciente(patient_id)


def _pedido(patient_id: str, order_id: str, orders: StudyOrderRepository) -> dict:
    order = orders.get(order_id)
    if order is None or order["patient_id"] != patient_id:
        raise HTTPException(404, "study order not found")
    return order


@router.post(
    "/patients/{patient_id}/study-orders/{order_id}/libraview", status_code=201, response_model=EnvioOut,
    dependencies=_SOLO_CENTRAL,
)
def enviar_pedido(
    patient_id: str,
    order_id: str,
    data: EnvioCreate,
    user: dict = Depends(get_current_user),
    repo: libraview.EnvioRepository = Depends(get_envio_libraview_repository),
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    """Manda el pedido a LibraView como una orden (una, con una práctica por ítem).

    Devuelve `201` **aunque el envío haya quedado en error**: el error es parte de la respuesta (`estado`, `error`), se ve en la
    pantalla y se reintenta, igual que el envío a Contalibra. Un `4xx` es sólo cuando el pedido que llegó acá está mal.

    `def` y no `async def`: lo que hace es la base (sincrónica) y el HTTP va en un loop propio de este hilo con `asyncio.run`, para
    no frenar el de uvicorn."""
    _exigir_configurado()
    paciente = patients.get(patient_id)
    if paciente is None:
        raise HTTPException(404, "patient not found")
    pedido = _pedido(patient_id, order_id, orders)
    previo = repo.get(order_id)
    if previo is not None and previo["estado"] == libraview.ENVIADO:
        raise HTTPException(409, "Este pedido ya está en LibraView.")

    # Cada ítem del pedido, exactamente una vez: una práctica de menos es un estudio que no se pide, una de más es un estudio que
    # el pedido no tiene.
    ids_del_pedido = [item["id"] for item in pedido["items"]]
    ids_enviados = [item.item_id for item in data.items]
    if sorted(ids_enviados) != sorted(ids_del_pedido):
        raise HTTPException(422, "Hay que elegir una práctica por cada ítem del pedido, una sola vez cada uno.")
    if data.paciente.fecha_nacimiento > hoy():
        raise HTTPException(422, "La fecha de nacimiento no puede ser futura.")
    for campo, valor in (
        ("el apellido", data.paciente.apellido), ("los nombres", data.paciente.nombres),
        ("el documento", data.paciente.numero_documento), ("el médico solicitante", data.medico_solicitante),
    ):
        if not valor.strip():
            raise HTTPException(422, f"Falta {campo}.")
    codigos = {item.item_id: item.codigo_practica.strip() for item in data.items}
    if not all(codigos.values()):
        raise HTTPException(422, "Falta la práctica de un ítem.")

    # La ficha gana lo que le faltaba (y sólo eso): ver `completar_documento_y_nacimiento`.
    patients.completar_documento_y_nacimiento(
        patient_id, data.paciente.numero_documento.strip(), data.paciente.fecha_nacimiento,
    )
    cuerpo = libraview.armar_cuerpo(
        order_id=order_id,
        codigos=[codigos[i] for i in ids_del_pedido],
        creado=pedido["created_at"],
        paciente={
            "apellido": data.paciente.apellido.strip(), "nombres": data.paciente.nombres.strip(),
            "sexo": data.paciente.sexo, "numero_documento": data.paciente.numero_documento.strip(),
            "fecha_nacimiento": data.paciente.fecha_nacimiento,
            "telefono": paciente.get("phone"), "email": paciente.get("email"),
        },
        medico_solicitante=data.medico_solicitante.strip(),
        matricula_solicitante=data.matricula_solicitante,
        diagnostico_presuntivo=data.diagnostico_presuntivo,
        prioridad=data.prioridad,
    )
    quien = user.get("name") or user.get("username") or ""
    repo.preparar(
        order_id, libraview.serializar(cuerpo), [(i, codigos[i]) for i in ids_del_pedido], quien,
    )
    return asyncio.run(libraview.enviar(repo, order_id))


@router.post(
    "/patients/{patient_id}/study-orders/{order_id}/libraview/reintentar", response_model=EnvioOut,
    dependencies=_SOLO_CENTRAL,
)
def reintentar(
    patient_id: str,
    order_id: str,
    repo: libraview.EnvioRepository = Depends(get_envio_libraview_repository),
    orders: StudyOrderRepository = Depends(get_study_order_repository),
):
    """Vuelve a mandar **el mismo cuerpo** que quedó guardado. Es seguro: LibraView es idempotente por `id_externo` y un cuerpo
    idéntico vuelve `200 repetida`, incluso si el envío anterior había llegado y la respuesta se perdió.

    **No** recalcula nada del pedido ni del paciente (a diferencia del reintento de Contalibra): un cuerpo distinto con el mismo id
    sería un 409. Para corregir un dato que LibraView rechazó se vuelve a mandar el pedido desde el diálogo."""
    _exigir_configurado()
    _pedido(patient_id, order_id, orders)
    previo = repo.get(order_id)
    if previo is None:
        raise HTTPException(404, "Este pedido no se mandó a LibraView.")
    if previo["estado"] == libraview.ENVIADO:
        raise HTTPException(409, "Este pedido ya está en LibraView.")
    return asyncio.run(libraview.enviar(repo, order_id))


# ── LibraView ────────────────────────────────────────────────────────────────


async def _cuerpo_crudo(request: Request) -> bytes:
    """El cuerpo **crudo**, con tope. La firma se calcula sobre estos bytes, no sobre el JSON vuelto a armar."""
    if int(request.headers.get("content-length", "0") or 0) > MAX_BYTES_AVISO:
        raise HTTPException(413, "Aviso demasiado grande.")
    cuerpo = bytearray()
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > MAX_BYTES_AVISO:
            raise HTTPException(413, "Aviso demasiado grande.")
    return bytes(cuerpo)


@webhook_router.post("/integraciones/libraview/resultados", dependencies=_SOLO_CENTRAL)
def recibir_resultado(
    request: Request,
    cuerpo: bytes = Depends(_cuerpo_crudo),
    repo: libraview.EnvioRepository = Depends(get_envio_libraview_repository),
):
    """El aviso de LibraView: se publicó un informe (o una adenda).

    | Respuesta | Cuándo | Qué hace LibraView |
    |---|---|---|
    | 503 | sin `LIBRAVIEW_WEBHOOK_SECRET` (o sin URL/token para bajar el informe) | reintenta |
    | 401 | la firma no verifica; **el mismo mensaje para todo** | queda fallido |
    | 422 | el JSON no trae lo necesario | queda fallido |
    | 404 | el número de acceso no es de un ítem de ese pedido | queda fallido, a la vista |
    | 502 | no se pudo bajar el informe o el PDF; no queda nada grabado | reintenta |
    | 200 | grabado, o ya estaba (`duplicado`) | listo |

    El orden importa: lo primero es el secreto, luego la firma, y recién con la firma buena se mira el contenido. Una respuesta no
    le dice a quien no está firmando nada sobre qué hay en esta instancia."""
    secreto = libraview.secreto_del_webhook()
    if not secreto or not libraview.configurado():
        raise HTTPException(503, "El webhook de LibraView no está configurado en esta instancia.")
    if not libraview.verificar_firma(secreto, cuerpo, request.headers.get("x-libraview-firma")):
        raise HTTPException(401, "Firma inválida.")
    try:
        aviso = json.loads(cuerpo)
    except ValueError:
        raise HTTPException(422, "El aviso no es un JSON.")
    try:
        resultado = asyncio.run(libraview.procesar_aviso(repo, aviso))
    except libraview.AvisoInvalido as exc:
        raise HTTPException(422, str(exc))
    except libraview.LibraViewNoDisponible as exc:
        _log.warning("aviso de LibraView sin procesar: %s", exc)
        raise HTTPException(502, "No se pudo bajar el informe de LibraView.")
    if resultado == libraview.DESCONOCIDO:
        raise HTTPException(404, "Ese estudio no es de un pedido de esta instancia.")
    return {"ok": True, "duplicado": resultado == libraview.DUPLICADO}
