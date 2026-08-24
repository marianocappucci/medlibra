"""MedLibra app factory: wires LibraGenda plus MedLibra's own patient and
clinical-note extensions, and mounts the routers."""

import os

from libracore.db.url_de_instancia import url_de_instancia

from fastapi import Depends, FastAPI

from libraauth.auditoria import (
    AuditoriaBase, AuditoriaRepository, agregar_middleware_de_usuario, build_logs_router,
    configurar_auditoria,
)
from libraauth.auth_events import AuthEventRepository
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.models import Base as AuthBase
from libraauth.password_reset import PasswordResetService
from libraauth.session_auth import (
    build_demo_codigos_router, build_smtp_settings_router, demo_username,
)
from libraauth.smtp_settings import SmtpSettingsRepository, resolver_smtp_config
from libraauth.terminos import TerminosRepository, build_terminos_router
from libracore import config_manager
from libracore.config_router import (
    build_backup_router, build_empresa_admin_router, build_empresa_router,
)
from libracore.respaldo import Instancia
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from libragenda import DepositManager, ReminderDispatcher, SqlAlchemyDepositRepository, SqlAlchemyReminderRepository
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.database import configure, get_engine, get_session_factory
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository

from .auditoria import AUDITABLES, COLUMNAS_CLINICAS, etiqueta_segura
from .auth import build_session_auth, require_admin, require_admin_o_servicio, require_staff
from .modules_gate import require_module
from .notifications import DEFAULT_REMINDER_POLICIES, LoggingNotificationPort
from .payments import ManualPaymentPort
from .routers import (
    agenda, agenda_blocks as agenda_blocks_router, appointments, availability,
    billing as billing_router, branch_hours, branches,
    business_settings, clinical_documents, clinical_notes, consents,
    consultorios as consultorios_router, dashboard as dashboard_router,
    deposits, health, prescriptions, reminders, resources, service_iva_rates, service_prices,
    services, study_orders, walkins as walkins_router,
)
from .routers import auth as auth_router
from .routers import patients as patients_router
from .routers import users as users_router
from .services.appointments import AppointmentService
from .services.branch_hours import BranchHoursRepository
from .services.agenda_blocks import AgendaBlockRepository, AppointmentRoomRepository
from .services.branches import BranchRepository
from .services.consultorios import ConsultorioRepository
from .services.walkins import WalkinRepository
from .services.business_settings import BusinessSettingsRepository
from .services.clinical_documents import ClinicalDocumentRepository
from .services.clinical_notes import ClinicalNoteRepository
from .services.consents import ConsentRepository
from .services.dashboard import DashboardService
from .services.modules import ModuleRepository
from .services.patients import PatientRepository
from .services.prescriptions import PrescriptionRepository
from .services.iva_rates import IvaRateRepository
from .services.service_prices import ServicePriceRepository
from .services.study_orders import StudyOrderRepository
from libraauth.bootstrap import ensure_demo_user
from .services.users import UserRepository, ensure_default_admin
from .services import billing


def _carpeta_de_backups(libracore_db_path: str) -> str:
    """Donde se guardan los ZIP de backup.

    🔴 **Salia de `os.path.dirname(libracore_db_path)`, y con la base en
    PostgreSQL eso no es una carpeta.** `dirname()` de
    `postgresql://usuario:clave@host:5432/base` devuelve
    `postgresql://usuario:clave@host:5432`, y ahi se creaba `backups/`: una
    carpeta **con la contrasena en el nombre**, colgando del directorio de
    trabajo. Es el mismo defecto que `billing.configure()` tenia en los tres
    productos, en otro lugar del mismo arranque.

    Con la base en PostgreSQL no hay "al lado de la base": se usa `DATA_DIR`,
    que es donde viven los logos y los documentos de esta instancia.
    """
    if str(libracore_db_path).startswith(("postgresql://", "postgresql+psycopg://")):
        return os.path.join(os.environ.get("DATA_DIR", "./data"), "backups")
    return os.path.join(os.path.dirname(libracore_db_path), "backups")


