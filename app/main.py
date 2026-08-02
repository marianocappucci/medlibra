"""MedLibra app factory: wires LibraGenda plus MedLibra's own patient and
clinical-note extensions, and mounts the routers."""

import os

from fastapi import Depends, FastAPI

from libraauth.models import Base as AuthBase
from libraauth.password_reset import PasswordResetService
from libraauth.session_auth import build_smtp_settings_router
from libraauth.smtp_settings import SmtpSettingsRepository, resolver_smtp_config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from libragenda import DepositManager, ReminderDispatcher, SqlAlchemyDepositRepository, SqlAlchemyReminderRepository
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.database import configure, get_engine, get_session_factory
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository

from .auth import build_session_auth, require_admin, require_staff
from .modules_gate import require_module
from .notifications import DEFAULT_REMINDER_POLICIES, LoggingNotificationPort
from .payments import ManualPaymentPort
from .routers import (
    agenda, appointments, availability, billing as billing_router, branch_hours, branches,
    business_settings, clinical_documents, clinical_notes, consents, dashboard as dashboard_router,
    deposits, health, prescriptions, reminders, resources, service_prices, services, study_orders,
)
from .routers import auth as auth_router
from .routers import patients as patients_router
from .routers import users as users_router
from .services.appointments import AppointmentService
from .services.branch_hours import BranchHoursRepository
from .services.branches import BranchRepository
from .services.business_settings import BusinessSettingsRepository
from .services.clinical_documents import ClinicalDocumentRepository
from .services.clinical_notes import ClinicalNoteRepository
from .services.consents import ConsentRepository
from .services.dashboard import DashboardService
from .services.modules import ModuleRepository
from .services.patients import PatientRepository
from .services.prescriptions import PrescriptionRepository
from .services.service_prices import ServicePriceRepository
from .services.study_orders import StudyOrderRepository
from .services.users import UserRepository, ensure_default_admin
from .services import billing


