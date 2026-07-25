# MedLibra

Vertical de turnos para salud: consultorios, profesionales independientes y
centros médicos.

Compone:

- LibraGenda `v0.9.0` — agenda, recursos, servicios, ciclo de vida de turnos
  (incluye `complete()`), disponibilidad/bloqueos/excepciones, feriados y
  timezone por sucursal, recurrencias, recordatorios (puerto de
  notificaciones + `list_sent()` para reportes), señas (puerto de pagos,
  `medio_pago` opcional + `list_by_status()`) y motivo opcional de
  cancelación/reprogramación.
- LibraCore `v0.16.1` — `libracore.auth.SessionAuth` (login por cookie
  firmada) y `libracore.arca_facturacion`/`libracore.db` (facturación
  electrónica ARCA + caja, ver `DECISIONS.md` ADR-016).

MedLibra posee la API HTTP y el dominio clínico propio. API: `/auth/login`,
`/auth/logout`, `/auth/me` (sesión por cookie); CRUD de usuarios en `/users`
(solo `admin`); CRUD de `/branches` (incluye `phone`/`address`),
`/resources`, `/services` y disponibilidad
(`/resources/{id}/availability`/`/blocks`/`/exceptions`, solo `admin`);
horario comercial por sucursal en `/branches/{id}/hours` (opt-in); precio
por servicio y sucursal en `/services/{id}/prices`; datos globales del
consultorio (nombre comercial, moneda) en `/business`; `/patients` (CRUD
completo — paciente = `Client` de LibraGenda + `dni`/`birth_date` propios,
`admin`+`staff`, borrar es admin-only); `/patients/{id}/notes` (historia
clínica básica — notas de evolución en texto libre, solo crear/listar/
obtener/borrar sin editar, `admin`+`staff`, borrar es admin-only);
`/patients/{id}/prescriptions` (recetas — una receta con uno o más items
de medicamento/dosis/indicaciones, mismo criterio append-only que las
notas clínicas, `admin`+`staff`, borrar es admin-only);
`/patients/{id}/study-orders` (pedidos de estudios — un pedido con uno o
más items de tipo de estudio/motivo, `admin`+`staff`, borrar es
admin-only) y `/patients/{id}/study-orders/{order_id}/items/{item_id}/results`
(resultado de un estudio, como registro separado vinculado al item,
`admin`+`staff`, borrar es admin-only); `/patients/{id}/documents`
(documentos clínicos — subida `multipart/form-data` de un archivo PDF/PNG/
JPG/JPEG hasta 20MB con título/descripción/autor, `admin`+`staff`, borrar
es admin-only) y `/patients/{id}/documents/{document_id}/file` (descarga
del archivo); `/patients/{id}/consents` (consentimientos informados —
procedimiento, quién autoriza, texto libre, append-only sin revocación
editable, `admin`+`staff`, borrar es admin-only); `/appointments` (crear/confirmar/cancelar/reprogramar — `admin`+`staff`,
valida contra la disponibilidad real configurada y el horario comercial de
la sucursal si está configurado, cancelar/reprogramar aceptan `reason`
opcional); `/resources/{id}/agenda` (turnos de un profesional en un rango
de fechas); `/reminders/dispatch` (solo `admin`, dispara los recordatorios
vencidos — 24h y 2h antes de cada turno, fijo); y
`/appointments/{id}/deposit` (pedir/consultar una seña, `admin`+`staff`) +
`/deposits/{id}/mark-paid`/`mark-failed`/`refund` (solo `admin`, confirma
el estado de la seña). Evoluciones estructuradas y diagnósticos
quedan para fases siguientes.

Recordatorios y señas todavía no tienen un canal real conectado (mismo
estado que Gestiolibra): los recordatorios se loguean
(`LoggingNotificationPort`) y las señas se cobran y confirman fuera de la
app, a mano (`ManualPaymentPort` — ver `DECISIONS.md` ADR-010).

## Autenticación y roles

Sesión por cookie firmada (`ml_session`), sin API keys ni JWT todavía. Al
arrancar sin usuarios, se crea un admin de bootstrap
(`MEDLIBRA_ADMIN_USERNAME`/`MEDLIBRA_ADMIN_PASSWORD`; sin contraseña
configurada la app no levanta salvo `ENV=development`, donde usa
`admin`/`admin`). Roles: `admin` (todo, incluido borrar pacientes/notas) y
`staff` — personal médico: turnos + pacientes + historia clínica, sin poder
borrar ninguno de los dos. A diferencia de Gestiolibra (donde `staff` solo
toca turnos), acá el rol clínico necesita acceso a los datos del paciente
para hacer su trabajo.