def _instancia_a_respaldar(database_url: str, libracore_db_path: str,
                           directorios: list) -> Instancia:
    """Que se lleva el backup, segun el motor de cada mitad.

    🔴 **Las dos mitades o ninguna.** El dominio y LibraCore son dos bases
    separadas -- dos archivos en SQLite, dos bases PostgreSQL despues del corte,
    porque no pueden compartir schema: las dos declaran una tabla `clients` con
    `id` de tipos incompatibles. Un backup con una sola no se puede restaurar:
    o volves el dominio y te quedan usuarios de otro momento, o al reves. Y no
    falla: da un ZIP que se descarga y pesa poco.

    Eso es exactamente lo que pasaba al cortar a PostgreSQL: `bases=` sirve para
    rutas de archivo, asi que la URL de la base entraba como si fuera una ruta,
    el archivo no existia y el ZIP salia con una sola base -- sin avisar. Lo
    encontro `test_el_backup_trae_las_dos_bases` al correr la suite contra
    PostgreSQL, no un cliente al intentar restaurar.
    """
    dominio = make_url(database_url)
    if dominio.drivername.startswith("postgresql"):
        extra = []
        if str(libracore_db_path).startswith(("postgresql://", "postgresql+psycopg://")):
            extra.append(str(libracore_db_path))
        return Instancia(
            nombre="medlibra",
            postgres_url=database_url,
            postgres_extra=extra,
            directorios=directorios,
        )
    return Instancia(
        nombre="medlibra",
        bases=[dominio.database, libracore_db_path],
        directorios=directorios,
    )


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
    libracore_db_path = url_de_instancia(
        "medlibra", core=True, default="./data/medlibra_libracore.db"
    )
    billing.configure(libracore_db_path)
    # La URL de SQLAlchemy salia siempre como `sqlite:///...`, aunque el destino
    # fuera una URL PostgreSQL: la interpolacion la convertia en una ruta
    # relativa sin sentido (`sqlite:///postgresql://...`) y el engine moria con
    # *unable to open database file*. `postgresql://` se pasa tal cual, con el
    # driver psycopg que es el de la familia, y `connect_args` es de SQLite.
    # Mismo arreglo que [[ventalibra]] y [[gestiolibra]].
    if libracore_db_path.startswith(("postgresql://", "postgresql+psycopg://")):
        auth_engine = create_engine(
            libracore_db_path.replace("postgresql://", "postgresql+psycopg://", 1)
        )
    else:
        auth_engine = create_engine(
            f"sqlite:///{libracore_db_path}", connect_args={"check_same_thread": False}
        )
    AuthBase.metadata.create_all(auth_engine)
    auth_sessions = sessionmaker(bind=auth_engine)

    sessions = get_session_factory()

    # Log de actividad (libraauth v0.11.0). Va contra el engine del DOMINIO
    # —el de LibraGenda— y no contra `auth_engine`: es donde ocurren las
    # escrituras que audita y donde vive su transacción.
    #
    # `columnas_ocultas` y `etiqueta` son las dos defensas que este producto
    # necesita y los otros tres no: el log lo lee cualquier admin, y el
    # contenido de una nota clínica o de una receta no tiene por qué quedar
    # copiado ahí. Ver `app/auditoria.py`.
    AuditoriaBase.metadata.create_all(get_engine())
    configurar_auditoria(
        sessions, AUDITABLES,
        columnas_ocultas=COLUMNAS_CLINICAS,
        etiqueta=etiqueta_segura,
    )

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
    # Crea al visitante de la demo, **solo si esta instancia es una demo**: se
    # guia por `DEMO_MODE` + `DEMO_USERNAME`, las mismas dos variables que
    # registran `POST /auth/demo`. En la instancia de un cliente devuelve None
    # y no toca la base.
    #
    # 🔴 Sin esta llamada la ruta existe y no tiene a quien loguear: contesta
    # `503 demo user not provisioned`. Cablear `incluir_demo=True` en el router
    # no alcanza — la ruta y la siembra las conecta el producto, cada una por
    # su lado.
    ensure_demo_user(user_repository)

    app = FastAPI(title="MedLibra")
    app.state.catalog = catalog
    app.state.availability = availability_repository
    app.state.branches = BranchRepository(catalog, sessions)
    app.state.branch_hours = branch_hours_repository
    app.state.service_prices = ServicePriceRepository(sessions)
    app.state.iva_rates = IvaRateRepository(sessions)
    app.state.business_settings = BusinessSettingsRepository(sessions)
    app.state.consultorios = ConsultorioRepository(sessions)
    app.state.agenda_blocks = AgendaBlockRepository(sessions)
    app.state.appointment_rooms = AppointmentRoomRepository(sessions)
    app.state.walkins = WalkinRepository(sessions)
    app.state.appointment_service = AppointmentService(
        catalog, appointment_repository, availability_repository, branch_hours_repository,
        app.state.agenda_blocks, app.state.appointment_rooms,
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
    # Terminos y Condiciones del Servicio: la prueba de la aceptacion y lo que
    # enciende el gate. MISMA fabrica de sesiones que el SMTP y los usuarios --
    # la tabla tiene FK a `usuarios`, que no siempre vive en la base del dominio.
    #
    # 🔴 Sin esta linea el gate NO corta y la instancia no falla: se queda sin
    # gate, en silencio. Por eso cada producto tiene un test que lo prueba.
    app.state.terminos = TerminosRepository(auth_sessions)
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
    app.state.auditoria = AuditoriaRepository(sessions)
    # Accesos: `auth_sessions`, que apunta a la base de LibraCore, donde
    # `auth_log` ya existe. Esto no agrega la tabla: empieza a escribirla.
    app.state.auth_events = AuthEventRepository(auth_sessions)
    # Sella el usuario de la cookie para que la auditoría sepa quién escribió.
    agregar_middleware_de_usuario(app)

    app.include_router(health.router)
    app.include_router(auth_router.router)
    # `GET`/`PUT`/`DELETE /admin/smtp`. El router exige rol admin por dentro:
    # quien pueda escribir ahí puede redirigir a dónde salen los enlaces de
    # recuperación de contraseña de todos los usuarios.
    app.include_router(build_smtp_settings_router())
    # `GET /terminos`, `POST /terminos/aceptar`, `GET /terminos/historial`.
    # NO se gatea desde afuera: es el unico camino para salir del gate.
    app.include_router(build_terminos_router())
    # `GET`/`POST`/`DELETE /admin/demo-codigos`, **solo en la demo**: es por
    # donde el backoffice emite los codigos que se le pasan a un interesado.
    # Exige rol admin o token de servicio por dentro, igual que el de SMTP.
    #
    # 🔴 El repositorio va contra `auth_sessions`, NO contra `sessions`: la
    # tabla de codigos vive en el mismo engine que `usuarios`, que en este
    # producto no es la base del dominio. Con el factory del dominio, la tabla
    # se crearia en el lugar equivocado y `POST /auth/demo` no encontraria
    # ningun codigo valido.
    #
    # 🔴 Y una instancia demo que llegue aca SIN el repositorio deja de dejar
    # entrar: el endpoint falla cerrado a proposito. Si un dia la demo devuelve
    # `503 demo access codes not configured`, lo que falta es esta linea.
    if demo_username():
        app.state.demo_codigos = DemoCodigoRepository(auth_sessions)
        app.include_router(build_demo_codigos_router())
    # Business/admin surface: only admins manage consultorios, profesionales,
    # servicios, disponibilidad, hours, prices, business settings and other
    # users.
    admin_only = [Depends(require_admin)]
    app.include_router(branches.router, dependencies=admin_only)
    app.include_router(branch_hours.router, dependencies=admin_only)
    app.include_router(resources.router, dependencies=admin_only)
    app.include_router(services.router, dependencies=admin_only)
    app.include_router(service_prices.router, dependencies=admin_only)
    app.include_router(service_iva_rates.router, dependencies=admin_only)
    app.include_router(availability.router, dependencies=admin_only)
    app.include_router(consultorios_router.router, dependencies=admin_only)
    app.include_router(agenda_blocks_router.router, dependencies=admin_only)
    app.include_router(business_settings.router, dependencies=admin_only)
    # Usuarios acepta ADEMAS el token de servicio (libraauth v0.7.0): es lo
    # unico que el backoffice de la suite necesita y que no puede salir del
    # motor, porque el router de usuarios es propio de cada producto.
    #
    # Deliberadamente solo este: el resto de los routers admin-only siguen
    # exigiendo sesion de un usuario del producto. El backoffice no tiene por
    # que poder tocar el resto del dominio, y colgar la dependencia de
    # `admin_only` seria ampliar el permiso sin necesidad.
    app.include_router(users_router.router, dependencies=[Depends(require_admin_o_servicio)])
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
    # La fila por orden de llegada va con los turnos y NO con la configuración:
    # armar el bloque de agenda es tarea de quien parametriza (admin), pero
    # anotar a quien acaba de entrar por la puerta la hace la secretaria todas
    # las mañanas. Con `admin_only` la función existiría y no la podría usar
    # nadie del mostrador.
    app.include_router(walkins_router.router, dependencies=staff_or_admin)
    app.include_router(
        deposits.request_router, dependencies=staff_or_admin + [Depends(require_module("senas"))],
    )
    # Logs: admin y nada más, y acá el gate importa más que en los otros
    # productos — la fila dice quién abrió la ficha de qué paciente. **No** se
    # gatea por plan: un log de auditoría no es una feature vendible.
    #
    # El router lo arma el motor (libraauth v0.10.0) pero el gate lo pone el
    # producto: el vocabulario de roles es de acá, no del paquete.
    app.include_router(build_logs_router(AUDITABLES), dependencies=[Depends(require_admin)])

    # Datos de empresa, logo y Datos / Backup (LibraCore v1.11.0).
    #
    # Los tres routers son del motor: este producto no reimplementa nada, solo
    # les pone su dependencia de rol. Todo admin — hasta hoy este producto no
    # tenia NINGUNA pantalla de configuracion, asi que no hay ningun consumidor
    # de la lectura que haya que dejar abierto.
    app.include_router(build_empresa_router(), dependencies=admin_only)
    app.include_router(build_empresa_admin_router(), dependencies=admin_only)

    # 🔴 DOS bases, y las dos tienen que entrar al backup: `usuarios` vive en
    # la de LibraCore, separada de la del dominio. Un backup de una sola no se
    # puede restaurar —o volves el dominio y te quedan usuarios de otro
    # momento, o al reves— y no falla: da un ZIP que se descarga y pesa poco.
    #
    # 🔴 Y los documentos clinicos son archivos en disco. Un backup "de la
    # base" los deja afuera enteros, y el cliente se lleva un ZIP creyendo que
    # tiene los estudios de sus pacientes.
    engine = get_engine()
    app.include_router(
        build_backup_router(
            _instancia_a_respaldar(
                database_url,
                libracore_db_path,
                directorios=[
                    config_manager.LOGO_DIR,
                    os.environ.get("MEDLIBRA_DOCUMENTS_DIR", "./data/medlibra_documents"),
                ],
            ),
            _carpeta_de_backups(libracore_db_path),
            # Sin estos dos el restore devuelve `ok` y no tiene efecto hasta
            # que alguien reinicie el contenedor: el pool sigue con el archivo
            # viejo abierto. `dispose()` sirve para los dos momentos.
            cerrar_conexiones=engine.dispose,
            reabrir_conexiones=engine.dispose,
        ),
        dependencies=admin_only,
    )

    return app
