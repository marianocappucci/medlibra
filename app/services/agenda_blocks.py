"""El bloque de agenda: cómo se arma la agenda de un profesional.

Pedido del humano (2026-08-22): *"la agenda del profesional se parametriza en un
consultorio, en un rango horario, en un día o días de la semana y se repite
hasta determinada fecha"*, más *"agregar duración de consulta"*.

## Qué agrega sobre la `Availability` de LibraGenda

`Availability` es `(profesional, día de la semana, 09:00, 19:00)` y **no tiene
ni consultorio ni vigencia**: una vez cargada vale para siempre. Un bloque suma
las tres cosas que faltaban:

| | `Availability` | Bloque |
|---|---|---|
| Dónde se atiende | — | **consultorio** |
| Hasta cuándo | para siempre | `valid_from` … `valid_to` |
| Cuánto dura un turno | de la prestación | **del bloque** (10 a 30 min) |
| Cómo se atiende | por turnos | por turnos **o por demanda espontánea** |

🔴 **No se toca el motor, y el bloque no se guarda como `Availability`.** Las
ventanas que el motor necesita se **derivan** del bloque para la fecha que se
está validando (`ventanas_vigentes`): así la vigencia por rango de fechas —que
`Availability` no sabe expresar— se resuelve antes de que el motor la vea, sin
enseñarle un concepto nuevo ni cortar versión del paquete.

⚠️ **Las horas son hora de pared de la sede**, igual que las ventanas semanales
y el horario de atención (ADR-028). La conversión a instante la hace
`AppointmentService`, no esto.

## Convive con la disponibilidad semanal que ya existía

Los bloques **se suman** a las `Availability` cargadas por
`/resources/{id}/availability`; no las reemplazan ni las migran. Las instancias
que hoy están andando —dev, la demo— tienen su jornada cargada por ese camino y
tienen que seguir dando turnos igual. La pantalla de Configuración nueva arma
bloques; el endpoint viejo sigue existiendo para lo que ya estaba.
"""
# 🔴 Las anotaciones se evalúan perezosamente y no al ejecutar cada `def`.
# Sin esto, `def vigentes(...) -> list[dict]` explota con "'function' object is
# not subscriptable": los repositorios de este proyecto tienen un método que se
# llama `list` (y acá hay además uno que se llama `set`), y dentro del cuerpo de
# la clase ese nombre tapa al builtin para todo lo que venga después.
from __future__ import annotations

from datetime import date, time, timedelta

from libragenda import Availability
from libragenda.sqlalchemy_repository import Base
from sqlalchemy import Date, ForeignKey, Integer, String, Time, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

#: Las duraciones que ofrece la pantalla. Cerrada y no un entero libre: el
#: pedido fue "poner 10, 15, 20, 25, 30 minutos", y una lista cerrada es lo que
#: hace que la grilla horaria tenga slots parejos. Un valor fuera de esto se
#: rechaza con 422 en vez de guardarse y romper la grilla más tarde.
DURACIONES = (10, 15, 20, 25, 30)

#: Cómo se atiende ese bloque.
#:
#: - `turnos`: cada paciente tiene su horario. Es lo de siempre.
#: - `espontanea`: por orden de llegada, sin horario asignado.
#:
#: 🔴 Un bloque `espontanea` **no genera ventana de disponibilidad**: si la
#: generara, se le podrían dar turnos con hora encima de una franja que
#: justamente no trabaja con horarios, y las dos formas se pisarían en la misma
#: media hora. La cola de llegada de esos bloques es un mecanismo aparte.
MODALIDADES = ("turnos", "espontanea")


class AgendaBlockRow(Base):
    __tablename__ = "agenda_blocks"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), index=True)
    consultorio_id: Mapped[str] = mapped_column(
        ForeignKey("consultorios.id"), index=True,
    )
    weekday: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time] = mapped_column(Time)
    valid_from: Mapped[date] = mapped_column(Date)
    #: `None` = sin fecha de fin, se repite indefinidamente.
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    slot_minutes: Mapped[int] = mapped_column(Integer)
    modality: Mapped[str] = mapped_column(String(20))


