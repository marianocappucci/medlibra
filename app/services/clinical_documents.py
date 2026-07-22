"""Documentos clinicos: archivos adjuntos por paciente (informes externos,
estudios escaneados, cualquier PDF/imagen que traiga el paciente).

Almacenamiento en filesystem local bajo un directorio persistente
(`MEDLIBRA_DOCUMENTS_DIR`), mismo patron ya probado en Contalibra/Restolibra
(`web/routers/config.py`: directorio dedicado + `open(...,"wb")`, sin sumar
una dependencia de infraestructura nueva como S3/MinIO). El nombre de
archivo en disco es un UUID normalizado (nunca el nombre original del
usuario) para evitar path traversal y colisiones; el nombre original se
guarda como metadata para mostrarlo/descargarlo con su nombre real.

Un documento se vincula solo al paciente -- no a un registro puntual
(nota, receta, pedido de estudio) -- decision explicita del usuario.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base


class ClinicalDocumentRow(Base):
    __tablename__ = "clinical_documents"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    stored_filename: Mapped[str] = mapped_column(String(300), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)


def _to_dict(row: ClinicalDocumentRow) -> dict:
    return {
        "id": row.id, "patient_id": row.patient_id,
        "created_at": row.created_at, "author": row.author,
        "title": row.title, "description": row.description,
        "original_filename": row.original_filename,
        "content_type": row.content_type, "size_bytes": row.size_bytes,
    }


class ClinicalDocumentRepository:
    def __init__(self, session_factory: sessionmaker[Session], documents_dir: str) -> None:
        self.session_factory = session_factory
        self.documents_dir = documents_dir

    def create(
        self, patient_id: str, author: str, title: str, description: str | None,
        original_filename: str, content_type: str | None, content: bytes,
    ) -> dict:
        ext = os.path.splitext(original_filename)[1].lower()
        stored_filename = f"{uuid4()}{ext}"
        os.makedirs(self.documents_dir, exist_ok=True)
        with open(os.path.join(self.documents_dir, stored_filename), "wb") as f:
            f.write(content)
        row = ClinicalDocumentRow(
            id=str(uuid4()), patient_id=patient_id, author=author,
            created_at=datetime.now(timezone.utc), title=title, description=description,
            original_filename=original_filename, stored_filename=stored_filename,
            content_type=content_type, size_bytes=len(content),
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return _to_dict(row)

    def get(self, document_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(ClinicalDocumentRow, document_id)
            return _to_dict(row) if row else None

    def get_file_path(self, document_id: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(ClinicalDocumentRow, document_id)
            if row is None:
                return None
            return os.path.join(self.documents_dir, row.stored_filename)

    def list_by_patient(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ClinicalDocumentRow)
                .where(ClinicalDocumentRow.patient_id == patient_id)
                .order_by(ClinicalDocumentRow.created_at)
            ).all()
            return [_to_dict(row) for row in rows]

    def delete(self, document_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ClinicalDocumentRow, document_id)
            if row is None:
                raise KeyError(document_id)
            stored_filename = row.stored_filename
            session.delete(row)
        try:
            os.remove(os.path.join(self.documents_dir, stored_filename))
        except FileNotFoundError:
            pass
