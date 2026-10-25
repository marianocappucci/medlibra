"""Atender un turno en un nodo sin conexión, y el envío a ContaLibra desde el central (ADR-045).

Decisiones del humano (2026-10-21 y 2026-10-25): en el consultorio sin internet **la agenda es de sólo consulta**
—no se dan, mueven ni cancelan turnos—, pero un turno ya dado se puede marcar **en curso**, **atendido** o **«no vino»**,
y lo cobrado cuenta. Si en la web se lo canceló o se lo movió mientras tanto, **la atención vale** y el turno queda
**«a revisar»**. El modelo es de LibraGenda (`libragenda.atencion_en_nodo`, ADR-019); este módulo es lo propio de MedLibra.

## En el nodo

`atender` deja la fila propia del nodo (`agenda_node_attendances`) y encola `turno.atendido`, en una sola transacción.
La agenda muestra el turno con la atención encima del espejo (`marcas_de_agenda`). Al **completar**, `extra` lleva
`consulta`: lo que hay que mandar a ContaLibra, calculado con **las mismas funciones que la web** (`precio_del_turno`,
`pagos_del_turno`, la alícuota de la prestación) sobre el espejo de los precios, las señas y los módulos:

    extra = {"consulta": {"importe": "1000.00", "pagos": [{"medio", "monto", "referencia"}], "medio_del_saldo",
                          "iva_rate": "0.0000" | None, "descripcion": <prestación>, "fecha": "2026-10-25"}}

La plata viaja como **texto** (LibraGenda lo pide: `extra` es JSON). Sin precio o sin el módulo de facturación del plan, no
hay `consulta` y no se manda nada, igual que en la web (completar el turno nunca se bloquea por el plan).

## En el central: el envío a ContaLibra, una sola vez

El nodo **no** llama a ContaLibra: no guarda `CONTALIBRA_SERVICE_TOKEN` y no hay dos envíos posibles, uno de la PC y otro
del central. Al aplicar `turno.atendido`, LibraGenda llama a `al_aplicar` **en la misma transacción** y **sólo la primera
vez**, también cuando el turno quedó a revisar (*«lo cobrado se conserva siempre»*). Ahí se anota la fila de
`envios_a_contalibra` en `pendiente`; **después de confirmar**, `enviar_pendiente` la reclama y manda. Lo que garantiza
que no salgan dos:

1. LibraGenda llama a `al_aplicar` una sola vez por atención (la `atencion_id` es la clave de idempotencia);
2. la fila de `envios_a_contalibra` es una por turno (`appointment_id` es la clave): si la web ya mandó esa consulta, o ya
   está anotada, `ON CONFLICT DO NOTHING` no anota otra, y el turno queda a revisar con `ya_atendido`;
3. `enviar_pendiente` reclama la fila con un `UPDATE ... WHERE estado = 'pendiente' AND intentos = 0`: dos entregas a la
   vez, una sola gana;
4. ContaLibra es idempotente por `(sistema, referencia)`: aunque se cortara entre mandar y anotar la respuesta, reintentar
   desde `/facturacion-externa` devuelve la misma venta.

Un fallo del envío **no rompe** la aplicación de la atención: queda `error` en `/facturacion-externa` con su botón de
reintentar, como en la web. Sin `CONTALIBRA_URL` queda `sin_destino`, como en la web. Si el proceso muere entre confirmar y
mandar, la fila queda `pendiente` con un intento y se ve y se reintenta ahí; y si la operación se entrega otra vez, se
manda desde ese punto.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from libragenda import atencion_en_nodo
from libragenda.database import get_session_factory
from libragenda.domain import AppointmentStatus
from libragenda.sqlalchemy_repository import (
    AppliedAttendanceRow,
    AppointmentRow,
    BranchRow,
    ClientRow,
    ResourceRow,
    ServiceRow,
)
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import contalibra

logger = logging.getLogger(__name__)

TIPO_TURNO_ATENDIDO = atencion_en_nodo.TIPO_TURNO_ATENDIDO


def en_un_nodo() -> bool:
    return atencion_en_nodo.en_un_nodo()


# ── En el nodo: atender ──────────────────────────────────────────────────────


def _texto_decimal(valor: Any) -> str:
    return format(Decimal(str(valor)), "f")


def consulta_a_enviar(
    turno, precio: Mapping, sena, sena_pagada: bool, medio_del_saldo: str, iva_rate: Decimal | None,
) -> dict:
    """Lo que el central va a mandar a ContaLibra de este turno. Mismo cálculo que `complete_appointment` en la web, con
    la plata como texto."""
    importe = precio["price"]
    pagos = contalibra.pagos_del_turno(importe, sena, sena_pagada, medio_del_saldo)
    return {
        "importe": _texto_decimal(importe),
        "pagos": [
            {"medio": p["medio"], "monto": _texto_decimal(p["monto"]), "referencia": p.get("referencia", "")}
            for p in pagos
        ],
        "medio_del_saldo": medio_del_saldo,
        "iva_rate": None if iva_rate is None else _texto_decimal(iva_rate),
        "descripcion": turno.service_id,
        "fecha": turno.starts_at.date().isoformat(),
    }


def atender(turno_id: str, estado: AppointmentStatus, *, actor: str | None, consulta: Mapping | None = None):
    """Atiende el turno en el nodo: la fila propia y `turno.atendido` en una sola transacción. Con `consulta`, el central
    la manda a ContaLibra al aplicarla.

    Levanta lo de LibraGenda: `AppointmentNotFound`, `InvalidTransition` (el estado efectivo no permite el paso, o se
    atendió a la vez desde otro lado)."""
    extra = {"consulta": dict(consulta)} if consulta else None
    with get_session_factory().begin() as sesion:
        return atencion_en_nodo.atender_en_nodo(sesion, turno_id, estado, actor=actor, extra=extra)


# ── En el nodo y en el central: lo que se ve en la agenda ────────────────────


def marcas_de_agenda(turno_ids: list[str]) -> dict[str, dict]:
    """Por turno: `{"estado": <el efectivo o None>, "atendido_en_la_pc": bool, "a_revisar": bool, "motivo": str | None}`.

    - **Atendido en la PC**: el turno tiene una atención propia del nodo que todavía no subió (no figura en
      `agenda_applied_attendances`, que baja por el espejo). Mientras tanto la agenda lo muestra con **el estado de esa
      atención**, encima del que trae el espejo. Una vez aplicada, manda el turno del central.
    - **A revisar**: el turno tiene una atención aplicada que chocó con la web y nadie revisó. Vale en las dos puntas.

    Sólo trae los turnos con alguna marca; el resto no aparece."""
    if not turno_ids:
        return {}
    marcas: dict[str, dict] = {}
    with get_session_factory()() as sesion:
        if en_un_nodo():
            del_nodo = atencion_en_nodo.atenciones_del_nodo(sesion, turno_ids)
            aplicadas = set(sesion.scalars(
                select(AppliedAttendanceRow.atencion_id).where(
                    AppliedAttendanceRow.atencion_id.in_([a.id for a in del_nodo.values()])
                )
            )) if del_nodo else set()
            for turno_id, atencion in del_nodo.items():
                if atencion.id not in aplicadas:
                    marcas[turno_id] = {
                        "estado": atencion.estado.value, "atendido_en_la_pc": True, "a_revisar": False, "motivo": None,
                    }
        filas = sesion.scalars(
            select(AppliedAttendanceRow)
            .where(
                AppliedAttendanceRow.appointment_id.in_(turno_ids),
                AppliedAttendanceRow.resultado == atencion_en_nodo.RESULTADO_A_REVISAR,
                AppliedAttendanceRow.reviewed_at.is_(None),
            )
            .order_by(AppliedAttendanceRow.at, AppliedAttendanceRow.atencion_id)
        )
        for fila in filas:
            marca = marcas.setdefault(fila.appointment_id, {
                "estado": None, "atendido_en_la_pc": False, "a_revisar": False, "motivo": None,
            })
            marca["a_revisar"], marca["motivo"] = True, fila.motivo   # la más nueva manda
    return marcas


def turnos_a_revisar() -> list[dict]:
    """Las atenciones de nodo que chocaron con la web y nadie revisó, con los nombres que la pantalla necesita. Los
    nombres de cada fila son los de `AtencionAplicada` de LibraGenda (lo que espera `libra-ui/TurnosARevisar`)."""
    with get_session_factory()() as sesion:
        filas = atencion_en_nodo.turnos_a_revisar(sesion)
        ids = {f.appointment_id for f in filas}
        turnos = {t.id: t for t in sesion.scalars(select(AppointmentRow).where(AppointmentRow.id.in_(ids)))} if ids else {}
        pacientes = {
            c.id: c.name for c in sesion.scalars(
                select(ClientRow).where(ClientRow.id.in_({t.client_id for t in turnos.values()}))
            )
        } if turnos else {}
        servicios = {
            s.id: s.name for s in sesion.scalars(
                select(ServiceRow).where(ServiceRow.id.in_({t.service_id for t in turnos.values()}))
            )
        } if turnos else {}
        # El huso de la sede del profesional: la hora del turno se muestra en la hora de la SEDE, no en la del navegador (ADR-028).
        sedes_de = {
            r.id: r.branch_id for r in sesion.scalars(
                select(ResourceRow).where(ResourceRow.id.in_({t.resource_id for t in turnos.values()}))
            )
        } if turnos else {}
        husos = {b.id: b.timezone for b in sesion.scalars(select(BranchRow))} if turnos else {}
    salida = []
    for fila in filas:
        turno = turnos.get(fila.appointment_id)
        salida.append({
            "atencion_id": fila.atencion_id,
            "appointment_id": fila.appointment_id,
            "estado": fila.estado.value,
            "at": fila.at,
            "actor": fila.actor,
            "motivo": fila.motivo,
            "estado_despues": fila.estado_despues.value if fila.estado_despues else None,
            "resultado": fila.resultado,
            "revisada_at": fila.revisada_at,
            "paciente": pacientes.get(turno.client_id) if turno else None,
            "servicio": servicios.get(turno.service_id) if turno else None,
            "starts_at": turno.starts_at if turno else None,
            "zona": (husos.get(sedes_de.get(turno.resource_id)) or "UTC") if turno else None,
        })
    return salida


def marcar_revisadas(atencion_ids: list[str], por: str | None) -> int:
    """Saca de la lista «a revisar» las atenciones (quedan registradas, con quién y cuándo). Es del central: en el nodo la
    tabla es del espejo y la guarda la rechaza. Devuelve cuántas."""
    with get_session_factory().begin() as sesion:
        for atencion_id in atencion_ids:
            atencion_en_nodo.marcar_revisada(sesion, atencion_id, por=por)
    return len(atencion_ids)


# ── En el central: aplicar y mandar a ContaLibra ─────────────────────────────


def al_aplicar(sesion, atencion) -> None:
    """El gancho de `aplicar_turno_atendido` (una vez por atención, en su transacción, también si quedó a revisar): si
    completó un turno con `consulta`, anota el envío a ContaLibra como `pendiente` (o `sin_destino` si esta instancia no
    tiene `CONTALIBRA_URL`, igual que la web). **No manda nada acá**: es una transacción de base."""
    if atencion.estado is not AppointmentStatus.COMPLETED:
        return
    consulta = (atencion.extra or {}).get("consulta")
    if not consulta:
        return
    medio = (consulta.get("medio_del_saldo") or "efectivo")[:40]
    if contalibra.destino():
        estado, error, intentos = contalibra.PENDIENTE, "", 0
    else:
        estado, error, intentos = (
            contalibra.SIN_DESTINO, "CONTALIBRA_URL no está configurada: la consulta no se facturó.", 1,
        )
    # Una fila por turno: si ya hay una (la web lo mandó, o es otra atención del mismo turno) no se anota otra y no sale
    # un segundo envío. El turno queda a revisar (`ya_atendido`) para que lo mire una persona.
    sesion.execute(
        pg_insert(contalibra.EnvioAContalibraRow.__table__)
        .values(
            appointment_id=atencion.appointment_id, estado=estado, venta_id=None, error=error, intentos=intentos,
            actualizado=datetime.now(UTC), medio_del_saldo=medio,
        )
        .on_conflict_do_nothing(index_elements=["appointment_id"])
    )


def _consulta_de(sesion, turno_id: str) -> tuple[Mapping | None, str | None]:
    """La `consulta` de la última atención completada de ese turno, y el paciente del turno (si el turno existe)."""
    atenciones = sesion.scalars(
        select(AppliedAttendanceRow)
        .where(
            AppliedAttendanceRow.appointment_id == turno_id,
            AppliedAttendanceRow.status == AppointmentStatus.COMPLETED.value,
        )
        .order_by(AppliedAttendanceRow.applied_at.desc())
    )
    consulta = next(((a.extra or {}).get("consulta") for a in atenciones if (a.extra or {}).get("consulta")), None)
    return consulta, sesion.scalar(select(AppointmentRow.client_id).where(AppointmentRow.id == turno_id))


def enviar_pendiente(turno_id: str) -> dict | None:
    """Manda a ContaLibra la consulta de ese turno **si está `pendiente` y nadie la reclamó**; devuelve la fila de
    `envios_a_contalibra` o `None` si no había nada que mandar. **Nunca levanta**: un fallo queda anotado como `error`.

    Se llama **después de confirmar** la aplicación (ver el docstring del módulo): nunca con la transacción abierta."""
    from libragenda.catalog_repository import SqlAlchemyCatalogRepository

    from .patients import PatientRepository

    try:
        sessions = get_session_factory()
        envios = contalibra.EnvioRepository(sessions)
        with sessions.begin() as sesion:
            reclamada = sesion.execute(
                update(contalibra.EnvioAContalibraRow)
                .where(
                    contalibra.EnvioAContalibraRow.appointment_id == turno_id,
                    contalibra.EnvioAContalibraRow.estado == contalibra.PENDIENTE,
                    contalibra.EnvioAContalibraRow.intentos == 0,
                )
                .values(intentos=1, actualizado=datetime.now(UTC))
                .returning(contalibra.EnvioAContalibraRow.appointment_id)
            ).first()
            if reclamada is None:
                return None
            consulta, cliente_id = _consulta_de(sesion, turno_id)
        medio = (consulta or {}).get("medio_del_saldo")
        if not consulta:
            return envios.registrar(
                turno_id, contalibra.ERROR, error="la atención no trae los datos de la consulta",
                sumar_intento=False,
            )
        paciente = PatientRepository(SqlAlchemyCatalogRepository(sessions), sessions).get(cliente_id) if cliente_id else None
        try:
            respuesta = asyncio.run(contalibra.enviar_consulta(
                appointment_id=turno_id,
                fecha=consulta["fecha"],
                descripcion=consulta["descripcion"],
                importe=Decimal(consulta["importe"]),
                pagos=[
                    {"medio": p["medio"], "monto": Decimal(p["monto"]), "referencia": p.get("referencia", "")}
                    for p in consulta["pagos"]
                ],
                paciente=paciente or {},
                iva_rate=None if consulta.get("iva_rate") is None else Decimal(consulta["iva_rate"]),
            ))
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se registra igual, como en la web
            logger.exception("No se pudo mandar la consulta %s a ContaLibra", turno_id)
            return envios.registrar(
                turno_id, contalibra.ERROR, error=str(exc), medio_del_saldo=medio, sumar_intento=False,
            )
        venta = (respuesta or {}).get("venta") or {}
        return envios.registrar(
            turno_id, contalibra.ENVIADO, venta_id=venta.get("id"), medio_del_saldo=medio, sumar_intento=False,
        )
    except Exception:  # noqa: BLE001 - un fallo acá no puede rechazar una atención que ya se aplicó
        logger.exception("No se pudo ni reclamar el envío de la consulta %s a ContaLibra", turno_id)
        return None


def aplicadores() -> dict[str, Any]:
    """`{operation_type: (conexion, operacion) -> None}` de `turno.atendido`, para el despachador del central.

    Es el de LibraGenda (en su propia sesión, que confirma al salir: seguro porque el aplicador es idempotente) con el
    gancho `al_aplicar` de arriba, y **después** de confirmar, el envío a ContaLibra. Va también cuando la operación se
    entrega otra vez: si el proceso murió entre confirmar y mandar, ahí se manda (`enviar_pendiente` no repite)."""
    base = atencion_en_nodo.aplicadores(al_aplicar=al_aplicar)[TIPO_TURNO_ATENDIDO]

    def aplicar(conexion, operacion) -> None:
        base(conexion, operacion)
        turno_id = (operacion.payload or {}).get("turno_id")
        if isinstance(turno_id, str):
            enviar_pendiente(turno_id)

    return {TIPO_TURNO_ATENDIDO: aplicar}


def registrar_en(despachador):
    """Registra `turno.atendido` en un `libraedge.sync.despacho.Despachador` y lo devuelve. Registrar dos veces el tipo
    falla al arrancar (regla del `Despachador`)."""
    for tipo, manejador in aplicadores().items():
        despachador.registrar(tipo, atencion_en_nodo.SCHEMA_VERSION, manejador)
    return despachador