def create_app(database_url: str) -> FastAPI:
    """Build the vertical app after configuring LibraGenda's PostgreSQL port."""
    configure(database_url)
    Base.metadata.create_all(get_engine())  # demo only; deploy uses Alembic

    # `usuarios` (libraauth) vive en la base de LIBRACORE, no en la del dominio.
    #
    # Es deliberado y se pago aprendiendolo: 11 tablas de libracore
    # (facturas, ventas, caja_movimientos, turnos_caja, egresos, egresos_pagos,
    # movimientos_stock, movimientos_tesoreria, cc_pagos, remitos, presupuestos)
    # declaran `usuario_id REFERENCES usuarios(id)`, y esas FK resuelven contra
    # la tabla que este en SU MISMO archivo. Mover `usuarios` a la base del
    # dominio (como se hizo el 2026-07-30 y se revirtio el mismo dia) dejaba dos
    # copias con ids distintos: un usuario nuevo entraba solo en la de auth, y
    # al facturar libracore escribia un usuario_id que ahi no existia -> o
    # violacion de FK, o el registro atribuido a OTRA persona. Ver
    # wiki/entities/libraauth.md.
    #
    # libraauth lee sin problema la tabla que escribio el sqlite3 crudo de
    # libracore (mismo schema, mismo hashing) y `create_all` no la altera.
    libracore_db_path = os.environ.get(
        "MEDLIBRA_LIBRACORE_DB_PATH", "./data/medlibra_libracore.db"
    )
    billing.configure(libracore_db_path)
    auth_engine = create_engine(
        f"sqlite:///{libracore_db_path}", connect_args={"check_same_thread": False}
    )
    AuthBase.metadata.create_all(auth_engine)
    auth_sessions = sessionmaker(bind=auth_engine)

    sessions = get_session_factory()
    catalog = SqlAlchemyCatalogRepository(sessions)
    appointment_repository = SqlAlchemyAppointmentRepository(sessions)
    availability_repository = SqlAlchemyAvailabilityRepository(sessions)
    # libraauth: el repositorio recibe el session_factory del producto (antes
    # usaba la conexion sqlite3 global de libracore). Sin `roles=`: el default
    # ("admin","staff") es exactamente el vocabulario de MedLibra.
    user_repository = UserRepository(auth_sessions)
    branch_hours_repository = BranchHoursRepository(sessions)
    deposit_repository = SqlAlchemyDepositRepository(sessions)
    reminder_repository = SqlAlchemyReminderRepository(sessions)
    patient_repository = PatientRepository(catalog, sessions)
    module_repository = ModuleRepository(sessions)
    module_repository.ensure_seeded()
    ensure_default_admin(user_repository)

    app = FastAPI(title="MedLibra")
    app.state.catalog = catalog
    app.state.availability = availability_repository
    app.state.branches = BranchRepository(catalog, sessions)
    app.state.branch_hours = branch_hours_repository
    app.state.service_prices = ServicePriceRepository(sessions)
    app.state.business_settings = BusinessSettingsRepository(sessions)
    app.state.appointment_service = AppointmentService(
        catalog, appointment_repository, availability_repository, branch_hours_repository,
    )
    app.state.patients = patient_repository
    app.state.clinical_notes = ClinicalNoteRepository(sessions)
    app.state.prescriptions = PrescriptionRepository(sessions)
    app.state.study_orders = StudyOrderRepository(sessions)
    documents_dir = os.environ.get("MEDLIBRA_DOCUMENTS_DIR", "./data/medlibra_documents")
    app.state.clinical_documents = ClinicalDocumentRepository(sessions, documents_dir)
    app.state.consents = ConsentRepository(sessions)
    app.state.users = user_repository
    app.state.session_auth = build_session_auth(user_repository)
    # Recuperación de contraseña por correo (libraauth v0.5.0). `auth_sessions`
    # y no el session_factory del dominio: la tabla de tokens tiene FK a
    # `usuarios`, que vive en la base de LibraCore. Sin SMTP configurado la app
    # levanta igual y el endpoint devuelve 503.
    # Config SMTP editable por backoffice (libraauth v0.6.0), con la contraseña
    # cifrada en reposo. Mismo `auth_sessions` que el resto del motor.
    app.state.smtp_settings = SmtpSettingsRepository(auth_sessions)
    app.state.password_reset = PasswordResetService(
        auth_sessions,
        product_name="MedLibra",
        reset_url_base=os.environ.get(
            "MEDLIBRA_RESET_URL_BASE", "https://dev.medlibra.com.ar/reset-password"
        ),
        # CALLABLE, no un valor: se resuelve en cada envío. Con un valor fijo,
        # guardar el SMTP por pantalla no tendría efecto hasta recrear el
        # contenedor. Sin nada guardado cae a las variables de entorno, así que
        # la instancia se comporta igual que antes hasta que se cargue algo.
        smtp_config=lambda: resolver_smtp_config(auth_sessions),
    )
    app.state.reminder_dispatcher = ReminderDispatcher(
        appointment_repository, reminder_repository,
        LoggingNotificationPort(), DEFAULT_REMINDER_POLICIES,
    )
    app.state.deposits = deposit_repository
    app.state.deposit_manager = DepositManager(deposit_repository, ManualPaymentPort())
    app.state.dashboard = DashboardService(
        appointment_repository, patient_repository, reminder_repository, deposit_repository,
    )
    app.state.modules = module_repository

    app.include_router(health.router)
    app.include_router(auth_router.router)
    # `GET`/`PUT`/`DELETE /admin/smtp`. El router exige rol admin por dentro:
    # quien pueda escribir ahí puede redirigir a dónde salen los enlaces de
    # recuperación de contraseña de todos los usuarios.
    app.include_router(build_smtp_settings_router())
    # Business/admin surface: only admins manage consultorios, profesionales,
    # servicios, disponibilidad, hours, prices, business settings and other
    # users.
    admin_only = [Depends(require_admin)]
    app.include_router(branches.router, dependencies=admin_only)
    app.include_router(branch_hours.router, dependencies=admin_only)
    app.include_router(resources.router, dependencies=admin_only)
    app.include_router(services.router, dependencies=admin_only)
    app.include_router(service_prices.router, dependencies=admin_only)
    app.include_router(availability.router, dependencies=admin_only)
    app.include_router(business_settings.router, dependencies=admin_only)
    app.include_router(users_router.router, dependencies=admin_only)
    # Recordatorios, señas, facturación y dashboard son módulos gateables
    # por plan (ver plans.py) -- el resto del dominio clínico y turnos
    # nunca se gatean (ver ADR-018).
    app.include_router(
        reminders.router, dependencies=admin_only + [Depends(require_module("recordatorios"))],
    )
    app.include_router(
        deposits.admin_router, dependencies=admin_only + [Depends(require_module("senas"))],
    )
    app.include_router(
        billing_router.router, dependencies=admin_only + [Depends(require_module("facturacion"))],
    )
    app.include_router(
        dashboard_router.router, dependencies=admin_only + [Depends(require_module("dashboard"))],
    )
    # Clinical surface: staff (medical professionals) read/write patients,
    # write historia clinica, issue recetas, pedidos de estudios, upload
    # documentos clinicos and record consentimientos -- that's their actual
    # job, unlike Gestiolibra's staff which never touches the catalog.
    # Deleting a patient, note, prescription, study order, document or
    # consent is still admin-only (see the per-route dependencies on those
    # routers).
    staff_or_admin = [Depends(require_staff)]
    app.include_router(patients_router.router, dependencies=staff_or_admin)
    app.include_router(clinical_notes.router, dependencies=staff_or_admin)
    app.include_router(prescriptions.router, dependencies=staff_or_admin)
    app.include_router(study_orders.router, dependencies=staff_or_admin)
    app.include_router(clinical_documents.router, dependencies=staff_or_admin)
    app.include_router(consents.router, dependencies=staff_or_admin)
    app.include_router(appointments.router, dependencies=staff_or_admin)
    app.include_router(agenda.router, dependencies=staff_or_admin)
    app.include_router(
        deposits.request_router, dependencies=staff_or_admin + [Depends(require_module("senas"))],
    )

    return app
