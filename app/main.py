"""MedLibra app factory: wires LibraGenda plus MedLibra's own patient and
clinical-note extensions, and mounts the routers."""

import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from libraauth.auditoria import (
    AuditoriaBase,
    AuditoriaRepository,
    agregar_middleware_de_usuario,
    build_logs_router,
    configurar_auditoria,
)
from libraauth.auth_events import AuthEventRepository, ip_del_request
from libraauth.bootstrap import ensure_demo_user
from libraauth.captcha import Captcha, UsadosEnBase
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.migrar import exigir_schema_al_dia
from libraauth.models import Base as AuthBase
from libraauth.password_reset import PasswordResetService
from libraauth.secretos import SecretosRepository
from libraauth.session_auth import (
    build_demo_codigos_router,
    build_smtp_settings_router,
    demo_username,
)
from libraauth.smtp_settings import SmtpSettingsRepository, resolver_smtp_config
from libraauth.terminos import TerminosRepository, build_terminos_router
from libracore import config_manager
from libracore.avisos_router import build_avisos_router
from libracore.candados import una_vez_al_arrancar
from libracore.config_router import (
    build_backup_router,
    build_empresa_admin_router,
    build_empresa_router,
)
from libracore.db.core import get_connection as lc_get_connection
from libracore.docs_api import cerrar_docs_de_la_api
from libracore.errores import instalar_registro_de_errores
from libracore.estado_del_sistema import build_estado_del_sistema_router
from libracore.nodo_conexion_router import build_conexion_del_nodo_router
from libracore.nodo_offline import SinConexion, SoloEnElCentral
from libracore.resguardo_enlace import build_resguardo_enlace_router
from libracore.respaldo import Instancia
from libracore.security_headers import CSP_SPA, SecurityHeadersMiddleware
from libracore.smtp_router import build_smtp_probe_router
from libracore.tema_router import build_tema_admin_router, build_tema_router
from libraedge.pantalla_del_central import create_canje_router, create_nodos_router
from libragenda import (
    DepositManager,
    ReminderDispatcher,
    SqlAlchemyDepositRepository,
    SqlAlchemyReminderRepository,
    crear_esquema,
)
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.database import configure, get_engine, get_session_factory
from libragenda.sqlalchemy_repository import Base, SqlAlchemyAppointmentRepository
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from . import offline
from .auditoria import AUDITABLES, COLUMNAS_CLINICAS, etiqueta_segura
from .auth import build_session_auth, get_current_user, require_admin, require_admin_o_servicio, require_staff
from .avisos import armar_notificacion, proveedores_de_la_instancia
from .config import Config, misma_base
from .modules_gate import require_module
from .notifications import DEFAULT_REMINDER_POLICIES
from .payments import ManualPaymentPort
from .routers import (
    agenda,
    appointments,
    availability,
    branch_hours,
    branches,
    business_settings,
    clinical_documents,
    clinical_notes,
    consents,
    deposits,
    facturacion_externa,
    health,
    holidays,
    prescriptions,
    reminders,
    resources,
    service_iva_rates,
    service_prices,
    services,
    sincronizacion_offline,
    study_orders,
    turnos_a_revisar,
)
from .routers import (
    agenda_blocks as agenda_blocks_router,
)
from .routers import auth as auth_router
from .routers import (
    consultorios as consultorios_router,
)
from .routers import (
    dashboard as dashboard_router,
)
from .routers import (
    medios_pago as medios_pago_router,
)
from .routers import patients as patients_router
from .routers import (
    resource_prices as resource_prices_router,
)
from .routers import users as users_router
from .routers import (
    walkins as walkins_router,
)
from .services import libracore_setup
from .services.agenda_blocks import AgendaBlockRepository
from .services.appointments import AppointmentService
from .services.branch_hours import BranchHoursRepository
from .services.branches import BranchRepository
from .services.business_settings import BusinessSettingsRepository
from .services.clinical_documents import ClinicalDocumentRepository
from .services.clinical_notes import ClinicalNoteRepository
from .services.consents import ConsentRepository
from .services.consultorios import ConsultorioRepository
from .services.contalibra import EnvioRepository as EnvioContalibraRepository
from .services.dashboard import DashboardService
from .services.iva_rates import IvaRateRepository
from .services.modules import ModuleRepository
from .services.patients import PatientRepository
from .services.prescriptions import PrescriptionRepository
from .services.resource_prices import ResourcePriceRepository
from .services.service_prices import ServicePriceRepository
from .services.study_orders import StudyOrderRepository
from .services.users import UserRepository, ensure_default_admin
from .services.walkins import WalkinRepository


