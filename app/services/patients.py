"""Patient: MedLibra's own clinical extension of LibraGenda's generic Client.

Every patient is a LibraGenda Client (id, name, phone, email, active) plus
two clinical fields MedLibra owns directly: DNI and fecha de nacimiento.
Not part of LibraGenda's domain -- clinical identity belongs to the
vertical, same principle as "users" being Gestiolibra's own table instead
of living in the engine.
"""
from datetime import date

from sqlalchemy import Date, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda import Client
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base

from .clinical_documents import ClinicalDocumentRow
from .clinical_notes import ClinicalNoteRow
from .consents import ConsentRow
from .prescriptions import PrescriptionRow
from .study_orders import StudyOrderRow


class PatientRow(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    dni: Mapped[str | None] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class PatientHasClinicalNotes(Exception):
    """Raised on delete() when the patient still has historia clínica,
    recetas, pedidos de estudios, documentos clínicos o consentimientos.

    Deleting the patient would either violate a FK (PostgreSQL) or silently
    orphan the records (SQLite, no FK enforcement by default) -- neither is
    acceptable for medical records. The caller must be explicit about what
    happens to the notes/prescriptions/study orders/documents/consents
    first; there's no cascade here.
    """


class PatientRepository:
    """Coordinates LibraGenda's Client (identity/scheduling) with MedLibra's
    own clinical extension row -- two tables, kept in step at the API
    boundary rather than merged into one, so LibraGenda's schema stays
    untouched by vertical-specific fields."""

    def __init__(
        self, catalog: SqlAlchemyCatalogRepository, session_factory: sessionmaker[Session],
    ) -> None:
        self.catalog = catalog
        self.session_factory = session_factory

    def create(
        self, id: str, name: str, phone: str | None, email: str | None, active: bool,
        dni: str | None, birth_date: date | None,
    ) -> dict:
        client = Client(id, name, phone, email, active)
        self.catalog.add_client(client)  # raises IntegrityError on duplicate id
        with self.session_factory.begin() as session:
            session.add(PatientRow(id=id, dni=dni, birth_date=birth_date))
        return self._to_out(client, dni, birth_date)

    def get(self, patient_id: str) -> dict | None:
        client = self.catalog.get_client(patient_id)
        if client is None:
            return None
        return self._to_out(client, *self._extension(patient_id))

    def list(self) -> list[dict]:
        with self.session_factory() as session:
            extensions = {row.id: row for row in session.scalars(select(PatientRow)).all()}
        return [
            self._to_out(
                client,
                extensions[client.id].dni if client.id in extensions else None,
                extensions[client.id].birth_date if client.id in extensions else None,
            )
            for client in self.catalog.list_clients()
        ]

    def update(
        self, patient_id: str, name: str, phone: str | None, email: str | None, active: bool,
        dni: str | None, birth_date: date | None,
    ) -> dict:
        client = Client(patient_id, name, phone, email, active)
        self.catalog.update_client(patient_id, client)  # raises KeyError if missing
        with self.session_factory.begin() as session:
            row = session.get(PatientRow, patient_id)
            if row is None:
                row = PatientRow(id=patient_id)
                session.add(row)
            row.dni, row.birth_date = dni, birth_date
        return self._to_out(client, dni, birth_date)

    def delete(self, patient_id: str) -> None:
        with self.session_factory() as session:
            has_notes = session.scalar(
                select(ClinicalNoteRow.id).where(ClinicalNoteRow.patient_id == patient_id).limit(1)
            ) is not None
            has_prescriptions = session.scalar(
                select(PrescriptionRow.id).where(PrescriptionRow.patient_id == patient_id).limit(1)
            ) is not None
            has_study_orders = session.scalar(
                select(StudyOrderRow.id).where(StudyOrderRow.patient_id == patient_id).limit(1)
            ) is not None
            has_documents = session.scalar(
                select(ClinicalDocumentRow.id).where(ClinicalDocumentRow.patient_id == patient_id).limit(1)
            ) is not None
            has_consents = session.scalar(
                select(ConsentRow.id).where(ConsentRow.patient_id == patient_id).limit(1)
            ) is not None
        if has_notes or has_prescriptions or has_study_orders or has_documents or has_consents:
            raise PatientHasClinicalNotes(patient_id)
        # Borrar primero la extension (PatientRow.id tiene FK a clients.id):
        # borrar el Client antes violaria esa FK en Postgres real -- en
        # SQLite pasaba desapercibido porque no fuerza FKs por default.
        with self.session_factory.begin() as session:
            row = session.get(PatientRow, patient_id)
            if row is not None:
                session.delete(row)
        self.catalog.delete_client(patient_id)  # raises KeyError if missing

    def _extension(self, patient_id: str) -> tuple[str | None, date | None]:
        with self.session_factory() as session:
            row = session.get(PatientRow, patient_id)
            return (row.dni, row.birth_date) if row else (None, None)

    @staticmethod
    def _to_out(client: Client, dni: str | None, birth_date: date | None) -> dict:
        return {
            "id": client.id, "name": client.name, "phone": client.phone,
            "email": client.email, "active": client.active,
            "dni": dni, "birth_date": birth_date,
        }
