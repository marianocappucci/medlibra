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
- `app/services/study_orders.py`: pedidos de estudios/análisis — un pedido
  con uno o más items (tipo de estudio, motivo), cada uno con uno o más
  resultados propios como registros separados, append-only en las tres
  capas (ver "Estudios" abajo).
- `app/services/clinical_documents.py`: archivos adjuntos por paciente —
  metadata en la base, archivo en filesystem local (ver "Documentos
  clínicos" abajo).
- `app/services/consents.py`: consentimientos informados — procedimiento,
  quién autoriza, texto libre, append-only sin revocación editable (ver
  "Consentimientos" abajo).
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
  patients/clinical_notes/prescriptions/study_orders/clinical_documents/
  consents (admin+staff, DELETE admin-only), appointments/agenda
  (admin+staff), recordatorios (`/reminders/dispatch`, admin-only) y
  señas (`/appointments/{id}/deposit` admin+staff, `/deposits/{id}/...`
  admin-only).
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

## Estudios

Un pedido de estudios tiene uno o más items (análisis de sangre,
radiografía, etc.) — mismo patrón que recetas, una consulta suele generar
un pedido con varios estudios a la vez. Tres tablas propias de MedLibra:
`study_orders` (header: paciente, autor, fecha), `study_order_items` (FK
al pedido, con `position` propio) y `study_results` (FK al item, no al
pedido — cada estudio produce su propio resultado, que puede llegar en un
momento distinto al de los demás items del mismo pedido).
**Append-only en las tres capas**: agregar un resultado nunca edita el
pedido ni el item, es un registro nuevo vinculado al item — mismo
espíritu que `clinical_notes`/`prescriptions` (ver ADR-006/ADR-011). Un
item puede tener más de un resultado (ej. un resultado ampliado o
corregido más adelante, sin sobreescribir el anterior). Borrar un
paciente con pedidos de estudios existentes está bloqueado (409), mismo
mecanismo que ya bloqueaba el borrado con notas/recetas —
`PatientRepository.delete()` chequea las tres tablas. Ver `DECISIONS.md`
ADR-012.

## Documentos clínicos

Archivos adjuntos por paciente (informes externos, estudios escaneados,
cualquier PDF/imagen que traiga el paciente). Un documento se vincula
**solo al paciente** — no a un registro puntual (nota, receta, pedido de
estudio) — decisión explícita del usuario. Ningún repo de LibraGenda/
Gestiolibra/MedLibra manejaba archivos todavía; se replicó el patrón ya
probado en Contalibra/Restolibra (`web/routers/config.py`: directorio
dedicado + `open(...,"wb")`) en vez de introducir S3/MinIO, sin precedente
en ningún producto Libra:

- **Solo metadata en la base** (`clinical_documents`: `title`,
  `description`, `original_filename`, `content_type`, `size_bytes`); el
  archivo vive en filesystem bajo `MEDLIBRA_DOCUMENTS_DIR` (default
  `./data/medlibra_documents`, mismo patrón que `DATA_DIR` de Contalibra).
- **Nombre en disco normalizado** (UUID + extensión), nunca el nombre
  original del usuario — evita path traversal y colisiones. El nombre
  original se guarda como metadata para mostrarlo/descargarlo tal cual.
- `POST /patients/{id}/documents` recibe `multipart/form-data`
  (`UploadFile` + campos `Form`), a diferencia del resto de la API que es
  JSON puro — inevitable para subir un archivo binario. Formatos
  aceptados: PDF/PNG/JPG/JPEG (422 si no matchea), hasta 20MB (422 si se
  excede).
- `GET /patients/{id}/documents/{document_id}/file` sirve el archivo con
  `FileResponse`, gateado por el mismo rol que el resto del router (no
  `StaticFiles` directo, que no tiene auth) — mismo criterio que
  Contalibra sirve su logo.
- `delete()` borra la fila y el archivo del disco (no soft-delete).
  Borrar un paciente con documentos existentes está bloqueado (409),
  mismo mecanismo que ya bloqueaba el borrado con notas/recetas/estudios
  — `PatientRepository.delete()` chequea las cuatro tablas.

Ver `DECISIONS.md` ADR-013.

## Consentimientos

Registro de que se otorgó consentimiento informado para un procedimiento:
`procedure`, `granted_by` (paciente, o nombre y relación de un tutor/
responsable si aplica) y `text` con el detalle acordado en texto libre.
**Solo el registro, sin archivo firmado embebido** — decisión explícita
del usuario: si hace falta el PDF firmado escaneado, se sube aparte como
documento clínico (`/patients/{id}/documents`), sin acoplar ambas
features. **Append-only, sin revocación editable** — mismo criterio que
el resto del dominio clínico: un consentimiento es un hecho histórico
(se otorgó tal día, para tal procedimiento); si el paciente cambia de
opinión más adelante, se registra un consentimiento **nuevo** que deja
constancia del retiro, nunca se edita ni se borra el original (el
`DELETE` sigue existiendo, admin-only, pero es para corregir errores de
carga, no para revocar). Sin endpoint de transición de estado: a
diferencia de una receta o un pedido de estudios, un consentimiento no
tiene ciclo de vida propio en absoluto, ni siquiera implícito. Borrar un
paciente con consentimientos existentes está bloqueado (409), mismo
mecanismo que ya bloqueaba el borrado con notas/recetas/estudios/
documentos — `PatientRepository.delete()` chequea las cinco tablas. Ver
`DECISIONS.md` ADR-014.

## Dominio clínico vs. motor genérico

LibraGenda no sabe nada de pacientes ni historia clínica — solo conoce
`Client` (identidad genérica para agendar) y `Resource`/`Service`/
`Appointment`. MedLibra extiende esa identidad con lo clínico en sus
propias tablas (`patients`, `clinical_notes`, `prescriptions`/
`prescription_items`, `study_orders`/`study_order_items`/`study_results`,
`clinical_documents`, `consents`), vinculadas por FK al `id` del `Client`
— mismo principio que "no duplicar reglas de LibraGenda" de
`CONVENTIONS.md`, aplicado en la dirección inversa: lo clínico no
contamina el motor, vive enteramente en MedLibra.

## Persistencia e integración

La aplicación configura LibraGenda mediante `LIBRAGENDA_DATABASE_URL` y usa PostgreSQL dedicado para MedLibra. Las migraciones de LibraGenda se ejecutan desde un checkout del repositorio upstream en la versión exacta pineada, antes de iniciar la API; no se usa `create_all()` en producción para las tablas de LibraGenda.

`pyproject.toml` pinea LibraGenda `v0.5.0` (actualizado desde `v0.3.0`, ver
`DECISIONS.md` ADR-004). Las tablas propias de MedLibra (`users`,
`patients`, `clinical_notes`, desde `0004_business_config` también
`branch_contacts`/`branch_hours`/`service_prices`/`business_settings`,
desde `0005_prescriptions` también `prescriptions`/`prescription_items`,
desde `0006_study_orders` también `study_orders`/`study_order_items`/
`study_results`, desde `0007_clinical_documents` también
`clinical_documents`, y desde `0008_consents` también `consents`) tienen
su propio Alembic (`migrations/` de este repo), cadena independiente
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
