"""La cola por orden de llegada de un bloque de demanda espontánea.

Pedido del humano (2026-08-22): *"posibilidad de armar la agenda por turnos o
por demanda espontánea"*, y al preguntarle qué significaba operativamente
eligió **sin horario: orden de llegada**.

## Por qué esto NO es un turno de LibraGenda

Un `Appointment` del motor **es** un horario: tiene `starts_at` y una duración,
y todas sus reglas —choques, ventanas de disponibilidad, bloqueos— se calculan
sobre ese rato. Una demanda espontánea no tiene rato: tiene una **posición en
una fila**. Meterla en el motor obligaría a inventarle un horario falso, y ese
horario mentiroso después chocaría contra los turnos de verdad, ocuparía la
sala y aparecería en la grilla horaria como si alguien tuviera reservada esa
media hora.

Por eso vive en su propia tabla y no pasa por el `InMemoryScheduler`. Lo que sí
comparte con un turno es de dónde cuelga: **un bloque de agenda**, con su
profesional, su consultorio y su vigencia (ver `agenda_blocks.py`).

## El orden de llegada es histórico

`arrival_order` se asigna al registrar la llegada y **no se renumera nunca**.
Cancelar al tercero de la fila no convierte al cuarto en tercero: el orden dice
en qué momento llegó cada uno, y reescribirlo borraría el único dato que la
cola tiene. Quién sigue se calcula filtrando por estado, no por el número.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timezone

from libragenda.sqlalchemy_repository import Base
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

#: Los estados de alguien en la fila.
#:
#: Deliberadamente **más chicos que los de un turno**: acá no hay `pending` ni
#: `confirmed` —quien está en la fila ya llegó, no hay nada que confirmar— ni
#: `no_show`, que es justamente lo que la demanda espontánea no puede tener.
ESPERANDO = "waiting"
EN_ATENCION = "in_progress"
ATENDIDO = "completed"
CANCELADO = "cancelled"

#: Qué transición admite cada estado. Un `dict` y no un `if` encadenado para que
#: la regla se pueda leer entera de un vistazo, igual que la máquina de estados
#: del turno en el motor.
TRANSICIONES = {
    ESPERANDO: {EN_ATENCION, CANCELADO},
    EN_ATENCION: {ATENDIDO, CANCELADO},
    ATENDIDO: set(),
    CANCELADO: set(),
}

#: Los que todavía ocupan lugar en la fila.
ACTIVOS = (ESPERANDO, EN_ATENCION)


class WalkinRow(Base):
    __tablename__ = "walkins"
    __table_args__ = (
        # 🔴 Dos llegadas simultáneas no pueden compartir número. Sin esto, el
        # `max + 1` de `registrar()` es una condición de carrera que deja dos
        # pacientes en la misma posición y nadie se entera: la fila se ve bien
        # y el orden entre esos dos queda librado a cómo los devuelva la base.
        UniqueConstraint("block_id", "day", "arrival_order", name="uq_walkins_orden"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("agenda_blocks.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    arrival_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=ESPERANDO)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransicionInvalida(Exception):
    """De este estado no se puede pasar a ése."""


def _to_dict(row: WalkinRow) -> dict:
    return {
        "id": row.id, "block_id": row.block_id, "day": row.day,
        "client_id": row.client_id, "service_id": row.service_id,
        "arrival_order": row.arrival_order, "status": row.status,
        "created_at": row.created_at,
    }


class WalkinRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def registrar(
        self, id: str, block_id: str, dia: date, client_id: str, service_id: str,
    ) -> dict:
        """Anota una llegada al final de la fila de ese bloque, ese día."""
        with self.session_factory.begin() as session:
            # El máximo incluye a los cancelados a propósito: el número dice el
            # orden en que se llegó, y reusar el de alguien que se fue haría que
            # dos personas distintas hayan sido "la tercera" del mismo día.
            ultimo = session.scalar(
                select(func.max(WalkinRow.arrival_order)).where(
                    WalkinRow.block_id == block_id, WalkinRow.day == dia,
                )
            )
            row = WalkinRow(
                id=id, block_id=block_id, day=dia, client_id=client_id,
                service_id=service_id, arrival_order=(ultimo or 0) + 1,
                status=ESPERANDO, created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return _to_dict(row)

    def get(self, walkin_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(WalkinRow, walkin_id)
            return _to_dict(row) if row else None

    def cola(self, block_id: str, dia: date, solo_activos: bool = False) -> list[dict]:
        """La fila de ese bloque ese día, en orden de llegada."""
        with self.session_factory() as session:
            consulta = select(WalkinRow).where(
                WalkinRow.block_id == block_id, WalkinRow.day == dia,
            )
            if solo_activos:
                consulta = consulta.where(WalkinRow.status.in_(ACTIVOS))
            rows = session.scalars(
                consulta.order_by(WalkinRow.arrival_order)
            ).all()
            return [_to_dict(row) for row in rows]

    def cambiar_estado(self, walkin_id: str, nuevo: str) -> dict:
        with self.session_factory.begin() as session:
            row = session.get(WalkinRow, walkin_id)
            if row is None:
                raise KeyError(walkin_id)
            if nuevo not in TRANSICIONES.get(row.status, set()):
                raise TransicionInvalida(f"{row.status} -> {nuevo}")
            row.status = nuevo
            session.flush()
            return _to_dict(row)
