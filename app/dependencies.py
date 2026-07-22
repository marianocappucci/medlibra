"""FastAPI dependency providers reading shared state off the app instance."""

from fastapi import Request

from libragenda.catalog_repository import SqlAlchemyCatalogRepository

from .services.appointments import AppointmentService
from .services.clinical_notes import ClinicalNoteRepository
from .services.patients import PatientRepository


def get_catalog_repository(request: Request) -> SqlAlchemyCatalogRepository:
    return request.app.state.catalog


def get_appointment_service(request: Request) -> AppointmentService:
    return request.app.state.appointment_service


def get_patient_repository(request: Request) -> PatientRepository:
    return request.app.state.patients


def get_clinical_note_repository(request: Request) -> ClinicalNoteRepository:
    return request.app.state.clinical_notes
