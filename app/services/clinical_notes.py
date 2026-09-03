"""Historia clínica básica: free-text evolution notes per patient.

Append-only by design -- there is no update endpoint/method. Clinical
records shouldn't be silently rewritten after the fact; only creation and
(admin-only, for genuine data-entry mistakes) deletion are exposed.
Structured diagnoses, recetas, estudios and consentimientos are Fase 2
(see ROADMAP.md), out of scope here.
"""
from datetime import UTC, datetime, timezone
from uuid import uuid4

from libragenda.sqlalchemy_repository import Base
from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker


class ClinicalNoteRow(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)


def _to_dict(row: ClinicalNoteRow) -> dict:
    return {
        "id": row.id, "patient_id": row.patient_id,
        "created_at": row.created_at, "author": row.author, "text": row.text,
    }


class ClinicalNoteRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, patient_id: str, author: str, text: str) -> dict:
        row = ClinicalNoteRow(
            id=str(uuid4()), patient_id=patient_id,
            created_at=datetime.now(UTC), author=author, text=text,
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return _to_dict(row)

    def get(self, note_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(ClinicalNoteRow, note_id)
            return _to_dict(row) if row else None

    def list_by_patient(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ClinicalNoteRow)
                .where(ClinicalNoteRow.patient_id == patient_id)
                .order_by(ClinicalNoteRow.created_at)
            ).all()
            return [_to_dict(row) for row in rows]

    def delete(self, note_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ClinicalNoteRow, note_id)
            if row is None:
                raise KeyError(note_id)
            session.delete(row)
