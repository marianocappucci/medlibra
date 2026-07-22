# Módulos de MedLibra

## Implementados

- `app/main.py`: factory FastAPI — configura LibraGenda, arma repos/servicios
  en `app.state`, monta routers.
- `app/dependencies.py`: providers de FastAPI que leen `app.state`.
- `app/services/appointments.py`: `AppointmentService` — capa de aplicación
  sobre `InMemoryScheduler` de LibraGenda. Lee la disponibilidad real del
  recurso (ventanas + bloqueos + excepciones) en vez de una ventana
  hardcodeada; `cancel()`/`reschedule()` aceptan `reason` opcional (motivo
  agregado en LibraGenda `v0.5.0`); `agenda()` filtra turnos por rango de
  fechas.
- `app/services/patients.py`: `PatientRepository` — coordina el `Client`
  genérico de LibraGenda (identidad/agenda) con la extensión clínica propia
  de MedLibra (`PatientRow`: `dni`, `birth_date`), dos tablas mantenidas en
  sync en el borde de la API en vez de mezclarse en una sola. `delete()`
  rechaza (409, vía `PatientHasClinicalNotes`) borrar un paciente que
  todavía tiene notas de historia clínica — sin esto, en PostgreSQL
  violaría la FK de `clinical_notes`, y en SQLite (sin FK forzada por
  default) las dejaría huérfanas silenciosamente.
- `app/services/clinical_notes.py`: `ClinicalNoteRepository` — historia
  clínica básica: notas de evolución en texto libre por paciente
  (`id`, `patient_id`, `created_at`, `author`, `text`). **Append-only por
  diseño**: no hay método de update, solo `create`/`get`/`list_by_patient`/
  `delete` (esta última pensada para corregir errores de carga, no para
  edición). Diagnósticos estructurados, estudios y consentimientos quedan
  para el resto de la Fase 2 (ver `ROADMAP.md`).
- `app/services/prescriptions.py`: `PrescriptionRepository` — recetas
  médicas por paciente. Una receta tiene uno o más items (medicamento,
  dosis, indicaciones) — `PrescriptionRow` (header: paciente, autor, fecha)
  + `PrescriptionItemRow` (FK a la receta, con `position` propio porque el
  `id` es un UUID y no sirve para ordenar). **Append-only, mismo criterio
  que `clinical_notes`**: sin update, solo `create`/`get`/`list_by_patient`/
  `delete` (admin-only, para errores de carga). `create()` exige al menos
  un item.
- `app/services/study_orders.py`: `StudyOrderRepository` — pedidos de
  estudios/análisis por paciente. Un pedido tiene uno o más items (tipo de
  estudio, motivo) — `StudyOrderRow` (header) + `StudyOrderItemRow` (con
  `position` propio, mismo motivo que en recetas). Cada item puede tener
  uno o más resultados propios (`StudyResultRow`, FK al item): el resultado
  es un registro nuevo vinculado al item cuando llega, nunca una edición
  del pedido — **append-only en las tres capas** (pedido, item, resultado),
  mismo criterio que `clinical_notes`/`prescriptions`. `create()` exige al
  menos un item.
- `app/services/clinical_documents.py`: `ClinicalDocumentRepository` —
  archivos adjuntos por paciente (informes externos, estudios escaneados).
  Solo metadata en la base (`title`, `description`, `original_filename`,
  `content_type`, `size_bytes`); el archivo vive en filesystem local bajo
  `MEDLIBRA_DOCUMENTS_DIR`, con nombre en disco normalizado (UUID + ext,
  nunca el nombre original) para evitar path traversal/colisiones — mismo
  patrón ya probado en Contalibra/Restolibra (`web/routers/config.py`),
  sin sumar S3/MinIO. Se vincula solo al paciente, no a un registro
  puntual. `delete()` borra la fila y el archivo del disco.
- `app/services/consents.py`: `ConsentRepository` — consentimientos
  informados por paciente (`procedure`, `granted_by` — paciente o tutor/
  responsable —, `text` con el detalle acordado). **Append-only, sin
  revocación editable**: un consentimiento es un hecho histórico; si el
  paciente retira su consentimiento más adelante, se carga un registro
  nuevo (no hay endpoint de update ni de estado). Sin archivo adjunto
  embebido — el PDF firmado escaneado, si hace falta, se sube aparte
  como documento clínico.
- `app/auth.py`: reusa `libracore.auth.SessionAuth` (cookie firmada, ya
  probada en producción por Contalibra/Restolibra/Gestiolibra) para la
  mecánica de sesión — con dependencias FastAPI propias
  (`get_current_user`, `require_role`) que devuelven 401/403 JSON en vez de
  los redirects 307 de `SessionAuth.require_auth`/`require_role` (pensados
  para una app server-rendered, no para esta API JSON pura).
