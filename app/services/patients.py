"""Patient: MedLibra's own clinical extension of LibraGenda's generic Client.

Every patient is a LibraGenda Client (id, name, phone, email, active) plus
two clinical fields MedLibra owns directly: DNI and fecha de nacimiento.
Not part of LibraGenda's domain -- clinical identity belongs to the
vertical, same principle as "users" being Gestiolibra's own table instead
of living in the engine.
"""
import re
from datetime import UTC, date, datetime, timezone

from libragenda import Client
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

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
    cuit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    condicion_iva: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PatientSequenceRow(Base):
    """El contador del número de paciente: una fila por serie (hoy sólo `patient`).

    Es una tabla y no un `max(id) + 1` por una razón: con el máximo, borrar al último
    paciente devuelve su número, y el siguiente alta hereda un id que todavía puede
    estar en un turno, una factura o un mensaje viejo. El contador sólo avanza.
    """
    __tablename__ = "patient_sequences"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    last: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


#: La serie de los números de paciente.
SERIE_PACIENTE = "patient"
#: `p-001`, `p-002`... el formato de los pacientes de la demo (`scripts/seed_demo.py`).
#: Pasa de `p-999` a `p-1000` sin truncar.
PREFIJO_ID = "p-"
_ID_GENERADO = re.compile(rf"^{re.escape(PREFIJO_ID)}(\d+)$")
#: Cuántos números ocupados a mano (un `p-007` escrito por una persona) se saltea
#: antes de rendirse. Cada intento consume un número, así que no es un bucle abierto.
INTENTOS_DE_ID = 50


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
        self, id: str | None, name: str, phone: str | None, email: str | None, active: bool,
        dni: str | None, birth_date: date | None,
        cuit: str | None = None, condicion_iva: str | None = None,
    ) -> dict:
        """Con `id` lo respeta (y un duplicado levanta `IntegrityError`, como siempre);
        sin `id` (`None`) genera el próximo número de la serie."""
        if id is None:
            client = self._add_with_next_number(name, phone, email, active)
            id = client.id
        else:
            client = Client(id, name, phone, email, active)
            self.catalog.add_client(client)  # raises IntegrityError on duplicate id
        with self.session_factory.begin() as session:
            session.add(PatientRow(
                id=id, dni=dni, birth_date=birth_date, cuit=cuit, condicion_iva=condicion_iva,
                created_at=datetime.now(UTC),
            ))
        return self._to_out(client, dni, birth_date, cuit, condicion_iva)

    def _add_with_next_number(
        self, name: str, phone: str | None, email: str | None, active: bool,
    ) -> Client:
        """Da de alta el cliente con el próximo `p-NNN` libre.

        El número sale de `_next_number()`, que es atómico, así que dos altas
        simultáneas nunca reciben el mismo. Si el id ya está ocupado es porque alguien
        lo escribió a mano (`p-007`): se toma el siguiente en vez de fallar el alta.
        """
        for _ in range(INTENTOS_DE_ID):
            client = Client(f"{PREFIJO_ID}{self._next_number():03d}", name, phone, email, active)
            try:
                self.catalog.add_client(client)
            except IntegrityError:
                continue
            return client
        raise IntegrityError("no hay un número de paciente libre", None, Exception())

    def _next_number(self) -> int:
        """Avanza el contador y devuelve el número, en una sola sentencia.

        `UPDATE ... SET last = last + 1 RETURNING last` toma el candado de la fila: una
        segunda transacción espera a la primera y recibe el número siguiente, no el mismo.
        Un `SELECT` seguido de un `UPDATE` dejaría la carrera entre los dos pasos.
        """
        paso = update(PatientSequenceRow).where(PatientSequenceRow.name == SERIE_PACIENTE).values(
            last=PatientSequenceRow.last + 1,
        ).returning(PatientSequenceRow.last)
        for _ in range(2):
            with self.session_factory.begin() as session:
                numero = session.scalar(paso)
            if numero is not None:
                return numero
            self._start_sequence()
        raise RuntimeError("no se pudo iniciar la serie de números de paciente")

    def _start_sequence(self) -> None:
        """Crea el contador la primera vez, partiendo del `p-NNN` más alto que ya exista.

        Sin esto, una instancia con `p-001..p-040` empezaría en 1 y cada alta saltearía
        a ciegas 40 ids ocupados. Si dos altas llegan juntas, una de las dos pierde la
        inserción (`IntegrityError`) y usa la fila de la otra.
        """
        with self.session_factory() as session:
            usados = [int(m.group(1)) for i in session.scalars(select(PatientRow.id))
                      if (m := _ID_GENERADO.match(i))]
        try:
            with self.session_factory.begin() as session:
                session.add(PatientSequenceRow(name=SERIE_PACIENTE, last=max(usados, default=0)))
        except IntegrityError:
            pass  # otra alta la creó entre medio

    def count_active(self) -> int:
        return sum(1 for client in self.catalog.list_clients() if client.active)

    def count_created_between(self, date_from: datetime, date_to: datetime) -> int:
        """Cantidad de pacientes dados de alta en el rango -- para el
        dashboard. Pacientes preexistentes a esta feature no tienen
        `created_at` (columna agregada después, sin backfill) y quedan
        fuera de cualquier rango, nunca cuentan como "nuevos"."""
        with self.session_factory() as session:
            return session.scalar(
                select(func.count(PatientRow.id)).where(
                    PatientRow.created_at.is_not(None),
                    PatientRow.created_at >= date_from,
                    PatientRow.created_at <= date_to,
                )
            ) or 0

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
                extensions[client.id].cuit if client.id in extensions else None,
                extensions[client.id].condicion_iva if client.id in extensions else None,
            )
            for client in self.catalog.list_clients()
        ]

    def update(
        self, patient_id: str, name: str, phone: str | None, email: str | None, active: bool,
        dni: str | None, birth_date: date | None,
        cuit: str | None = None, condicion_iva: str | None = None,
    ) -> dict:
        client = Client(patient_id, name, phone, email, active)
        self.catalog.update_client(patient_id, client)  # raises KeyError if missing
        with self.session_factory.begin() as session:
            row = session.get(PatientRow, patient_id)
            if row is None:
                row = PatientRow(id=patient_id)
                session.add(row)
            row.dni, row.birth_date = dni, birth_date
            row.cuit, row.condicion_iva = cuit, condicion_iva
        return self._to_out(client, dni, birth_date, cuit, condicion_iva)

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

    def _extension(
        self, patient_id: str
    ) -> tuple[str | None, date | None, str | None, str | None]:
        with self.session_factory() as session:
            row = session.get(PatientRow, patient_id)
            return (row.dni, row.birth_date, row.cuit, row.condicion_iva) if row else (
                None, None, None, None,
            )

    @staticmethod
    def _to_out(
        client: Client, dni: str | None, birth_date: date | None,
        cuit: str | None = None, condicion_iva: str | None = None,
    ) -> dict:
        return {
            "id": client.id, "name": client.name, "phone": client.phone,
            "email": client.email, "active": client.active,
            "dni": dni, "birth_date": birth_date,
            "cuit": cuit, "condicion_iva": condicion_iva,
        }
