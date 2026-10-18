"""El consultorio: la sala física donde se atiende.

🔴 **Por qué es una entidad y no un campo.** Hasta el 2026-08-23 lo único que
MedLibra sabía ocupar era el **profesional** (el `Resource` de LibraGenda), así
que la pregunta *"¿la Dra. Vidal y el Dr. Molina no están los dos en el
Consultorio 2 a las 10?"* no se podía ni formular: no había sala que colisionar.
Un consultorio tiene una capacidad de uno y es el recurso más escaso de una
clínica chica — dos agendas correctas por separado se pisan en la puerta.

🔴 **Un consultorio ES un `Resource` de LibraGenda, de recurso secundario**
(ADR-042, que corrige al ADR-030 de acá y se apoya en el ADR-009 y el ADR-016 del
motor). Hasta el 2026-10-17 esto decía lo contrario —*"un consultorio NO es un
`Resource`"*— y la sala se chequeaba en `AppointmentService`, **afuera** de la
transacción del motor: dos profesionales que reservaban a la vez veían los dos
la sala libre y entraban los dos. El motor ya sabe ocupar más de un recurso por
turno y trabarlos juntos; lo que le faltaba a la sala era existir como recurso.

Por eso cada consultorio son **dos filas, la misma identidad**:

- el `Resource` (`resources`), que es lo que el motor traba y compara: nombre,
  sede y `active` viven ahí también;
- la `ConsultorioRow` (`consultorios`), la extensión del vertical, con el mismo
  `id` — el patrón de `PatientRow` sobre `Client`.

`ConsultorioRepository` escribe las dos en la misma transacción, así que no hay
consultorio sin recurso. **El `Resource` de una sala no es un profesional**: los
dos listados que arman la agenda (`/resources` y `/agenda/catalogo`) lo sacan
con `ids()`.
"""
from libragenda.sqlalchemy_repository import Base, ResourceRow
from sqlalchemy import Boolean, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker


class ConsultorioRow(Base):
    __tablename__ = "consultorios"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    branch_id: Mapped[str | None] = mapped_column(
        ForeignKey("branches.id"), nullable=True, index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


def _to_dict(row: ConsultorioRow) -> dict:
    return {
        "id": row.id, "name": row.name,
        "branch_id": row.branch_id, "active": row.active,
    }


class ConsultorioRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(
        self, id: str, name: str, branch_id: str | None, active: bool,
    ) -> dict:
        with self.session_factory.begin() as session:
            # El recurso primero: es el que choca contra el id de un profesional
            # ya cargado, y entonces el `IntegrityError` sale antes de escribir
            # nada de la sala.
            session.add(ResourceRow(id=id, name=name, branch_id=branch_id, active=active))
            row = ConsultorioRow(
                id=id, name=name, branch_id=branch_id, active=active,
            )
            session.add(row)
            session.flush()
            return _to_dict(row)

    def get(self, consultorio_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(ConsultorioRow, consultorio_id)
            return _to_dict(row) if row else None

    def list(self) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ConsultorioRow).order_by(ConsultorioRow.name)
            ).all()
            return [_to_dict(row) for row in rows]

    def ids(self) -> set[str]:
        """Los ids de las salas: los `Resource` que **no** son profesionales."""
        with self.session_factory() as session:
            return set(session.scalars(select(ConsultorioRow.id)).all())

    def update(
        self, consultorio_id: str, name: str, branch_id: str | None, active: bool,
    ) -> dict:
        with self.session_factory.begin() as session:
            row = session.get(ConsultorioRow, consultorio_id)
            if row is None:
                raise KeyError(consultorio_id)
            row.name = name
            row.branch_id = branch_id
            row.active = active
            recurso = session.get(ResourceRow, consultorio_id)
            if recurso is not None:
                recurso.name = name
                recurso.branch_id = branch_id
                recurso.active = active
            session.flush()
            return _to_dict(row)

    def delete(self, consultorio_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ConsultorioRow, consultorio_id)
            if row is None:
                raise KeyError(consultorio_id)
            session.delete(row)
            # Con turnos colgando el `IntegrityError` sale de acá (el turno
            # referencia al recurso) o del bloque de agenda (referencia a la
            # sala): el router lo traduce igual.
            recurso = session.get(ResourceRow, consultorio_id)
            if recurso is not None:
                session.delete(recurso)
