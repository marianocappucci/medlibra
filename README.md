# MedLibra

Vertical de turnos para salud: consultorios, profesionales independientes y
centros médicos.

Compone:

- LibraGenda `v0.5.0` — agenda, recursos, servicios, ciclo de vida de turnos,
  disponibilidad/bloqueos/excepciones, feriados y timezone por sucursal,
  recurrencias, recordatorios (puerto de notificaciones), señas (puerto de
  pagos) y motivo opcional de cancelación/reprogramación.
- LibraCore — solo `libracore.auth.SessionAuth` por ahora (login por cookie
  firmada, mismo patrón que Gestiolibra); administración/facturación/caja,
  **solo si MedLibra incorpora facturación** (no está decidido).

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
`admin`+`staff`, borrar es admin-only);
`/appointments` (crear/confirmar/cancelar/reprogramar — `admin`+`staff`,
valida contra la disponibilidad real configurada y el horario comercial de
la sucursal si está configurado, cancelar/reprogramar aceptan `reason`
opcional); `/resources/{id}/agenda` (turnos de un profesional en un rango
de fechas); `/reminders/dispatch` (solo `admin`, dispara los recordatorios
vencidos — 24h y 2h antes de cada turno, fijo); y
`/appointments/{id}/deposit` (pedir/consultar una seña, `admin`+`staff`) +
`/deposits/{id}/mark-paid`/`mark-failed`/`refund` (solo `admin`, confirma
el estado de la seña). Evoluciones estructuradas, diagnósticos,
documentos clínicos y consentimientos quedan para fases siguientes.

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

LibraGenda permanece como paquete reutilizable con PostgreSQL dedicado y
migraciones propias — base `medlibra` en el mismo Postgres 16 del VPS Donweb
que aloja la de LibraGenda, migrada con las migraciones del propio paquete
de LibraGenda (no se distribuyen en el wheel de pip, se aplican desde un
checkout de esa versión exacta contra `DATABASE_URL`).

No confundir con los sistemas de salud del Servidor Homei (PACS, Farmacia,
Portal de Pacientes) — son proyectos completamente separados, sin relación
ni infraestructura compartida.

## Migraciones

Dos cadenas de Alembic independientes corren contra la **misma** base
`medlibra`, cada una con su propia tabla de versión (`alembic_version` es
de LibraGenda, `alembic_version_medlibra` es de MedLibra). El deploy corre
ambas, en este orden, antes de levantar la API:

**1. Migraciones de LibraGenda** (schema del motor). No viajan en el wheel
instalado por pip, se aplican clonando el repo en el tag pineado en
`pyproject.toml` (hoy `v0.5.0`):

```bash
LIBRAGENDA_REF=v0.5.0 DATABASE_URL="$DATABASE_URL" \
  bash path/a/libragenda/scripts/run_migrations.sh
```

**2. Migraciones propias de MedLibra** (`users`, `patients`,
`clinical_notes`, `branch_contacts`, `branch_hours`, `service_prices`,
`business_settings`, `prescriptions`, `prescription_items`,
`study_orders`, `study_order_items`, `study_results` — no pertenecen al
dominio de LibraGenda, ver `MODULES.md`). Viajan en este mismo repo:

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
(LibraGenda + propia) contra un Postgres 16 de servicio, mismo orden que
un deploy real.

**Requiere un secret `LIBRA_PAT`** en este repo (Settings → Secrets and
variables → Actions): `libragenda` y `libracore` son privados, y el
`GITHUB_TOKEN` automático de Actions no tiene acceso a otros repos. Crear
un fine-grained PAT en <https://github.com/settings/tokens?type=beta>
scoped **solo** a `libragenda` y `libracore`, permiso **Contents:
Read-only**, y cargarlo como ese secret (mismo token se puede reusar en
Gestiolibra, cargándolo como secret ahí también — los secrets no se
comparten automáticamente entre repos). Sin este secret, el paso "Install
package + dev deps" falla (no un bug del workflow).

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
uvicorn app.main:app --reload
```

La base PostgreSQL y las migraciones de LibraGenda deben estar configuradas
antes de iniciar la aplicación real.