def _carpeta_de_backups(libracore_db_path: str) -> str:
    """Donde se guardan los ZIP de backup.

    🔴 **Salia de `os.path.dirname(libracore_db_path)`, y con la base en
    PostgreSQL eso no es una carpeta.** `dirname()` de
    `postgresql://usuario:clave@host:5432/base` devuelve
    `postgresql://usuario:clave@host:5432`, y ahi se creaba `backups/`: una
    carpeta **con la contrasena en el nombre**, colgando del directorio de
    trabajo. Es el mismo defecto que `libracore_setup.configure()` —entonces
    llamado `billing.configure()`— tenia en los tres productos, en otro lugar
    del mismo arranque.

    Con la base en PostgreSQL no hay "al lado de la base": se usa `DATA_DIR`,
    que es donde viven los logos y los documentos de esta instancia.
    """
    if str(libracore_db_path).startswith(("postgresql://", "postgresql+psycopg://")):
        return os.path.join(os.environ.get("DATA_DIR", "./data"), "backups")
    return os.path.join(os.path.dirname(libracore_db_path), "backups")


def _instancia_a_respaldar(database_url: str, libracore_db_path: str,
                           directorios: list) -> Instancia:
    """Que se lleva el backup, segun el motor de cada mitad.

    🔴 **Las dos mitades o ninguna.** Mientras el dominio y LibraCore sean dos
    bases (dos archivos en SQLite, dos bases PostgreSQL desde el corte, porque
    no podian compartir schema: las dos declaraban una tabla `clients` con `id`
    de tipos incompatibles), un backup con una sola no se puede restaurar: o
    volves el dominio y te quedan usuarios de otro momento, o al reves. Y no
    falla: da un ZIP que se descarga y pesa poco.

    Con una sola base (ADR-043: libragenda v0.14.0 renombro su `clients`) hay una
    sola mitad, y declarar la misma base como `postgres_extra` la volcaria dos
    veces y la restauraria encima de si misma: el core se agrega **sólo si es otra**.

    Eso es exactamente lo que pasaba al cortar a PostgreSQL: `bases=` sirve para
    rutas de archivo, asi que la URL de la base entraba como si fuera una ruta,
    el archivo no existia y el ZIP salia con una sola base -- sin avisar. Lo
    encontro `test_el_backup_trae_las_dos_bases` al correr la suite contra
    PostgreSQL, no un cliente al intentar restaurar.
    """
    dominio = make_url(database_url)
    if dominio.drivername.startswith("postgresql"):
        extra = []
        if (str(libracore_db_path).startswith(("postgresql://", "postgresql+psycopg://"))
                and not misma_base(database_url, str(libracore_db_path))):
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


_log = logging.getLogger(__name__)


