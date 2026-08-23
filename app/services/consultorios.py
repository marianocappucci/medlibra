"""El consultorio: la sala física donde se atiende.

🔴 **Por qué es una entidad y no un campo.** Hasta el 2026-08-23 lo único que
MedLibra sabía ocupar era el **profesional** (el `Resource` de LibraGenda), así
que la pregunta *"¿la Dra. Vidal y el Dr. Molina no están los dos en el
Consultorio 2 a las 10?"* no se podía ni formular: no había sala que colisionar.
Un consultorio tiene una capacidad de uno y es el recurso más escaso de una
clínica chica — dos agendas correctas por separado se pisan en la puerta.

**Un consultorio NO es un `Resource` de LibraGenda**, aunque se le parezca. El
motor asocia un turno a *un solo* recurso y busca choques sobre él
(`find_conflicts`); modelar la sala como un segundo `Resource` obligaría a un
turno a ocupar dos, que es justo lo que el motor no hace. La sala vive acá y su
choque lo valida `AppointmentService` — el reparto que fija LibraGenda es que el
vertical resuelve lo que el motor no modela, en vez de deformar el motor.
"""
from sqlalchemy import Boolean, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base


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
            session.flush()
            return _to_dict(row)

    def delete(self, consultorio_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ConsultorioRow, consultorio_id)
            if row is None:
                raise KeyError(consultorio_id)
            session.delete(row)
