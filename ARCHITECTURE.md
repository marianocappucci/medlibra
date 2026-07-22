# Arquitectura — MedLibra

## Propósito y límites

MedLibra será el producto vertical de turnos y gestión clínica para consultorios, profesionales independientes y centros médicos.

LibraGenda aporta el motor genérico de agenda. MedLibra debe mantener el dominio clínico propio — pacientes, historia clínica, evoluciones y diagnósticos — separado del motor común.

No confundir con PACS, Farmacia ni Portal de Pacientes del Servidor Homei; son proyectos separados y no comparten infraestructura.

## Componentes

- `app/main.py`: factory FastAPI, configuración y composición de dependencias.
  Aplica el gating por rol a nivel de router (`include_router(..., dependencies=[...])`),
  con un `Depends(require_admin)` extra en los endpoints `DELETE` de
  pacientes/notas clínicas (ver "Roles" abajo).
- `app/dependencies.py`: providers que leen el estado de la aplicación.
- `app/auth.py`: sesión por cookie firmada (reusa `libracore.auth.SessionAuth`,
  mismo patrón que [[gestiolibra]]) + dependencias FastAPI propias
  (`get_current_user`, `require_role`) que responden 401/403 JSON.
- `app/security.py`: hashing de contraseñas (PBKDF2, mismo algoritmo que
  `libracore.db.usuarios` y que Gestiolibra).
- `app/services/appointments.py`: capa de aplicación sobre LibraGenda
  (turnos, disponibilidad real configurable, cancelar/reprogramar con
  motivo). `create()`/`reschedule()` validan además el horario comercial
  de la sucursal del recurso (`branch_hours`), cuando está configurado.
- `app/services/patients.py`: pacientes — extensión clínica (`dni`,
  `birth_date`) del `Client` genérico de LibraGenda, coordinada en el borde
  de la API, no mezclada en el schema del motor.
- `app/services/clinical_notes.py`: historia clínica básica — notas de
  evolución en texto libre, append-only (sin update).
- `app/services/users.py`: tabla y repositorio de usuarios propios de
  MedLibra (no pertenecen al dominio de LibraGenda).
- `app/services/branches.py`, `branch_hours.py`, `service_prices.py`,
  `business_settings.py`: configuración comercial del consultorio — mismo
  código que Gestiolibra, portado verbatim (ver "Configuración comercial"
  abajo).
- `app/routers/`: health (público), auth (login/logout/me), users
  (admin-only), branches (+ horario, + contacto)/resources/services (+
  precio por sucursal)/availability (admin-only), negocio (`/business`),
  patients/clinical_notes (admin+staff, DELETE admin-only), appointments/
  agenda (admin+staff).
- `MODULES.md`: inventario operativo de módulos.
- LibraGenda `v0.5.0`: dependencia versionada para dominio, persistencia y
  migraciones propias.
- LibraCore: dependencia versionada solo por `libracore.auth.SessionAuth`
  (facturación/caja sigue sin decidir, ver `DECISIONS.md` ADR-003).

## Roles

Dos roles, distintos de Gestiolibra por una razón de dominio real: en
Gestiolibra `staff` solo toca turnos, pero en MedLibra el personal médico
(`staff`) necesita leer y escribir historia clínica para hacer su trabajo.
`admin` tiene acceso completo (catálogo, disponibilidad, usuarios, y es el
único que puede borrar pacientes o notas clínicas — la historia clínica es
append-only por diseño, ver ADR-006, así que hasta el borrado admin-only es
una excepción pensada solo para corregir errores de carga, no para editar
contenido). `staff` gestiona turnos y pacientes/historia clínica sin poder
borrar ninguno de los dos.

## Configuración comercial

Mismo feature que Gestiolibra, mismo día, código portado verbatim (sin
lógica propia del vertical): horario comercial por sucursal (opt-in — sin
configurar no gatea nada), precio por servicio y sucursal (LibraGenda no
conoce precios por diseño, un servicio puede costar distinto por
consultorio), y contacto de sucursal + datos globales del negocio. Ver
`DECISIONS.md` ADR-009 y la entrada equivalente en Gestiolibra (ADR-008
de ese repo) para el detalle completo de las decisiones de diseño.

## Dominio clínico vs. motor genérico

LibraGenda no sabe nada de pacientes ni historia clínica — solo conoce
`Client` (identidad genérica para agendar) y `Resource`/`Service`/
`Appointment`. MedLibra extiende esa identidad con lo clínico en sus
propias tablas (`patients`, `clinical_notes`), vinculadas por FK al `id`
del `Client` — mismo principio que "no duplicar reglas de LibraGenda" de
`CONVENTIONS.md`, aplicado en la dirección inversa: lo clínico no
contamina el motor, vive enteramente en MedLibra.

## Persistencia e integración

La aplicación configura LibraGenda mediante `LIBRAGENDA_DATABASE_URL` y usa PostgreSQL dedicado para MedLibra. Las migraciones de LibraGenda se ejecutan desde un checkout del repositorio upstream en la versión exacta pineada, antes de iniciar la API; no se usa `create_all()` en producción para las tablas de LibraGenda.

`pyproject.toml` pinea LibraGenda `v0.5.0` (actualizado desde `v0.3.0`, ver
`DECISIONS.md` ADR-004). Las tablas propias de MedLibra (`users`,
`patients`, `clinical_notes`, y desde `0004_business_config` también
`branch_contacts`/`branch_hours`/`service_prices`/`business_settings`)
tienen su propio Alembic (`migrations/` de este repo), cadena independiente
de la de LibraGenda con su propia tabla de versión (`alembic_version_medlibra`,
para no colisionar sobre la misma base física — ver `DECISIONS.md` ADR-008).
`Base.metadata.create_all()`
sigue en `create_app()` pero solo importa para los tests con SQLite en
memoria; en producción es un no-op una vez que ambas cadenas de Alembic ya
crearon el schema real.

## Entornos y deploy

- Desarrollo: entorno dev con base `medlibra` y usuario dedicado.
- Demo: producción controlada para validación.
- Producción: dominio del cliente.

La rama observada actualmente es `main`. La adopción de `develop` como rama de integración queda pendiente de una decisión operativa explícita.