def migrar_secretos() -> dict:
    """Saca de `config.json` los secretos que quedaron en claro. Idempotente.

    Corre en cada arranque (dentro de `create_app()`, ver mas abajo), asi la
    migracion de una instancia viva **es su deploy**. Loguea NOMBRES de
    claves, nunca valores: un log con el secreto lo muda del archivo a una
    superficie peor, porque los logs se copian y se mandan.

    Si cifrar falla, el `config.json` **no se toca** -la instancia sigue
    cobrando con la credencial que tiene- y se loguea como error, que es lo
    que despues ve la sonda `auditar_secretos.py`.
    """
    informe = config_manager.migrar_secretos_al_almacen()
    if informe["migradas"]:
        _log.warning(
            "secretos movidos de config.json al almacen cifrado: %s",
            ", ".join(informe["migradas"]),
        )
    if informe["ya_estaban"]:
        _log.warning(
            "config.json tenia una copia vieja de %s; se vacio (el almacen manda)",
            ", ".join(informe["ya_estaban"]),
        )
    if informe["fallaron"]:
        _log.error(
            "no se pudieron cifrar y QUEDAN EN CLARO en config.json: %s",
            ", ".join(f"{k} ({v})" for k, v in informe["fallaron"].items()),
        )
    return informe


async def _contestar_409_de_nodo(request: Request, exc: SinConexion | SoloEnElCentral) -> JSONResponse:
    """Lo que un nodo de LibraEdge contesta con un 409 y no con un 500 (ADR-045): lo que se hace sólo con internet o sólo en el
    central. `{"detail": {"codigo", "mensaje"}}`, el mismo cuerpo que los routers del motor."""
    return JSONResponse({"detail": exc.detalle()}, status_code=409)


#: Los routers cuyos datos manda el central: en un nodo se leen del espejo y se escriben sólo en el central (409
#: `solo_en_el_central`). En el central y en una instalación común no hace nada. Ver `app/offline.py`.
_DEL_CENTRAL = [Depends(offline.escritura_solo_en_el_central)]