LibraGenda permanece como paquete reutilizable con migraciones propias,
migradas desde un checkout de esa versión exacta contra `DATABASE_URL`
(no se distribuyen en el wheel de pip).

No confundir con los sistemas de salud del Servidor Homei (PACS, Farmacia,
Portal de Pacientes) — son proyectos completamente separados, sin relación
ni infraestructura compartida.

Los documentos clínicos subidos se guardan en filesystem local bajo
`MEDLIBRA_DOCUMENTS_DIR` (default `./data/medlibra_documents` — en
producción, un volumen persistente montado en ese path, mismo patrón que
`DATA_DIR` de Contalibra/Restolibra; ver `DECISIONS.md` ADR-013).

Facturación/caja usa `libracore.db` — sqlite3 crudo con su propia
conexión, configurada aparte del engine SQLAlchemy de LibraGenda/MedLibra
vía `MEDLIBRA_LIBRACORE_DB_PATH` (default `./data/medlibra_libracore.db`,
mismo criterio de volumen persistente que `MEDLIBRA_DOCUMENTS_DIR`). Ver
`DECISIONS.md` ADR-016.

## Base de datos

**SQLite es el destino de producción por defecto**, mismo estándar que
toda la familia Libra (arquitectura silo: una instancia/base aislada por
cliente, igual que Contalibra/Restolibra — ver `DECISIONS.md` ADR-015).
`LibraGenda.configure(url)` activa `PRAGMA foreign_keys=ON`
automáticamente para cualquier conexión SQLite. PostgreSQL sigue
soportado vía la misma `DATABASE_URL` para el caso puntual que lo
amerite, sin cambios de código.

## Migraciones

Dos cadenas de Alembic independientes corren contra la **misma** base
`medlibra`, cada una con su propia tabla de versión (`alembic_version` es
de LibraGenda, `alembic_version_medlibra` es de MedLibra). El deploy corre
ambas, en este orden, antes de levantar la API:

**1. Migraciones de LibraGenda** (schema del motor). No viajan en el wheel
instalado por pip, se aplican clonando el repo en el tag pineado en
`pyproject.toml` (hoy `v0.6.0`):

```bash
LIBRAGENDA_REF=v0.6.0 DATABASE_URL="sqlite:///data/medlibra.db" \
  bash path/a/libragenda/scripts/run_migrations.sh
```

**2. Migraciones propias de MedLibra** (`users`, `patients`,
`clinical_notes`, `branch_contacts`, `branch_hours`, `service_prices`,
`business_settings`, `prescriptions`, `prescription_items`,
`study_orders`, `study_order_items`, `study_results`,
`clinical_documents`, `consents`, `modulos` — no pertenecen al dominio de
LibraGenda, ver `MODULES.md`). Viajan en este mismo repo:

```bash
DATABASE_URL="$DATABASE_URL" alembic upgrade head
```

`migrations/env.py` deja `target_metadata = None` a propósito: esos tres
modelos están registrados en el `Base` compartido de LibraGenda, así que
apuntar el autogenerate ahí vería también las tablas de LibraGenda como
propias de esta cadena. Las migraciones se escriben a mano, mismo criterio
que LibraGenda y Gestiolibra.

## CI

`.github/workflows/ci.yml`: en cada push/PR a `main` — instala el paquete,
corre `pytest`, y como smoke check aplica las dos cadenas de Alembic
(LibraGenda + propia) contra un archivo SQLite, mismo orden que un
deploy real. Sin servicio de base de datos que levantar.

**Requiere un secret `LIBRA_PAT`** en este repo (Settings → Secrets and
variables → Actions): `libragenda` y `libracore` son privados, y el
`GITHUB_TOKEN` automático de Actions no tiene acceso a otros repos. Crear
un fine-grained PAT en <https://github.com/settings/tokens?type=beta>
scoped **solo** a `libragenda` y `libracore`, permiso **Contents:
Read-only**, y cargarlo como ese secret (mismo token se puede reusar en
Gestiolibra, cargándolo como secret ahí también — los secrets no se
comparten automáticamente entre repos). Sin este secret, el paso "Install
package + dev deps" falla (no un bug del workflow).

## Planes y módulos