- `app/security.py`: hashing de contraseñas PBKDF2, mismo algoritmo que
  `libracore.db.usuarios` y que Gestiolibra (ver `DECISIONS.md`
  de ese repo, ADR-005) — reimplementado en vez de importar las funciones
  privadas (prefijo `_`) de ese módulo, no pensado para reuso directo
  (razón que se sostiene aunque ambos usen SQLite hoy).
- `app/services/users.py`: `UserRow` (tabla propia de MedLibra) +
  `UserRepository` + `ensure_default_admin()` (bootstrap fail-closed, igual
  criterio que `SECRET_KEY`: sin `MEDLIBRA_ADMIN_PASSWORD` la app no
  levanta, salvo `ENV=development`).
- Roles: `admin` (CRUD completo de sucursales/recursos/servicios/
  disponibilidad/usuarios; único que puede borrar pacientes o notas
  clínicas) y `staff` (personal médico — crea/lee/actualiza pacientes,
  escribe historia clínica, gestiona turnos; **no** puede borrar pacientes
  ni notas, ni tocar catálogo/usuarios). A diferencia de Gestiolibra, donde
  `staff` solo toca turnos: acá el personal médico necesita acceso clínico
  para hacer su trabajo, así que `patients`/`clinical_notes`/`prescriptions`/
  `study_orders`/`clinical_documents`/`consents` están gateados a
  `admin`+`staff` con un `Depends(require_admin)` extra solo en los
  endpoints `DELETE`.
- `app/services/branches.py`, `branch_hours.py`, `service_prices.py`,
  `business_settings.py`: configuración comercial del consultorio, todas
  tablas propias de MedLibra — mismo feature, mismo código (portado
  verbatim), ya construido para Gestiolibra el mismo día.
- `app/notifications.py`, `app/payments.py`: implementaciones placeholder de
  los puertos `NotificationPort`/`PaymentPort` de LibraGenda — mismo
  feature, mismo código que Gestiolibra, portado verbatim. Ver
  "Recordatorios y señas" en `ARCHITECTURE.md`.
- `app/routers/`: `health.py` (público), `auth.py` (`/auth/login`,
  `/auth/logout`, `/auth/me`), `users.py` (CRUD de usuarios, admin-only),
  `branches.py` (CRUD de sucursales, incluye teléfono/dirección),
  `branch_hours.py` (`/branches/{id}/hours` — horario comercial, opt-in),
  `resources.py`, `services.py` (CRUD completo, admin-only),
  `service_prices.py` (`/services/{id}/prices` — precio por servicio y
  sucursal), `business_settings.py` (`/business` — nombre comercial y
  moneda, singleton), `availability.py` (CRUD de ventanas/bloqueos/
  excepciones, admin-only), `patients.py` (CRUD completo, admin+staff
  salvo `DELETE`), `clinical_notes.py` (`/patients/{id}/notes`,
  admin+staff salvo `DELETE`), `prescriptions.py` (`/patients/{id}/prescriptions`,
  admin+staff salvo `DELETE`), `study_orders.py`
  (`/patients/{id}/study-orders` y `/patients/{id}/study-orders/{order_id}/items/{item_id}/results`,
  admin+staff salvo `DELETE`), `clinical_documents.py`
  (`/patients/{id}/documents` — subida multipart + descarga vía
  `/{document_id}/file`, admin+staff salvo `DELETE`), `consents.py`
  (`/patients/{id}/consents`, admin+staff salvo `DELETE`),
  `appointments.py` (crear/confirmar/
  cancelar/reprogramar, admin+staff — `create`/`reschedule` validan
  además el horario comercial si está configurado), `agenda.py`
  (admin+staff), `reminders.py` (`/reminders/dispatch`, admin-only),
  `deposits.py` (`/appointments/{id}/deposit` admin+staff,
  `/deposits/{id}/mark-paid`/`mark-failed`/`refund` admin-only) —
  traducen excepciones de dominio a códigos HTTP (404/409/422).
  `/demo/seed` fue reemplazado por el CRUD real.

## Próximos

- `billing` (opcional, no decidido): composición de LibraCore para facturación/caja.

## Después del MVP

- Canal real de notificaciones (email/SMS/WhatsApp) para reemplazar
  `LoggingNotificationPort`.
- Proveedor de pago real para reemplazar `ManualPaymentPort` y automatizar
  la confirmación de señas.
- Dashboard y reportes operativos.

## Fuera de alcance

Turnos genéricos no clínicos (Gestiolibra), mesas, comandas, cocina y food
cost (Restolibra), sistemas del Servidor Homei (PACS, Farmacia, Portal de
Pacientes — proyectos separados sin relación con MedLibra).