class AppointmentRoomRow(Base):
    """En qué consultorio ocurre un turno.

    Tabla aparte y no una columna del turno porque el turno lo modela
    LibraGenda: `Appointment` es un dataclass del motor y agregarle un campo
    sería cambiar el motor. Es el mismo patrón con el que `Patient` extiende al
    `Client` y `BranchContactRow` a la sede.

    Se llena al crear el turno, con el consultorio del bloque que lo cubre. Un
    turno dado sobre la disponibilidad semanal vieja —sin bloque— no tiene fila
    acá, y entonces no participa del choque de sala: no hay sala que declarar.
    """

    __tablename__ = "appointment_rooms"

    appointment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    consultorio_id: Mapped[str] = mapped_column(
        ForeignKey("consultorios.id"), index=True,
    )


def _to_dict(row: AgendaBlockRow) -> dict:
    return {
        "id": row.id, "resource_id": row.resource_id,
        "consultorio_id": row.consultorio_id, "weekday": row.weekday,
        "starts_at": row.starts_at, "ends_at": row.ends_at,
        "valid_from": row.valid_from, "valid_to": row.valid_to,
        "slot_minutes": row.slot_minutes, "modality": row.modality,
    }


def validar(
    weekday: int, starts_at: time, ends_at: time,
    valid_from: date, valid_to: date | None,
    slot_minutes: int, modality: str,
) -> None:
    """Lo que un bloque no puede ser. Levanta `ValueError` con el motivo.

    Se valida acá y no en el router para que el repositorio no dependa de que
    alguien haya pasado por la API: el seed de la demo y los tests construyen
    bloques por este mismo camino.
    """
    if not 0 <= weekday <= 6:
        raise ValueError("el día de la semana va de 0 (lunes) a 6 (domingo)")
    if starts_at >= ends_at:
        raise ValueError("el bloque tiene que terminar después de empezar")
    if valid_to is not None and valid_to < valid_from:
        raise ValueError("la fecha de fin no puede ser anterior a la de inicio")
    if slot_minutes not in DURACIONES:
        raise ValueError(
            f"la duración tiene que ser una de {', '.join(str(d) for d in DURACIONES)} minutos"
        )
    if modality not in MODALIDADES:
        raise ValueError(f"la modalidad tiene que ser {' o '.join(MODALIDADES)}")
    # 🔴 El bloque tiene que entrar al menos un turno entero. Con una franja de
    # 09:00 a 09:10 y turnos de 15 minutos, el bloque existe, se dibuja y la
    # ventana derivada rechaza absolutamente todo — una agenda que se ve
    # configurada y no da un solo turno.
    minutos = (
        ends_at.hour * 60 + ends_at.minute - starts_at.hour * 60 - starts_at.minute
    )
    if modality == "turnos" and minutos < slot_minutes:
        raise ValueError(
            f"el bloque dura {minutos} minutos y no entra un turno de {slot_minutes}"
        )


class AgendaBlockRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, id: str, **campos) -> dict:
        validar(
            campos["weekday"], campos["starts_at"], campos["ends_at"],
            campos["valid_from"], campos["valid_to"],
            campos["slot_minutes"], campos["modality"],
        )
        with self.session_factory.begin() as session:
            row = AgendaBlockRow(id=id, **campos)
            session.add(row)
            session.flush()
            return _to_dict(row)

    def get(self, block_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(AgendaBlockRow, block_id)
            return _to_dict(row) if row else None

    def list(self, resource_id: str | None = None) -> list[dict]:
        with self.session_factory() as session:
            consulta = select(AgendaBlockRow)
            if resource_id is not None:
                consulta = consulta.where(AgendaBlockRow.resource_id == resource_id)
            rows = session.scalars(
                consulta.order_by(AgendaBlockRow.weekday, AgendaBlockRow.starts_at)
            ).all()
            return [_to_dict(row) for row in rows]

    def update(self, block_id: str, **campos) -> dict:
        validar(
            campos["weekday"], campos["starts_at"], campos["ends_at"],
            campos["valid_from"], campos["valid_to"],
            campos["slot_minutes"], campos["modality"],
        )
        with self.session_factory.begin() as session:
            row = session.get(AgendaBlockRow, block_id)
            if row is None:
                raise KeyError(block_id)
            for campo, valor in campos.items():
                setattr(row, campo, valor)
            session.flush()
            return _to_dict(row)

    def delete(self, block_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(AgendaBlockRow, block_id)
            if row is None:
                raise KeyError(block_id)
            session.delete(row)

    # -- lo que consume el motor -------------------------------------------

    def vigentes(self, resource_id: str, dia: date) -> list[dict]:
        """Los bloques `turnos` de ese profesional que rigen ese día.

        Filtra por día de la semana **y** por vigencia: un bloque que venció el
        mes pasado sigue en la tabla —es el historial de cómo se atendía— y no
        tiene que dar turnos hoy.
        """
        with self.session_factory() as session:
            rows = session.scalars(
                select(AgendaBlockRow).where(
                    AgendaBlockRow.resource_id == resource_id,
                    AgendaBlockRow.weekday == dia.weekday(),
                    AgendaBlockRow.modality == "turnos",
                    AgendaBlockRow.valid_from <= dia,
                )
            ).all()
            return [
                _to_dict(row) for row in rows
                if row.valid_to is None or row.valid_to >= dia
            ]

    def ventanas_vigentes(self, resource_id: str, dia: date) -> list[Availability]:
        """Los bloques de ese día, con la forma que el motor entiende."""
        return [
            Availability(resource_id, b["weekday"], b["starts_at"], b["ends_at"])
            for b in self.vigentes(resource_id, dia)
        ]

    def cubre(
        self, resource_id: str, inicio_local, duracion: timedelta,
    ) -> dict | None:
        """El bloque que contiene ese rato, o `None`.

        Es lo que decide **la duración del turno y en qué consultorio ocurre**.
        Si hay más de uno —dos bloques del mismo profesional el mismo día en
        salas distintas—, gana el que empieza más temprano, que es el orden en
        que `vigentes()` los devuelve.
        """
        fin_local = inicio_local + duracion
        for b in self.vigentes(resource_id, inicio_local.date()):
            if b["starts_at"] <= inicio_local.time() and fin_local.time() <= b["ends_at"]:
                return b
        return None

    def duracion_de(self, resource_id: str, inicio_local) -> timedelta | None:
        """La duración que fija el bloque que empieza a cubrir ese horario.

        🔴 Se busca por el **inicio** y no por el rato completo, porque la
        duración es justamente lo que todavía no se sabe: preguntar
        `cubre(inicio, duracion)` para averiguar la duración sería circular.
        """
        for b in self.vigentes(resource_id, inicio_local.date()):
            if b["starts_at"] <= inicio_local.time() < b["ends_at"]:
                return timedelta(minutes=b["slot_minutes"])
        return None


class AppointmentRoomRepository:
    """Dónde ocurre cada turno, y qué turnos ocupan una sala."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def set(self, appointment_id: str, consultorio_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(AppointmentRoomRow, appointment_id)
            if row is None:
                session.add(AppointmentRoomRow(
                    appointment_id=appointment_id, consultorio_id=consultorio_id,
                ))
            else:
                row.consultorio_id = consultorio_id

    def get(self, appointment_id: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(AppointmentRoomRow, appointment_id)
            return row.consultorio_id if row else None

    def ids_en(self, consultorio_id: str) -> set[str]:
        """Los turnos asignados a esa sala."""
        with self.session_factory() as session:
            rows = session.scalars(
                select(AppointmentRoomRow.appointment_id).where(
                    AppointmentRoomRow.consultorio_id == consultorio_id,
                )
            ).all()
            return set(rows)

    def delete(self, appointment_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(AppointmentRoomRow, appointment_id)
            if row is not None:
                session.delete(row)
