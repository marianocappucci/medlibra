"""Consentimientos informados por paciente: registro de que se otorgo
consentimiento para un procedimiento, quien lo autorizo (el paciente o un
tutor/responsable) y el detalle acordado en texto libre.

Append-only por diseno, mismo criterio que clinical_notes: sin endpoint
de actualizacion. Un consentimiento es un hecho historico -- si el
paciente retira su consentimiento mas adelante, se carga un registro
nuevo que lo deja constancia, nunca se edita el original. Sin archivo
adjunto embebido: si hace falta el PDF firmado escaneado, se sube aparte
como documento clinico (/patients/{id}/documents, ya construido).
"""
from datetime import UTC, datetime, timezone
from uuid import uuid4

from libragenda.sqlalchemy_repository import Base
from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker


class ConsentRow(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))
    procedure: Mapped[str] = mapped_column(String(300))
    granted_by: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)


def _to_dict(row: ConsentRow) -> dict:
    return {
        "id": row.id, "patient_id": row.patient_id,
        "created_at": row.created_at, "author": row.author,
        "procedure": row.procedure, "granted_by": row.granted_by, "text": row.text,
    }


class ConsentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, patient_id: str, author: str, procedure: str, granted_by: str, text: str) -> dict:
        row = ConsentRow(
            id=str(uuid4()), patient_id=patient_id, author=author,
            created_at=datetime.now(UTC),
            procedure=procedure, granted_by=granted_by, text=text,
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return _to_dict(row)

    def get(self, consent_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(ConsentRow, consent_id)
            return _to_dict(row) if row else None

    def list_by_patient(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ConsentRow)
                .where(ConsentRow.patient_id == patient_id)
                .order_by(ConsentRow.created_at)
            ).all()
            return [_to_dict(row) for row in rows]

    def delete(self, consent_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ConsentRow, consent_id)
            if row is None:
                raise KeyError(consent_id)
            session.delete(row)
