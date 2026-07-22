"""Recetas: prescripciones medicas por paciente.

Una receta tiene uno o mas items (medicamento, dosis, indicaciones) --
refleja como se prescribe en la practica real, una consulta suele generar
una receta con varios farmacos. Append-only por diseno, mismo criterio que
`clinical_notes`: sin endpoint de actualizacion, solo crear/listar/obtener/
borrar (el borrado pensado para corregir errores de carga, no para editar
contenido ya recetado).
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from libragenda.sqlalchemy_repository import Base


class PrescriptionRow(Base):
    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))

    items: Mapped[list["PrescriptionItemRow"]] = relationship(
        back_populates="prescription", order_by="PrescriptionItemRow.position",
        cascade="all, delete-orphan",
    )


class PrescriptionItemRow(Base):
    __tablename__ = "prescription_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    prescription_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"), index=True)
    # Orden de carga dentro de la receta -- el id es un UUID, no sirve para
    # ordenar (no es secuencial), así que se guarda la posición explícita.
    position: Mapped[int] = mapped_column(Integer)
    medication: Mapped[str] = mapped_column(String(200))
    dosage: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    prescription: Mapped[PrescriptionRow] = relationship(back_populates="items")


def _to_dict(row: PrescriptionRow) -> dict:
    return {
        "id": row.id, "patient_id": row.patient_id,
        "created_at": row.created_at, "author": row.author,
        "items": [
            {
                "id": item.id, "medication": item.medication,
                "dosage": item.dosage, "instructions": item.instructions,
            }
            for item in row.items
        ],
    }


class PrescriptionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, patient_id: str, author: str, items: list[dict]) -> dict:
        if not items:
            raise ValueError("a prescription needs at least one item")
        row = PrescriptionRow(
            id=str(uuid4()), patient_id=patient_id, author=author,
            created_at=datetime.now(timezone.utc),
            items=[
                PrescriptionItemRow(
                    id=str(uuid4()), position=position, medication=item["medication"],
                    dosage=item["dosage"], instructions=item.get("instructions"),
                )
                for position, item in enumerate(items)
            ],
        )
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _to_dict(row)
        return result

    def get(self, prescription_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(PrescriptionRow, prescription_id)
            return _to_dict(row) if row else None

    def list_by_patient(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(PrescriptionRow)
                .where(PrescriptionRow.patient_id == patient_id)
                .order_by(PrescriptionRow.created_at)
            ).all()
            return [_to_dict(row) for row in rows]

    def delete(self, prescription_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(PrescriptionRow, prescription_id)
            if row is None:
                raise KeyError(prescription_id)
            session.delete(row)
