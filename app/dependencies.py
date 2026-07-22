"""FastAPI dependency providers reading shared state off the app instance."""

from fastapi import Request

from libragenda import DepositManager, ReminderDispatcher
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.repositories import DepositRepository

from .services.appointments import AppointmentService
from .services.branch_hours import BranchHoursRepository
from .services.branches import BranchRepository
from .services.business_settings import BusinessSettingsRepository
from .services.clinical_documents import ClinicalDocumentRepository
from .services.clinical_notes import ClinicalNoteRepository
from .services.consents import ConsentRepository
from .services.patients import PatientRepository
from .services.prescriptions import PrescriptionRepository
from .services.service_prices import ServicePriceRepository
from .services.study_orders import StudyOrderRepository
from .services.users import UserRepository


def get_catalog_repository(request: Request) -> SqlAlchemyCatalogRepository:
    return request.app.state.catalog


def get_availability_repository(request: Request) -> SqlAlchemyAvailabilityRepository:
    return request.app.state.availability


def get_appointment_service(request: Request) -> AppointmentService:
    return request.app.state.appointment_service


def get_patient_repository(request: Request) -> PatientRepository:
    return request.app.state.patients


def get_clinical_note_repository(request: Request) -> ClinicalNoteRepository:
    return request.app.state.clinical_notes


def get_clinical_document_repository(request: Request) -> ClinicalDocumentRepository:
    return request.app.state.clinical_documents


def get_consent_repository(request: Request) -> ConsentRepository:
    return request.app.state.consents


def get_prescription_repository(request: Request) -> PrescriptionRepository:
    return request.app.state.prescriptions


def get_study_order_repository(request: Request) -> StudyOrderRepository:
    return request.app.state.study_orders


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.users


def get_branch_repository(request: Request) -> BranchRepository:
    return request.app.state.branches


def get_branch_hours_repository(request: Request) -> BranchHoursRepository:
    return request.app.state.branch_hours


def get_service_price_repository(request: Request) -> ServicePriceRepository:
    return request.app.state.service_prices


def get_business_settings_repository(request: Request) -> BusinessSettingsRepository:
    return request.app.state.business_settings


def get_reminder_dispatcher(request: Request) -> ReminderDispatcher:
    return request.app.state.reminder_dispatcher


def get_deposit_manager(request: Request) -> DepositManager:
    return request.app.state.deposit_manager


def get_deposit_repository(request: Request) -> DepositRepository:
    return request.app.state.deposits
