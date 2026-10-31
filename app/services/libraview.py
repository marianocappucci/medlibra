"""La costura con LibraView, el RIS de imágenes: el pedido de estudio sale como orden y el informe vuelve como resultado.

Ver ADR-051 en `DECISIONS.md` y el contrato del otro lado en `docs/integraciones.md` de LibraView.

## Las dos mitades

**Ida.** Un pedido de estudios por imágenes se manda a LibraView con un botón (no es automático: no todo pedido es de imágenes, los
de laboratorio no van). Cada envío deja su fila en `envios_a_libraview`, con su estado, el error si lo hubo y **el cuerpo exacto que
se mandó**. Es el mismo criterio que `contalibra.py` (un fallo del otro lado no es invisible y se reintenta a mano), con una diferencia
que importa: Contalibra recalcula todo desde el turno al reintentar; acá se **reenvía el mismo cuerpo**. LibraView es idempotente por
`id_externo` y compara el contenido: el mismo cuerpo vuelve `200 repetida`, uno armado de nuevo con otro dato (el paciente cambió de
teléfono, se corrigió un apellido) vuelve `409`. El reintento no puede convertirse en un conflicto.

**Vuelta.** Cuando se publica un informe (o una adenda) LibraView avisa con un webhook firmado y **sin datos del paciente**: sólo ids.
El aviso no es el resultado: con el número de acceso se pide el informe y su PDF a LibraView, con la credencial de acá, y recién ahí
se graba. Que el aviso no lleve datos clínicos es una propiedad de LibraView que este código aprovecha: lo que llega por el aire
abierto no puede hacer decir a MedLibra nada que LibraView no confirme.

## Qué no se hace nunca

- **Seguir una URL que viene en el aviso.** El aviso trae `recursos` con rutas, y usarlas sería dejar que quien firme (o quien robe el
  secreto) elija a dónde sale un pedido con el token de LibraView. Las rutas se arman acá con `LIBRAVIEW_URL` + el `id_externo` y el
  `numero_acceso`, y esos dos se validan contra un alfabeto cerrado antes de entrar a una URL.
- **Grabar a medias.** El resultado, el documento con el PDF y la fila del evento (la deduplicación) entran en **una** transacción:
  o están los tres o ninguno. Un aviso que se procesó a medias y se reintenta duplicaría el resultado.
- **Contestar 2xx sin haber guardado.** Si LibraView no contesta el informe o el PDF el router devuelve 502 y LibraView reintenta
  (30 s … 24 h, 8 intentos).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import quote
from uuid import uuid4

import httpx
from libracore.fechas import ZONA_AR
from libragenda.sqlalchemy_repository import Base
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from .clinical_documents import ClinicalDocumentRow
from .study_orders import StudyOrderItemRow, StudyOrderRow, StudyResultRow

_log = logging.getLogger(__name__)

PENDIENTE = "pendiente"
ENVIADO = "enviado"
ERROR = "error"

#: Cuánto se espera a LibraView al mandar la orden. Corto, como el de Contalibra: quien manda está mirando la pantalla; si tarda
#: queda como error (o pendiente) y se reintenta, que es para lo que existe la fila.
TIMEOUT_SEGUNDOS = 10.0
#: Bajar el informe y el PDF es lo único que hace el webhook, y LibraView reintenta si no contestamos a tiempo: se puede esperar más.
TIMEOUT_INFORME_SEGUNDOS = 20.0
#: Tope del PDF del informe. Un informe de texto con una imagen clave pesa decenas de KB; 20 MB es el mismo tope que los documentos
#: clínicos que sube el personal (`routers/clinical_documents.py`).
MAX_PDF_BYTES = 20 * 1024 * 1024
#: La ventana en que una firma vale. Es la que documenta LibraView: el instante va dentro de lo firmado para que un cuerpo capturado
#: no se reenvíe una semana después.
TOLERANCIA_FIRMA_SEGUNDOS = 300

EVENTO_PUBLICADO = "informe.publicado"
EVENTO_ADENDA = "informe.adenda"
EVENTOS = (EVENTO_PUBLICADO, EVENTO_ADENDA)

#: Lo que `procesar_aviso` le cuenta al router.
PROCESADO = "procesado"
DUPLICADO = "duplicado"
DESCONOCIDO = "desconocido"

#: El `id_externo` y el número de acceso entran a una URL: sólo estos caracteres. Es el alfabeto de LibraView para el id externo
#: (letras, números y `. _ : @ + = -`); el número de acceso es más estrecho, pero aceptar de más acá es inofensivo porque además se
#: busca en la base: si no lo emitió LibraView para un pedido nuestro, no existe.
_SEGURO = re.compile(r"^[A-Za-z0-9._:@+=-]{1,100}$")


class LibraViewNoDisponible(RuntimeError):
    """LibraView no contestó, rechazó el pedido o contestó algo que no sirve. El router lo traduce a 502."""


class AvisoInvalido(ValueError):
    """El aviso (ya con la firma verificada) no trae lo necesario. El router lo traduce a 422."""


# ── Configuración ────────────────────────────────────────────────────────────


def destino() -> str:
    """La URL de LibraView, o `""` si esta instancia no la tiene."""
    return os.environ.get("LIBRAVIEW_URL", "").strip().rstrip("/")


def _token() -> str:
    return os.environ.get("LIBRAVIEW_TOKEN", "").strip()


def _secreto() -> str:
    return os.environ.get("LIBRAVIEW_WEBHOOK_SECRET", "").strip()


def configurado() -> bool:
    """El interruptor de todo el módulo: sin `LIBRAVIEW_URL` y `LIBRAVIEW_TOKEN` la integración está apagada y la pantalla no
    muestra nada. A diferencia de Contalibra (donde apagado es un estado a vigilar porque hay plata sin facturar), acá apagado es
    lo normal: la mayoría de las instancias no tienen un RIS."""
    return bool(destino() and _token())


def recibe_resultados() -> bool:
    """Si el webhook está listo: además de hablar con LibraView, tiene el secreto con el que verifica la firma."""
    return configurado() and bool(_secreto())


def secreto_del_webhook() -> str:
    return _secreto()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}


def _nuevo_cliente(timeout: float = TIMEOUT_SEGUNDOS) -> httpx.AsyncClient:
    """Un solo lugar donde se arma el cliente HTTP: los tests lo reemplazan por uno con `httpx.MockTransport`.

    Las redirecciones **no se siguen** (el default de httpx): una orden con el token de LibraView no tiene por qué ir a otro lado."""
    return httpx.AsyncClient(timeout=timeout)


# ── Modelos ──────────────────────────────────────────────────────────────────


class EnvioALibraViewRow(Base):
    __tablename__ = "envios_a_libraview"

    #: Un envío por pedido (la orden de LibraView es **una** con todas las prácticas del pedido).
    order_id: Mapped[str] = mapped_column(ForeignKey("study_orders.id"), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20), default=PENDIENTE, index=True)
    #: 🔴 El JSON exacto que se mandó (o se va a mandar). El reintento reenvía **éste**: ver el docstring del módulo.
    #: Lleva datos del paciente, así que no sale en el log de actividad (`COLUMNAS_CLINICAS`) ni en ninguna respuesta de la API.
    cuerpo: Mapped[str] = mapped_column(Text)
    #: El id de la orden del otro lado, cuando llegó.
    orden_libraview_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Lo que dijo LibraView si falló. Vacío cuando salió bien.
    error: Mapped[str] = mapped_column(String(500), default="")
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: Quién apretó el botón. Para el que reintenta: quién lo mandó la primera vez.
    enviado_por: Mapped[str] = mapped_column(String(200), default="")


class EstudioEnLibraViewRow(Base):
    """Un ítem del pedido y el número de acceso que le dio LibraView. Es el puente de la vuelta: el aviso trae el número de acceso
    y de acá sale a qué ítem (y a qué paciente) va el resultado."""

    __tablename__ = "estudios_en_libraview"

    item_id: Mapped[str] = mapped_column(ForeignKey("study_order_items.id"), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("study_orders.id"), index=True)
    codigo_practica: Mapped[str] = mapped_column(String(100))
    #: Nulo hasta que LibraView confirma la orden. Único cuando no es nulo: dos ítems no pueden ser el mismo estudio.
    numero_acceso: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)


class EventoDeLibraViewRow(Base):
    """Los avisos ya procesados: la deduplicación. LibraView entrega **al menos una vez**, así que el mismo `id_evento` puede llegar
    dos veces (un reintento tras un 2xx que se perdió); la fila entra en la misma transacción que el resultado."""

    __tablename__ = "eventos_de_libraview"

    id_evento: Mapped[str] = mapped_column(String(100), primary_key=True)
    evento: Mapped[str] = mapped_column(String(40))
    numero_acceso: Mapped[str] = mapped_column(String(64))
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: El resultado que generó el aviso. Sin FK: si alguien borra el resultado, el evento sigue contando como procesado (si no,
    #: el reintento de LibraView lo volvería a crear).
    result_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ── El cuerpo de la orden ────────────────────────────────────────────────────


def armar_cuerpo(
    *, order_id: str, codigos: list[str], creado: datetime, paciente: dict, medico_solicitante: str,
    matricula_solicitante: str | None = None, diagnostico_presuntivo: str | None = None,
    prioridad: str = "rutina",
) -> dict:
    """El JSON de `POST /api/integracion/v1/ordenes`.

    - `id_externo` es el **id del pedido** (no el del ítem): un pedido con varios estudios es **una** orden con varias prácticas.
    - `practicas` va en el orden de los ítems del pedido (`position`): LibraView devuelve los números de acceso en ese mismo orden y
      de ahí se emparejan.
    - `fecha_orden` es el día del pedido **en hora argentina**: un pedido de las 22:00 del 28 tiene fecha 28 aunque en UTC ya sea 29
      (y LibraView rechaza una fecha futura).
    - Las claves vacías se **omiten**: LibraView rechaza un campo desconocido, pero también valida el formato de los que llegan; un
      correo `""` no es un correo.
    """
    if creado.tzinfo is None:
        creado = creado.replace(tzinfo=UTC)
    nacimiento = paciente["fecha_nacimiento"]
    datos = {
        "tipo_documento": "DNI",
        "numero_documento": paciente["numero_documento"],
        "apellido": paciente["apellido"],
        "nombres": paciente["nombres"],
        "fecha_nacimiento": nacimiento.isoformat() if isinstance(nacimiento, date) else str(nacimiento),
        "sexo": paciente["sexo"],
        "telefono": paciente.get("telefono"),
        "email": paciente.get("email"),
    }
    cuerpo = {
        "id_externo": order_id,
        "paciente": _sin_vacios(datos),
        "medico_solicitante": medico_solicitante,
        "matricula_solicitante": matricula_solicitante,
        "diagnostico_presuntivo": diagnostico_presuntivo,
        "prioridad": prioridad,
        "fecha_orden": creado.astimezone(ZONA_AR).date().isoformat(),
        "practicas": list(codigos),
    }
    return _sin_vacios(cuerpo)


def _sin_vacios(datos: dict) -> dict:
    """Saca las claves con `None` o texto en blanco. Lo demás (una lista, un objeto) se deja como está."""
    return {k: v for k, v in datos.items() if v is not None and not (isinstance(v, str) and not v.strip())}


def serializar(cuerpo: dict) -> str:
    """El cuerpo como texto, tal cual se guarda y se reenvía."""
    return json.dumps(cuerpo, ensure_ascii=False, sort_keys=True)


# ── La firma del webhook ─────────────────────────────────────────────────────


def verificar_firma(
    secreto: str, cuerpo: bytes, cabecera: str | None, ahora: float | None = None,
    tolerancia: int = TOLERANCIA_FIRMA_SEGUNDOS,
) -> bool:
    """Si `cabecera` (`t=<unix>,v1=<hex>`) es la firma de `cuerpo` con `secreto` y no está vencida.

    HMAC-SHA256 de `f"{t}." + cuerpo`, sobre el cuerpo **crudo** (no el JSON vuelto a armar: cualquier espacio de diferencia cambia la
    firma). Compara en tiempo constante. Una cabecera mal formada es `False`, nunca una excepción: quien llama contesta lo mismo para
    todo (401) y no hay forma de distinguir «mal formada» de «mala» desde afuera.

    Se acepta una firma con instante **futuro** dentro de la misma ventana (relojes que no coinciden), y se ignoran las claves que no
    conoce (`v2=` el día que LibraView firme con otro esquema)."""
    if not secreto or not cabecera:
        return False
    try:
        campos = dict(pedazo.strip().split("=", 1) for pedazo in cabecera.split(","))
        instante = int(campos["t"])
        recibida = campos["v1"]
        esperado = hmac.new(
            secreto.encode("utf-8"), f"{instante}.".encode() + cuerpo, hashlib.sha256,
        ).hexdigest()
        # Como bytes: `compare_digest` con `str` revienta si alguno trae algo que no es ASCII.
        coincide = hmac.compare_digest(esperado.encode("ascii"), recibida.encode("utf-8"))
    except (KeyError, ValueError, TypeError, UnicodeError, OverflowError):
        return False
    ahora = time.time() if ahora is None else ahora
    return coincide and abs(ahora - instante) <= tolerancia


# ── Repositorio ──────────────────────────────────────────────────────────────


def _a_dict(row: EnvioALibraViewRow, estudios: list[EstudioEnLibraViewRow]) -> dict:
    """Lo que sale por la API. **Sin el cuerpo**: tiene el nombre, el documento y la fecha de nacimiento del paciente."""
    return {
        "order_id": row.order_id, "estado": row.estado, "error": row.error,
        "intentos": row.intentos, "actualizado": row.actualizado,
        "orden_libraview_id": row.orden_libraview_id,
        "items": [
            {"item_id": e.item_id, "codigo_practica": e.codigo_practica, "numero_acceso": e.numero_acceso}
            for e in estudios
        ],
    }


class EnvioRepository:
    def __init__(self, session_factory: sessionmaker[Session], documents_dir: str) -> None:
        self.session_factory = session_factory
        #: Donde se escribe el PDF del informe: el mismo `MEDLIBRA_DOCUMENTS_DIR` de los documentos clínicos.
        self.documents_dir = documents_dir

    # ── Ida ──

    def _estudios(self, session: Session, order_id: str) -> list[EstudioEnLibraViewRow]:
        """Los estudios del envío en el orden de los ítems del pedido."""
        return list(session.scalars(
            select(EstudioEnLibraViewRow)
            .join(StudyOrderItemRow, StudyOrderItemRow.id == EstudioEnLibraViewRow.item_id)
            .where(EstudioEnLibraViewRow.order_id == order_id)
            .order_by(StudyOrderItemRow.position)
        ))

    def get(self, order_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(EnvioALibraViewRow, order_id)
            return _a_dict(row, self._estudios(session, order_id)) if row else None

    def cuerpo(self, order_id: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(EnvioALibraViewRow, order_id)
            return row.cuerpo if row else None

    def listar_por_paciente(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            filas = session.scalars(
                select(EnvioALibraViewRow)
                .join(StudyOrderRow, StudyOrderRow.id == EnvioALibraViewRow.order_id)
                .where(StudyOrderRow.patient_id == patient_id)
                .order_by(EnvioALibraViewRow.actualizado.desc())
            ).all()
            return [_a_dict(fila, self._estudios(session, fila.order_id)) for fila in filas]

    def preparar(self, order_id: str, cuerpo: str, items: list[tuple[str, str]], enviado_por: str) -> dict:
        """Deja el envío `pendiente` con el cuerpo que se va a mandar, **antes** de mandarlo.

        Si el proceso se cae entre este paso y la respuesta, queda la fila `pendiente` con su cuerpo y se reintenta desde la pantalla,
        en vez de un pedido que "quizá salió". Si ya había un envío con error se pisa el cuerpo: es el camino para corregir un dato que
        LibraView rechazó (un envío `enviado` no llega acá: lo frena el router)."""
        with self.session_factory.begin() as session:
            row = session.get(EnvioALibraViewRow, order_id)
            if row is None:
                row = EnvioALibraViewRow(order_id=order_id, intentos=0)
                session.add(row)
            row.estado = PENDIENTE
            row.cuerpo = cuerpo
            row.orden_libraview_id = None
            row.error = ""
            row.enviado_por = (enviado_por or "")[:200]
            row.actualizado = datetime.now(UTC)
            for viejo in self._estudios(session, order_id):
                session.delete(viejo)
            session.flush()
            for item_id, codigo in items:
                session.add(EstudioEnLibraViewRow(item_id=item_id, order_id=order_id, codigo_practica=codigo))
            session.flush()
            return _a_dict(row, self._estudios(session, order_id))

    def registrar(
        self, order_id: str, estado: str, *, error: str = "", orden_libraview_id: int | None = None,
        numeros_de_acceso: list[str] | None = None,
    ) -> dict:
        """Anota cómo terminó un intento (suma uno). Con `numeros_de_acceso` los empareja **por posición** con los ítems del pedido,
        que es como los devuelve LibraView."""
        with self.session_factory.begin() as session:
            row = session.get(EnvioALibraViewRow, order_id)
            row.estado = estado
            row.orden_libraview_id = orden_libraview_id
            # Se recorta y no se deja crecer: el detalle completo ya está en el log y esto se muestra en pantalla.
            row.error = (error or "")[:500]
            row.intentos = (row.intentos or 0) + 1
            row.actualizado = datetime.now(UTC)
            estudios = self._estudios(session, order_id)
            if numeros_de_acceso is not None:
                for estudio, numero in zip(estudios, numeros_de_acceso, strict=True):
                    estudio.numero_acceso = numero
            session.flush()
            return _a_dict(row, estudios)

    # ── Vuelta ──

    def ya_procesado(self, id_evento: str) -> bool:
        with self.session_factory() as session:
            return session.get(EventoDeLibraViewRow, id_evento) is not None

    def estudio_por_acceso(self, numero_acceso: str, order_id: str) -> dict | None:
        """El ítem al que va un número de acceso, **si es de ese pedido**. Un número que existe pero es de otro pedido es tan
        desconocido como uno inexistente: el aviso y la base tienen que coincidir."""
        with self.session_factory() as session:
            fila = session.execute(
                select(EstudioEnLibraViewRow, StudyOrderRow.patient_id)
                .join(StudyOrderRow, StudyOrderRow.id == EstudioEnLibraViewRow.order_id)
                .where(
                    EstudioEnLibraViewRow.numero_acceso == numero_acceso,
                    EstudioEnLibraViewRow.order_id == order_id,
                )
            ).first()
            if fila is None:
                return None
            estudio, patient_id = fila
            return {
                "item_id": estudio.item_id, "order_id": estudio.order_id, "patient_id": patient_id,
                "codigo_practica": estudio.codigo_practica,
            }

    def grabar_informe(
        self, *, estudio: dict, id_evento: str, evento: str, numero_acceso: str, autor: str, texto: str,
        titulo: str, nombre_pdf: str, pdf: bytes | None,
    ) -> str:
        """El resultado, el documento con el PDF y la fila del evento, en **una** transacción. Devuelve `PROCESADO` o `DUPLICADO`.

        El archivo se escribe **antes** (el documento necesita su nombre en disco) con el mismo esquema que
        `ClinicalDocumentRepository.create` —un UUID más la extensión, nunca un nombre que venga de afuera— y se borra si la
        transacción no se confirma. Una carrera en el PK del evento (dos entregas a la vez del mismo aviso) pierde la segunda: es un
        duplicado, no un error."""
        guardado = None
        if pdf is not None:
            guardado = f"{uuid4()}.pdf"
            os.makedirs(self.documents_dir, exist_ok=True)
            with open(os.path.join(self.documents_dir, guardado), "wb") as archivo:
                archivo.write(pdf)
        ahora = datetime.now(UTC)
        try:
            with self.session_factory.begin() as session:
                resultado = StudyResultRow(
                    id=str(uuid4()), item_id=estudio["item_id"], author=autor, created_at=ahora, text=texto,
                )
                session.add(resultado)
                if pdf is not None:
                    session.add(ClinicalDocumentRow(
                        id=str(uuid4()), patient_id=estudio["patient_id"], author=autor, created_at=ahora,
                        title=titulo[:300], description=None, original_filename=nombre_pdf,
                        stored_filename=guardado, content_type="application/pdf", size_bytes=len(pdf),
                    ))
                session.add(EventoDeLibraViewRow(
                    id_evento=id_evento, evento=evento, numero_acceso=numero_acceso, recibido_en=ahora,
                    result_id=resultado.id,
                ))
                session.flush()
        except BaseException as exc:
            self._borrar_archivo(guardado)
            # Una carrera: el evento ya lo grabó otra entrega. Cualquier otro `IntegrityError` (una FK, un largo) es un error de verdad.
            if isinstance(exc, IntegrityError) and self.ya_procesado(id_evento):
                return DUPLICADO
            raise
        return PROCESADO

    def _borrar_archivo(self, guardado: str | None) -> None:
        if guardado is None:
            return
        try:
            os.remove(os.path.join(self.documents_dir, guardado))
        except FileNotFoundError:
            pass


# ── Hablar con LibraView ─────────────────────────────────────────────────────


def _detalle(respuesta: httpx.Response) -> str:
    """Lo accionable de una respuesta de error: el `detail` de FastAPI si lo hay (un texto, o la lista de campos que no validaron),
    y si no el principio del cuerpo."""
    try:
        detalle = respuesta.json().get("detail")
    except (ValueError, AttributeError):
        detalle = None
    if isinstance(detalle, str):
        return detalle
    if isinstance(detalle, list):
        partes = []
        for item in detalle:
            if isinstance(item, dict):
                donde = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                partes.append(f"{donde}: {item.get('msg')}" if donde else str(item.get("msg")))
            else:
                partes.append(str(item))
        return "; ".join(partes)
    return respuesta.text[:300]


def _mensaje_de_error(respuesta: httpx.Response) -> str:
    """`"<status>: <detalle>"`, con un texto propio para lo que la persona puede resolver."""
    estado = respuesta.status_code
    if estado in (401, 403):
        return f"{estado}: LibraView rechazó la credencial (revisá LIBRAVIEW_TOKEN)."
    if estado == 409:
        return f"{estado}: LibraView ya tiene otra orden con este id."
    return f"{estado}: {_detalle(respuesta)}"


async def enviar(repo: EnvioRepository, order_id: str) -> dict:
    """Manda el cuerpo guardado del envío y anota cómo salió. Nunca levanta por un fallo del otro lado: queda en `error`.

    Si responde `2xx` guarda el id de la orden de LibraView y el número de acceso de cada ítem. `repetida: true` (reenviar el mismo
    cuerpo) es un éxito igual: el envío anterior había llegado y se perdió la respuesta. Siempre suma un intento."""
    cuerpo = repo.cuerpo(order_id)
    if cuerpo is None:
        raise KeyError(order_id)
    if not configurado():
        return repo.registrar(order_id, ERROR, error="LIBRAVIEW_URL y LIBRAVIEW_TOKEN no están configuradas.")
    try:
        async with _nuevo_cliente() as cliente:
            respuesta = await cliente.post(
                f"{destino()}/api/integracion/v1/ordenes",
                content=cuerpo.encode("utf-8"),
                headers={**_headers(), "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        _log.warning("LibraView no contestó al mandar el pedido %s: %r", order_id, exc)
        return repo.registrar(order_id, ERROR, error=f"No se pudo hablar con LibraView ({type(exc).__name__}).")
    if respuesta.status_code >= 300:
        # Redirecciones incluidas: no se siguen, y una 3xx no es una orden creada.
        return repo.registrar(order_id, ERROR, error=_mensaje_de_error(respuesta))
    try:
        datos = respuesta.json()
        numeros = [str(e["numero_acceso"]) for e in datos["estudios"]]
        orden_id = datos.get("orden_id")
        pedidos = len(json.loads(cuerpo)["practicas"])
    except (ValueError, KeyError, TypeError):
        return repo.registrar(order_id, ERROR, error=f"{respuesta.status_code}: LibraView contestó algo que no se entiende.")
    if len(numeros) != pedidos:
        # La orden existe del otro lado, pero no se puede emparejar: mejor un error visible que números de acceso corridos.
        return repo.registrar(
            order_id, ERROR,
            error=f"LibraView devolvió {len(numeros)} estudios y se pidieron {pedidos}.",
        )
    try:
        return repo.registrar(
            order_id, ENVIADO, orden_libraview_id=orden_id if isinstance(orden_id, int) else None,
            numeros_de_acceso=numeros,
        )
    except IntegrityError:
        # El número de acceso es único: que ya lo tenga otro ítem es un dato que no puede ser.
        return repo.registrar(order_id, ERROR, error="LibraView devolvió un número de acceso que ya está en uso.")


async def practicas() -> list[dict]:
    """El catálogo de prácticas de LibraView. Levanta `LibraViewNoDisponible` si no se pudo."""
    if not configurado():
        raise LibraViewNoDisponible("LibraView no está configurado.")
    try:
        async with _nuevo_cliente() as cliente:
            respuesta = await cliente.get(f"{destino()}/api/integracion/v1/practicas", headers=_headers())
    except httpx.HTTPError as exc:
        raise LibraViewNoDisponible(f"No se pudo hablar con LibraView ({type(exc).__name__}).") from exc
    if respuesta.status_code != 200:
        raise LibraViewNoDisponible(_mensaje_de_error(respuesta))
    try:
        catalogo = respuesta.json()
        if not isinstance(catalogo, list):
            raise ValueError
        return [{
            "codigo": str(p["codigo"]), "nombre": str(p.get("nombre") or p["codigo"]),
            "modalidad": p.get("modalidad"), "codigo_nomenclador": p.get("codigo_nomenclador"),
            "preparacion": p.get("preparacion"),
        } for p in catalogo]
    except (ValueError, KeyError, TypeError) as exc:
        raise LibraViewNoDisponible("LibraView devolvió un catálogo que no se entiende.") from exc


# ── El aviso ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Aviso:
    id_evento: str
    evento: str
    id_externo: str
    numero_acceso: str
    adendas: int


def _leer_aviso(evento: dict) -> _Aviso:
    """Valida lo mínimo del aviso. Un aviso firmado pero sin lo necesario es un 422: reintentarlo no lo arregla."""
    if not isinstance(evento, dict):
        raise AvisoInvalido("El aviso no es un objeto.")
    campos = {}
    for nombre in ("id_evento", "evento", "id_externo", "numero_acceso"):
        valor = evento.get(nombre)
        if not isinstance(valor, str) or not _SEGURO.match(valor):
            raise AvisoInvalido(f"El aviso no trae un {nombre} válido.")
        campos[nombre] = valor
    if campos["evento"] not in EVENTOS:
        raise AvisoInvalido(f"Evento desconocido: {campos['evento'][:40]}.")
    adendas = evento.get("adendas", 0)
    if isinstance(adendas, bool) or not isinstance(adendas, int) or adendas < 0:
        raise AvisoInvalido("El aviso no trae una cantidad de adendas válida.")
    return _Aviso(adendas=adendas, **campos)


async def _bajar_informe(aviso: _Aviso) -> dict:
    """`GET .../informe`. La URL se arma acá: nunca se usa una que venga en el aviso."""
    url = (
        f"{destino()}/api/integracion/v1/ordenes/{quote(aviso.id_externo, safe='')}"
        f"/estudios/{quote(aviso.numero_acceso, safe='')}/informe"
    )
    try:
        async with _nuevo_cliente(TIMEOUT_INFORME_SEGUNDOS) as cliente:
            respuesta = await cliente.get(url, headers=_headers())
    except httpx.HTTPError as exc:
        raise LibraViewNoDisponible(f"No se pudo bajar el informe ({type(exc).__name__}).") from exc
    if respuesta.status_code != 200:
        raise LibraViewNoDisponible(f"No se pudo bajar el informe: {_mensaje_de_error(respuesta)}")
    try:
        informe = respuesta.json()
    except ValueError as exc:
        raise LibraViewNoDisponible("El informe de LibraView no es un JSON.") from exc
    if not isinstance(informe, dict):
        raise LibraViewNoDisponible("El informe de LibraView no se entiende.")
    return informe


async def _bajar_pdf(aviso: _Aviso) -> bytes | None:
    """`GET .../informe.pdf`, con tope de tamaño. Devuelve `None` si pasa del tope (el resultado igual se graba, sin el archivo)."""
    url = (
        f"{destino()}/api/integracion/v1/ordenes/{quote(aviso.id_externo, safe='')}"
        f"/estudios/{quote(aviso.numero_acceso, safe='')}/informe.pdf"
    )
    try:
        async with _nuevo_cliente(TIMEOUT_INFORME_SEGUNDOS) as cliente:
            async with cliente.stream("GET", url, headers=_headers()) as respuesta:
                if respuesta.status_code != 200:
                    await respuesta.aread()
                    raise LibraViewNoDisponible(f"No se pudo bajar el PDF: {_mensaje_de_error(respuesta)}")
                declarado = respuesta.headers.get("content-length", "")
                if declarado.isdigit() and int(declarado) > MAX_PDF_BYTES:
                    return None
                contenido = bytearray()
                async for trozo in respuesta.aiter_bytes():
                    contenido += trozo
                    if len(contenido) > MAX_PDF_BYTES:
                        return None
    except httpx.HTTPError as exc:
        raise LibraViewNoDisponible(f"No se pudo bajar el PDF ({type(exc).__name__}).") from exc
    if not contenido.startswith(b"%PDF"):
        raise LibraViewNoDisponible("El PDF de LibraView no es un PDF.")
    return bytes(contenido)


def _autor(firmado_por: object) -> str:
    """`"<firmado_por> (LibraView)"`, o `"LibraView"` si no viene. Que diga de dónde vino: el resultado no lo cargó nadie de acá."""
    nombre = firmado_por.strip() if isinstance(firmado_por, str) else ""
    return f"{nombre[:170]} (LibraView)" if nombre else "LibraView"


async def procesar_aviso(repo: EnvioRepository, evento: dict) -> str:
    """Un aviso de LibraView ya verificado (la firma la mira el router) → `PROCESADO`, `DUPLICADO` o `DESCONOCIDO`.

    - **Duplicado**: el `id_evento` ya se procesó. No hace nada y el router contesta 200: LibraView entrega al menos una vez.
    - **Desconocido**: el número de acceso no es de un ítem de ese pedido. El router contesta 404, que en LibraView queda visible
      como fallido (un aviso de una orden que MedLibra no mandó, o de otra instancia con el mismo cliente, merece que alguien lo vea).
    - Si LibraView no contesta el informe o el PDF levanta `LibraViewNoDisponible` (502: LibraView reintenta) y **no queda nada
      grabado**.
    - `AvisoInvalido` si el aviso no trae lo necesario (422).

    Una adenda es **un resultado más** (los resultados ya son append-only): la número `adendas` de la lista (1-based; la última si no
    coincide), con su autor."""
    aviso = _leer_aviso(evento)
    if repo.ya_procesado(aviso.id_evento):
        return DUPLICADO
    estudio = repo.estudio_por_acceso(aviso.numero_acceso, aviso.id_externo)
    if estudio is None:
        return DESCONOCIDO

    informe = await _bajar_informe(aviso)
    titulo = f"Informe de {estudio['codigo_practica']} — N.º de acceso {aviso.numero_acceso}"
    nombre_pdf = f"informe-{aviso.numero_acceso}.pdf"
    if aviso.evento == EVENTO_PUBLICADO:
        texto = informe.get("texto")
        autor = _autor(informe.get("firmado_por"))
    else:
        adendas = informe.get("adendas")
        if not isinstance(adendas, list) or not adendas or not isinstance(adendas[-1], dict):
            raise LibraViewNoDisponible("LibraView no devolvió la adenda del aviso.")
        # La número N del aviso (1-based); si no coincide con lo que hay, la última, que es la que acaba de publicarse.
        numero = aviso.adendas if 1 <= aviso.adendas <= len(adendas) else len(adendas)
        adenda = adendas[numero - 1]
        texto = adenda.get("texto")
        autor = _autor(adenda.get("firmado_por"))
        if isinstance(texto, str):
            texto = f"Adenda {numero}: {texto}"
        titulo += f" (adenda {numero})"
        nombre_pdf = f"informe-{aviso.numero_acceso}-adenda-{numero}.pdf"
    if not isinstance(texto, str) or not texto.strip():
        raise LibraViewNoDisponible("El informe de LibraView no trae texto.")

    pdf = await _bajar_pdf(aviso)
    if pdf is None:
        _log.warning(
            "el PDF del informe %s pasa de %d bytes: se graba el resultado sin el documento",
            aviso.numero_acceso, MAX_PDF_BYTES,
        )
    return repo.grabar_informe(
        estudio=estudio, id_evento=aviso.id_evento, evento=aviso.evento, numero_acceso=aviso.numero_acceso,
        autor=autor, texto=texto, titulo=titulo, nombre_pdf=nombre_pdf, pdf=pdf,
    )