Onboarding multi-consultorio con enforcement real (ver `DECISIONS.md`
ADR-018). `plans.py` (raíz del repo) define tres planes — Básico ($25k),
Estándar ($40k) y Premium ($60k) — y qué módulos gateables incluye cada
uno. **Todo el dominio clínico es siempre gratis y nunca se gatea**
(pacientes, historia clínica, recetas, estudios, documentos clínicos,
consentimientos), igual que catálogo/turnos — a diferencia de Gestiolibra,
acá lo clínico es una necesidad profesional básica, no un extra
comercial. Lo que varía por plan es recordatorios, señas, facturación y
dashboard.

La tabla `modulos` (migración `0011_modulos`) guarda el estado real por
instancia — se siembra con todo habilitado por defecto (una instancia sin
plan asignado no bloquea nada) y `aplicar_plan_en_db()` la ajusta cuando
se asigna un plan real. `require_module(nombre)` (`app/modules_gate.py`)
devuelve 403 en los routers gateados si el módulo está deshabilitado;
completar un turno (`POST /appointments/{id}/complete`) nunca se bloquea
por plan — si "facturacion" está deshabilitado simplemente no factura.

## Deploy

Primera infraestructura de deploy de MedLibra (`Dockerfile`,
`docker-compose.yml`, `app/asgi.py`, `scripts/{nuevo_cliente,panel_admin,
npm_api,npm_setup}.py`) — mismo patrón que Contalibra/Restolibra/Gestiolibra
(silo: una instancia + una base SQLite aislada por cliente). A diferencia
de Gestiolibra, MedLibra todavía no tiene frontend, así que el `Dockerfile`
no tiene stage de node — Python puro.

**Reutiliza las mismas deploy keys de LibraCore/LibraGenda que ya usa
Gestiolibra** (mismo ssh-agent multi-key persistente del VPS,
`agent-multi-libra.sock`) — las deploy keys son por-repo-destino, no
por-consumidor, así que no hace falta generar ninguna nueva para esas dos
dependencias:

```bash
LIBRACORE_SSH_KEY=/root/.ssh/agent-multi-libra.sock python3 scripts/panel_admin.py actualizar <cliente>
```

El propio repo MedLibra tiene su propia deploy key dedicada de solo
lectura (`id_ed25519_medlibra`, alias `github-medlibra` en
`~/.ssh/config` del VPS, antes del bloque genérico `Host *`), mismo
patrón que `id_ed25519_gestiolibra`.

`docker-compose.yml` levanta `medlibra-dev` en el puerto `8077` (siguiente
libre después de `gestiolibra-dev` en `8075`/`8076` y antes de
`restolibra-web` en `8079`; puerto base para clientes reales vía
provisioning: `8078`). `scripts/npm_api.py`/`npm_setup.py` (wrappers sobre
`libracore.npm_api`/`libracore.provisioning`) arman el proxy + certificado
por dominio cuando llegue el momento de exponer `dev.medlibra.com.ar`;
reutilizan la misma instancia de NPM y credenciales que ya usan
Contalibra/Restolibra/Gestiolibra (config en `scripts/.npm_config.json`,
gitignoreado).

**Primer deploy real verificado (2026-07-25, ver `DECISIONS.md`
ADR-019)**: imagen `medlibra:latest` construida en el VPS y cliente de
prueba `prueba` (puerto `8078`, plan Premium) dado de alta con
`nuevo_cliente.py` — contenedor healthy, login, endpoint clínico sin
gating y dashboard verificados. Dominio propio
(`dev.medlibra.com.ar` + proxy NPM + SSL) todavía pendiente, ver
`TASKS.md`.

## Documentación

- [ROADMAP.md](ROADMAP.md) — dirección estratégica.
- [TASKS.md](TASKS.md) — trabajo concreto vigente.
- [ARCHITECTURE.md](ARCHITECTURE.md) — arquitectura actual.
- [CONVENTIONS.md](CONVENTIONS.md) — estándares del código.
- [DECISIONS.md](DECISIONS.md) — decisiones y motivos.
- [CHANGELOG.md](CHANGELOG.md) — cambios publicados.
- [MODULES.md](MODULES.md) — inventario de módulos.

## Desarrollo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
DATABASE_URL="sqlite:///./dev-data/medlibra.db" uvicorn app.asgi:app --reload
```

`app/asgi.py` es el entrypoint que usa uvicorn en contenedor (Docker) o
local — lee `DATABASE_URL` del entorno una sola vez al importar, porque
`create_app()` requiere ese argumento y no puede usarse directo como
factory de uvicorn (mismo patrón que Gestiolibra). Las migraciones de
LibraGenda y las propias deben aplicarse (`alembic upgrade head` en ambas
cadenas) antes de iniciar la aplicación real.
