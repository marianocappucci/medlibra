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
- `app/services/prescriptions.py`: recetas médicas — una receta con uno o
  más items (medicamento, dosis, indicaciones), append-only, mismo
  criterio que `clinical_notes` (ver "Recetas" abajo).
- `app/services/users.py`: tabla y repositorio de usuarios propios de
  MedLibra (no pertenecen al dominio de LibraGenda).
- `app/services/branches.py`, `branch_hours.py`, `service_prices.py`,
  `business_settings.py`: configuración comercial del consultorio — mismo
  código que Gestiolibra, portado verbatim (ver "Configuración comercial"
  abajo).
- `app/notifications.py`, `app/payments.py`: implementaciones placeholder
  de los puertos `NotificationPort`/`PaymentPort` de LibraGenda — mismo
  código que Gestiolibra, portado verbatim (ver "Recordatorios y señas"
  abajo).
- `app/routers/`: health (público), auth (login/logout/me), users
  (admin-only), branches (+ horario, + contacto)/resources/services (+
  precio por sucursal)/availability (admin-only), negocio (`/business`),
  patients/clinical_notes/prescriptions (admin+staff, DELETE admin-only),
  appointments/agenda (admin+staff), recordatorios (`/reminders/dispatch`,
  admin-only) y señas (`/appointments/{id}/deposit` admin+staff,
  `/deposits/{id}/...` admin-only).
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

## Recordatorios y señas

Mismo feature que Gestiolibra, mismo día, código portado verbatim (sin
lógica propia del vertical): el dominio ya está resuelto en LibraGenda
(`ReminderDispatcher`/`due_reminders()`, `DepositManager`), lo que faltaba
era conectarlo a un canal real, y todavía no hay uno elegido para
MedLibra tampoco.

- **Recordatorios**: `LoggingNotificationPort` implementa `NotificationPort`
  logueando en vez de enviar. `DEFAULT_REMINDER_POLICIES` (24h y 2h antes,
  fijo) se pasa a `ReminderDispatcher` al construir la app.
  `POST /reminders/dispatch` (admin-only) está pensado para un cron/
  scheduler externo, no hay uno corriendo dentro de este repo.
- **Señas**: `ManualPaymentPort` implementa `PaymentPort`; no cobra ni
  reintegra solo, solo loguea la intención. La confirmación de la seña
  (efectivo, transferencia, link de MercadoPago enviado a mano) la hace un
  admin vía `POST /deposits/{id}/mark-paid`/`mark-failed`/`refund`.
- Ninguna de las dos piezas necesitó una migración nueva: `deposits` y
  `sent_reminders` son tablas propias de LibraGenda, ya migradas por su
  propia cadena. Ver `DECISIONS.md` ADR-010 y la entrada equivalente en
  Gestiolibra (ADR-009 de ese repo) para el detalle completo.

## Recetas

Una receta tiene uno o más items (medicamento, dosis, indicaciones) —
refleja cómo se prescribe en la práctica real, una consulta suele generar
una receta con varios fármacos. Dos tablas propias de MedLibra:
`prescriptions` (header: paciente, autor, fecha) y `prescription_items`
(FK a la receta, con `position` propio — el `id` de cada item es un UUID,
no sirve para ordenar por inserción). **Append-only, mismo criterio que
`clinical_notes`** (ver ADR-006): sin endpoint de actualización, solo
crear/listar/obtener/borrar (el borrado admin-only, para corregir errores
de carga). Borrar un paciente con recetas existentes está bloqueado (409),
mismo mecanismo que ya bloqueaba el borrado con notas clínicas —
`PatientRepository.delete()` chequea ambas tablas. Ver `DECISIONS.md`
ADR-011.

## Dominio clínico vs. motor genérico

LibraGenda no sabe nada de pacientes ni historia clínica — solo conoce
`Client` (identidad genérica para agendar) y `Resource`/`Service`/
`Appointment`. MedLibra extiende esa identidad con lo clínico en sus
propias tablas (`patients`, `clinical_notes`, `prescriptions`/
`prescription_items`), vinculadas por FK al `id` del `Client` — mismo
principio que "no duplicar reglas de LibraGenda" de `CONVENTIONS.md`,
aplicado en la dirección inversa: lo clínico no contamina el motor, vive
enteramente en MedLibra.

## Persistencia e integración

La aplicación configura LibraGenda mediante `LIBRAGENDA_DATABASE_URL` y usa PostgreSQL dedicado para MedLibra. Las migraciones de LibraGenda se ejecutan desde un checkout del repositorio upstream en la versión exacta pineada, antes de iniciar la API; no se usa `create_all()` en producción para las tablas de LibraGenda.

`pyproject.toml` pinea LibraGenda `v0.5.0` (actualizado desde `v0.3.0`, ver
`DECISIONS.md` ADR-004). Las tablas propias de MedLibra (`users`,
`patients`, `clinical_notes`, desde `0004_business_config` también
`branch_contacts`/`branch_hours`/`service_prices`/`business_settings`, y
desde `0005_prescriptions` también `prescriptions`/`prescription_items`)
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