def create_app(database_url: str) -> FastAPI:
    """Build the vertical app after configuring LibraGenda's PostgreSQL port."""
    # `pool_pre_ping` en el engine del dominio tambien (`libragenda.configure` se lo pasa a `create_engine`): mismo motivo
    # que el de auth mas abajo.
    configure(database_url, pool_pre_ping=True)
    # De a un proceso por vez (libragenda v0.12.0, ADR-015): con `uvicorn --workers N` el arranque corre N veces y dos
    # `create_all` a la vez chocan con «already exists».
    crear_esquema(get_engine())  # demo only; deploy uses Alembic

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
    #
    # 2026-10-25 (ADR-043): "la base de LibraCore" puede ser la del dominio. Con una sola
    # base las `usuarios` y las 11 tablas con FK a `usuarios` conviven con las de la agenda
    # (ya no chocan: `agenda_clients`, `medlibra_modulos`).
    #
    # La base de LibraCore puede ser la del dominio o una aparte (ADR-043): `Config` lo resuelve.
    config = Config.desde_entorno(database_url)
    libracore_db_path = config.libracore_database_url
    libracore_setup.configure(libracore_db_path)
    # La URL de SQLAlchemy salia siempre como `sqlite:///...`, aunque el destino
    # fuera una URL PostgreSQL: la interpolacion la convertia en una ruta
    # relativa sin sentido (`sqlite:///postgresql://...`) y el engine moria con
    # *unable to open database file*. `postgresql://` se pasa tal cual, con el
    # driver psycopg que es el de la familia, y `connect_args` es de SQLite.
    # Mismo arreglo que [[ventalibra]] y [[gestiolibra]].
    if libracore_db_path.startswith(("postgresql://", "postgresql+psycopg://")):
        # `pool_pre_ping`: tras un restore en caliente con varios workers, el que no atendio el restore se recupera
        # solo en vez de dar 500 hasta el reinicio (docs/varios-procesos.md de libracore).
        auth_engine = create_engine(
            libracore_db_path.replace("postgresql://", "postgresql+psycopg://", 1), pool_pre_ping=True
        )
    else:
        auth_engine = create_engine(
            f"sqlite:///{libracore_db_path}", connect_args={"check_same_thread": False}
        )
    # 🔴 Las tablas de auth las crea la cadena de LibraAuth (`libraauth-migrar
    # upgrade --prefijo medlibra --base dominio`, declarada en `scripts/panel_admin.py`; `core` si la
    # instancia tuviera la variable del core con OTRA base: `Config.base_de_auth`),
    # no el arranque. Desde libraauth v0.45.0 (2026-09-17) el arranque la EXIGE: si
    # no corrió, la app no levanta y el error dice el comando. Hasta ese día acá
    # había un `AuthBase.metadata.create_all(auth_engine)` que tapaba cualquier
    # camino que se olvidara de migrar.
    exigir_schema_al_dia(auth_engine, prefijo="medlibra", base=config.base_de_auth)
    auth_sessions = sessionmaker(bind=auth_engine)

    # 🔴 Los secretos de terceros de `config.json` -el access token y la firma
    # de webhook de MercadoPago, y la contrasena SMTP- dejan de vivir en texto
    # plano (libracore v1.108.0 + libraauth v0.46.0, 2026-09-17). Se enchufa
    # ACA, justo despues de `auth_sessions`: es el session factory que apunta a
    # la base de LIBRACORE, donde -a diferencia de Contalibra- viven las tablas
    # de libraauth en este producto (ver el comentario de `usuarios` mas
    # arriba). La tabla `secretos_instancia` la crea la revision `0002` de la
    # cadena de libraauth -no un `create_all`-, y `exigir_schema_al_dia()` ya
    # corrio dos lineas arriba, asi que esa revision esta garantizada.
    #
    # LibraCore no importa libraauth: recibe el almacen. Por eso el enganche es
    # del producto, que es el unico que tiene los dos paquetes.
    #
    # Desde aca, `config_manager.load()` sigue devolviendo el secreto en claro
    # a sus consumidores, pero lo trae de la base cifrada y no del archivo. La
    # migracion de lo que ya estaba en el JSON corre mas abajo, en el mismo
    # `create_app()`: ver `migrar_secretos()`.
    _secretos = SecretosRepository(auth_sessions)
    config_manager.usar_almacen_de_secretos(_secretos)

    sessions = get_session_factory()

    # Log de actividad (libraauth v0.11.0). Va contra el engine del DOMINIO
    # —el de LibraGenda— y no contra `auth_engine`: es donde ocurren las
    # escrituras que audita y donde vive su transacción.
    #
    # `columnas_ocultas` y `etiqueta` son las dos defensas que este producto
    # necesita y los otros tres no: el log lo lee cualquier admin, y el
    # contenido de una nota clínica o de una receta no tiene por qué quedar
    # copiado ahí. Ver `app/auditoria.py`.
    # DDL: con dos workers sobre una base nueva, dos `CREATE TABLE` a la vez se pisan (`pg_type_typname_nsp_index`).
    with una_vez_al_arrancar("medlibra-arranque", destino=libracore_db_path):
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
    # 🔴 De a un proceso por vez (ADR-044 de libracore). `create_app()` ES el arranque y con `uvicorn --workers N` lo corre
    # cada worker: un «si no existe, crear» (los modulos, el admin, el usuario de la demo) se contestaba «no existe» en
    # todos antes de que ninguno creara. El candado hace que el segundo espere al primero y vea lo que dejo; cada paso
    # sigue preguntando adentro, asi que sigue siendo idempotente. `destino` es la base de LibraCore: cualquiera sirve
    # mientras sea la misma para todos los workers (el candado es de esa base, no de lo que se siembra).
    with una_vez_al_arrancar("medlibra-arranque", destino=libracore_db_path):
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

    # Saca de `config.json` los secretos que quedaron en claro (2026-09-17).
    # Va DESPUES de `exigir_schema_al_dia` (dos pantallas mas arriba): la
    # tabla `secretos_instancia` es de la revision `0002` de libraauth, y
    # escribir en ella antes de saber que existe convertiria un schema viejo
    # en un 500 en vez del error que dice el comando. Este producto no tiene
    # un hook de `startup` separado -todo `create_app()` corre sincronico en
    # el arranque-, asi que la llamada va aca, al mismo tiempo que el resto
    # del cableado de auth. Idempotente: la segunda vez no hace nada.
    with una_vez_al_arrancar("medlibra-arranque", destino=libracore_db_path):
        migrar_secretos()

    app = FastAPI(title="MedLibra")
    cerrar_docs_de_la_api(app)
    # Lo que en un nodo de LibraEdge se hace sólo con internet o sólo en el central se contesta 409 (ADR-045), también si lo
    # levanta un servicio al que no llega ninguna traducción por ruta (el alta de un paciente, la nota de una consulta).
    for excepcion in (SinConexion, SoloEnElCentral):
        app.add_exception_handler(excepcion, _contestar_409_de_nodo)
    # La atención de un turno sin conexión se enchufa al outbox (ADR-045). Fuera de un nodo no hace nada.
    offline.configurar()

    # 🔴 Colgado de la app para poder SOLTARLO. En produccion la app es una y
    # vive lo que vive el proceso, asi que da igual; en la suite cada test arma
    # una app nueva y este engine deja un pool vivo por test. Contra SQLite no
    # se notaba --un `StaticPool` de una conexion que se recolecta sola--, pero
    # contra PostgreSQL son conexiones TCP que se acumulan hasta
    # `max_connections`, y el sintoma son errores de conexion en tests que no
    # tienen nada que ver con el que los causo. Ver `fresh_database_url()`.
    app.state.auth_engine = auth_engine
    app.state.catalog = catalog
    app.state.availability = availability_repository
    app.state.branches = BranchRepository(catalog, sessions)
    app.state.branch_hours = branch_hours_repository
    app.state.service_prices = ServicePriceRepository(sessions)
    app.state.resource_prices = ResourcePriceRepository(sessions)
    app.state.iva_rates = IvaRateRepository(sessions)
    app.state.business_settings = BusinessSettingsRepository(sessions)
    app.state.consultorios = ConsultorioRepository(sessions)
    app.state.agenda_blocks = AgendaBlockRepository(sessions)
    app.state.walkins = WalkinRepository(sessions)
    app.state.envios_contalibra = EnvioContalibraRepository(sessions)
    app.state.appointment_service = AppointmentService(
        catalog, appointment_repository, availability_repository, branch_hours_repository,
        app.state.agenda_blocks,
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
    # Los desafios del captcha ya resueltos se anotan en la base de `usuarios` (libraauth v0.50.0, ADR-023) y no en la
    # memoria del proceso: con `uvicorn --workers N` un desafio resuelto servia una vez POR WORKER. Es el mismo `Captcha`
    # que el router armaria solo (misma clave que la sesion), pero con `usados=`. La tabla la crea la revision `0003`
    # de la cadena de `libraauth-migrar`.
    app.state.captcha = Captcha(app.state.session_auth.secret_key, usados=UsadosEnBase(auth_sessions))
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
    # Los recordatorios salen de verdad (ADR-049, libracore ADR-090): WhatsApp por Evolution y mail por el SMTP de arriba, con
    # el modo y la conexion que el admin deja en Configuracion > Avisos. **La misma fabrica de proveedores** sirve al puerto, al
    # reintento de `/reminders/dispatch` y al router de `/api/avisos`: se resuelve en cada uso.
    def smtp_config():
        return resolver_smtp_config(auth_sessions)

    app.state.proveedores_de_avisos = proveedores_de_la_instancia(smtp_config)
    app.state.reminder_dispatcher = ReminderDispatcher(
        appointment_repository, reminder_repository,
        armar_notificacion(
            catalog=catalog, appointments=appointment_repository, branches=app.state.branches,
            consultorios=app.state.consultorios, proveedores=app.state.proveedores_de_avisos,
        ),
        DEFAULT_REMINDER_POLICIES,
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

    # 🔴 Los headers de seguridad. Se agrega **al final** a proposito: en
    # Starlette el ultimo middleware agregado es el mas externo, asi que asi
    # envuelve a todas las respuestas, incluidas las de error que devuelven los
    # de adentro.
    #
    # `CSP_SPA` y no la CSP por defecto: esa habilita `cdn.jsdelivr.net` para las
    # apps Jinja2, y este producto no carga nada externo. Ver libracore.
    app.add_middleware(SecurityHeadersMiddleware, csp=CSP_SPA)
    # El registro de errores de la familia (ADR-045 de libracore): un 500 deja una linea en `DATA_DIR/errores/` con un
    # `ref` que el usuario puede dictar, y monta `POST /api/errores-cliente` para los errores del navegador (publico a
    # proposito).
    instalar_registro_de_errores(app, "medlibra")

    app.include_router(health.router)
    # La sincronización del nodo offline (LibraEdge, ADR-045): `/sync/v1/push` y `/pull` (`/ticket-arca` y `/carga-inicial` contestan 501: MedLibra no factura ni tiene existencias). Se monta siempre: sin
    # un nodo registrado no hay ningún secreto válido y todo contesta 401. La autenticación es el secreto del nodo, no la
    # sesión: por eso no lleva guarda de rol.
    app.include_router(sincronizacion_offline.router)
    # `GET /api/nodo/conexion` (libracore ADR-084): si esta instalación es la PC del consultorio y si ve a la web, lo que lee el cartel
    # «Sin conexión» de la pantalla. MedLibra no factura: `a_facturar` es siempre 0. La abre cualquier usuario de la instancia
    # (`require_staff`, como la barra del pie): la pantalla la lee en cuanto carga la sesión. Fuera de un nodo contesta `es_nodo: false`.
    app.include_router(build_conexion_del_nodo_router(conexion=offline.CONEXION, usuario_actual=require_staff))
    # «Sucursal sin internet» (libraedge ADR-011 y ADR-014): el admin da de alta el nodo de una sede y se lleva la dirección y un
    # código de vinculación, ve los nodos y los da de baja. Toda la lógica es de LibraEdge; acá sólo la guarda (cambia la
    # estructura de la instancia: sólo admin) y el aprovisionamiento de `app/offline.py`.
    app.include_router(
        create_nodos_router(offline.aprovisionamiento, lc_get_connection),
        dependencies=[Depends(require_admin)],
    )
    # El canje del código (libraedge ADR-014): `POST /sync/v1/vinculacion`. **Sin guarda a propósito**: lo llama el instalador del
    # nodo, que no tiene sesión; lo protegen el código (un solo uso, 15 minutos) y el límite de intentos del motor.
    app.include_router(create_canje_router(offline.aprovisionamiento, lc_get_connection, ip_del_request=ip_del_request))
    app.include_router(auth_router.router)
    # `GET`/`PUT`/`DELETE /admin/smtp`. El router exige rol admin por dentro:
    # quien pueda escribir ahí puede redirigir a dónde salen los enlaces de
    # recuperación de contraseña de todos los usuarios.
    app.include_router(build_smtp_settings_router())
    # `POST /admin/smtp/probar`, del motor: abre la conexion, negocia TLS y
    # hace login.
    #
    # 🔑 Resuelve por el MISMO camino que los envios, y por eso el boton
    # significa algo: un endpoint que probara otra config diria "Conectado"
    # contra un servidor mientras los mails salen por otro. El gate va afuera
    # porque el router del motor no trae ninguno propio, y esto abre una
    # sesion SMTP con las credenciales del cliente.
    app.include_router(
        build_smtp_probe_router(lambda: resolver_smtp_config(auth_sessions)),
        dependencies=[Depends(require_admin)],
    )
    # `GET`/`PUT /api/avisos/config`, `POST /api/avisos/probar` y `GET /api/avisos/envios` (libracore ADR-090, ADR-049 de acá): cómo
    # está WhatsApp, cambiarlo, probarlo y el registro de lo que salió. Sólo admin (`require_admin` no tiene default en el
    # motor): el registro guarda el teléfono, el mail y el texto de cada aviso a un paciente. `PUT` y `probar` dan 409
    # `solo_en_el_central` en un nodo: el motor lo resuelve solo, no hace falta `_DEL_CENTRAL`. El mismo `smtp_config` que el de arriba.
    app.include_router(build_avisos_router(require_admin=require_admin, smtp_config=smtp_config))
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
    app.include_router(branches.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(branch_hours.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(holidays.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(resources.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(services.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(service_prices.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(resource_prices_router.router, dependencies=admin_only + _DEL_CENTRAL)
    # Que consultas se mandaron a Contalibra y cuales no pudieron. Admin: es
    # plata y es configuracion de la instancia, no operacion del mostrador.
    app.include_router(facturacion_externa.router, dependencies=admin_only + _DEL_CENTRAL)
    # 🔴 Con que medios se puede cobrar. **NO va con `admin_only`**: lo consume
    # el selector del mostrador al completar un turno, y ahi no hay un admin.
    # Es una lista de constantes del motor, sin datos de la instancia.
    app.include_router(medios_pago_router.router)
    app.include_router(service_iva_rates.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(availability.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(consultorios_router.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(agenda_blocks_router.router, dependencies=admin_only + _DEL_CENTRAL)
    app.include_router(business_settings.router, dependencies=admin_only + _DEL_CENTRAL)
    # Usuarios acepta ADEMAS el token de servicio (libraauth v0.7.0): es lo
    # unico que el backoffice de la suite necesita y que no puede salir del
    # motor, porque el router de usuarios es propio de cada producto.
    #
    # Deliberadamente solo este: el resto de los routers admin-only siguen
    # exigiendo sesion de un usuario del producto. El backoffice no tiene por
    # que poder tocar el resto del dominio, y colgar la dependencia de
    # `admin_only` seria ampliar el permiso sin necesidad.
    #
    # El guard ya NO se pasa acá (ADR-018, libraauth v0.43.0): vive dentro
    # del router que arma `build_users_router()` en `app/routers/users.py`.
    app.include_router(users_router.router)
    # Recordatorios, señas, facturación y dashboard son módulos gateables
    # por plan (ver plans.py) -- el resto del dominio clínico y turnos
    # nunca se gatean (ver ADR-018).
    app.include_router(
        reminders.router, dependencies=admin_only + _DEL_CENTRAL + [Depends(require_module("recordatorios"))],
    )
    app.include_router(
        deposits.admin_router, dependencies=admin_only + _DEL_CENTRAL + [Depends(require_module("senas"))],
    )
    # 🔴 No hay router de `/config/arca`. Este producto ya no factura: la
    # facturación vive en Contalibra (ADR-036). El módulo "facturacion" del plan
    # sigue existiendo y ahora gatea **el envío**, no la emisión local.
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
    # La agenda trae su propia lectura del catálogo (`GET /agenda/catalogo`):
    # profesionales, sedes y prestaciones, sin abrirle a staff los routers de
    # configuración de arriba, que son el alta y el borrado (ADR-039).
    app.include_router(agenda.router, dependencies=staff_or_admin)
    # Los turnos que se atendieron sin conexión y en la web cambiaron mientras tanto (ADR-045): staff y admin, en las dos puntas.
    app.include_router(turnos_a_revisar.router, dependencies=staff_or_admin)
    # La fila por orden de llegada va con los turnos y NO con la configuración:
    # armar el bloque de agenda es tarea de quien parametriza (admin), pero
    # anotar a quien acaba de entrar por la puerta la hace la secretaria todas
    # las mañanas. Con `admin_only` la función existiría y no la podría usar
    # nadie del mostrador.
    app.include_router(walkins_router.router, dependencies=staff_or_admin)
    app.include_router(
        deposits.request_router, dependencies=staff_or_admin + _DEL_CENTRAL + [Depends(require_module("senas"))],
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

    # El tema de la suite (libracore ADR-012, libra-ui ADR-007/008): los colores que el backoffice de la suite empuja a esta instancia. La
    # lectura es PÚBLICA a propósito (el login también va con los colores de la suite y no expone nada sensible). La escritura es del admin O
    # del token de servicio del backoffice: 🔴 con `require_admin` a secas el backoffice NO entraría (esa guarda no conoce el token).
    app.include_router(build_tema_router())
    app.include_router(build_tema_admin_router(), dependencies=[Depends(require_admin_o_servicio)])

    # 🔴 DOS bases, y las dos tienen que entrar al backup: `usuarios` vive en
    # la de LibraCore, separada de la del dominio. Un backup de una sola no se
    # puede restaurar —o volves el dominio y te quedan usuarios de otro
    # momento, o al reves— y no falla: da un ZIP que se descarga y pesa poco.
    #
    # 🔴 Y los documentos clinicos son archivos en disco. Un backup "de la
    # base" los deja afuera enteros, y el cliente se lleva un ZIP creyendo que
    # tiene los estudios de sus pacientes.
    engine = get_engine()
    # Una sola variable para los dos routers de abajo: el enlace de la copia
    # externa deja su `rclone.conf` en `<backups_dir>/.resguardo/`, y el subidor
    # del host lo busca AL LADO de los ZIP. Calculada dos veces, un cambio en
    # una sola llamada dejaria el enlace en una carpeta que nadie lee.
    backups_dir = _carpeta_de_backups(libracore_db_path)
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
            backups_dir,
            # Sin estos dos el restore devuelve `ok` y no tiene efecto hasta
            # que alguien reinicie el contenedor: el pool sigue con el archivo
            # viejo abierto. `dispose()` sirve para los dos momentos.
            cerrar_conexiones=engine.dispose,
            reabrir_conexiones=engine.dispose,
        ),
        dependencies=admin_only,
    )
    # La barra de estado del pie (libracore ADR-075, libra-ui ADR-083): usuario, versión, el certificado de ARCA y el
    # último respaldo, en una consulta. La abre cualquier rol de la instancia; lo que ve cada uno lo decide el motor
    # (ARCA y respaldo, sólo admin).
    app.include_router(
        build_estado_del_sistema_router(
            usuario_actual=get_current_user, backups_dir=backups_dir, conexion=offline.CONEXION,
            # La barra del pie: la PC con su conexión, o los nodos del central.
            nodos_del_central=offline.nodos_del_central,
        ),
        dependencies=[Depends(require_staff)],
    )
    # Enlace de la copia externa con la nube del cliente (LibraCore v1.93.0):
    # `GET`/`DELETE /api/config/resguardo-externo/enlace`, `POST .../{proveedor}`
    # y `GET .../callback`. El router es del motor; el producto pone el gate.
    #
    # 🔴 Dos gates y los dos hacen falta. `admin_only` porque conecta la cuenta
    # de nube del cliente; `require_module("resguardo_externo")` porque es un
    # ADD-ON (`plans.ADDONS`): apagado hasta que el backoffice lo prenda en esta
    # instancia. El 403 del segundo es lo que la pantalla lee como "sin plan".
    # El callback queda detras de los dos a proposito: la cookie de sesion es
    # `SameSite=Lax` y viaja en la vuelta desde Google/Dropbox.
    #
    # `volver_a` queda en el default (`/configuracion?seccion=datos`): es donde
    # vive la pantalla en este producto.
    app.include_router(
        build_resguardo_enlace_router(backups_dir, carpeta="Resguardo MedLibra"),
        dependencies=admin_only + [Depends(require_module("resguardo_externo"))],
    )

    return app
