# Roadmap de MedLibra

## Fase 0 — scaffold (completa)

Repo privado, FastAPI, dependencia LibraGenda `v0.3.0`, PostgreSQL dedicado
real (base `medlibra`, usuario `medlibra_dev`, Postgres 16 del VPS Donweb)
migrado con la cadena Alembic completa de LibraGenda y verificado end-to-end
con los repositorios SQLAlchemy reales — no solo un smoke test sqlite del
demo. Cierra el ítem "MedLibra consume el mismo contrato sin contaminar el
motor con clínica" de la Fase 3 del roadmap de LibraGenda.

## Fase 1 — MVP operativo (completa)

- Separar el demo en routers y servicios de aplicación (completo).
  `app/routers/` (health, patients, clinical_notes, appointments) +
  `app/services/` (`AppointmentService`, `PatientRepository`,
  `ClinicalNoteRepository`) + `app/dependencies.py`.
- Definir el dominio clínico propio: paciente, historia clínica básica
  (completo). Paciente = `Client` de LibraGenda + extensión propia (`dni`,
  `birth_date`) en tabla `patients`. Historia clínica = notas de evolución
  en texto libre por paciente, append-only (sin update; borrar un paciente
  con notas está bloqueado). Diagnósticos estructurados, recetas, estudios
  y consentimientos quedan para Fase 2. Ver `DECISIONS.md` ADR-005/006.
- CRUD de profesionales y consultorios (completo). Routers `branches`,
  `resources`, `services` — mismo código, verbatim, que ya probó
  Gestiolibra (genéricos, sin lógica propia del vertical). `/demo/seed`
  reemplazado.
- Agenda diaria/semanal y disponibilidad configurable por profesional
  (completo). `/resources/{id}/availability`/`/blocks`/`/exceptions` — CRUD
  completo. `AppointmentService.create()`/`reschedule()` dejaron de usar la
  ventana 9-18 hardcodeada, leen la disponibilidad real configurada.
  `/resources/{id}/agenda` devuelve los turnos del profesional en un rango.
- Cancelar y reprogramar con motivos (completo). `POST /appointments/{id}/cancel`
  y `POST /appointments/{id}/reschedule`, ambos con `reason` opcional —
  mismo patrón que Gestiolibra, usando el campo que LibraGenda agregó en
  `v0.5.0`.
- Login y roles básicos (completo). Reusa `libracore.auth.SessionAuth`
  (mismo patrón que Gestiolibra), con tabla `users` propia. Dos roles:
  `admin` (todo) y `staff` (personal médico — turnos + acceso clínico
  completo a pacientes/historia clínica salvo borrar, **a diferencia de
  Gestiolibra** donde `staff` solo toca turnos — acá el rol clínico
  necesita ver/escribir historia clínica para hacer su trabajo). Ver
  `DECISIONS.md` ADR-007.

Con esto, MedLibra alcanza paridad funcional con Gestiolibra sobre
LibraGenda, más su propio dominio clínico encima.

## Fase 2 — operación clínica (en curso)

- Configuración comercial del consultorio (completo). Mismo alcance y
  mismo código que Gestiolibra (portado verbatim, sin lógica propia del
  vertical): horario comercial por sucursal (`branch_hours`, opt-in),
  precio por servicio y sucursal (`service_prices`), contacto de
  sucursal (`branch_contacts`: teléfono, dirección) y datos globales del
  negocio (`business_settings`: nombre comercial, moneda). Migración
  `0004_business_config` en el Alembic propio de MedLibra.
  `AppointmentService.create()`/`reschedule()` validan el horario
  comercial cuando está configurado.
- Recordatorios y señas (completo). Mismo alcance y mismo código que
  Gestiolibra, portado verbatim el mismo día: `POST /reminders/dispatch`
  (admin-only, avisos 24h y 2h antes, fijo) sobre `ReminderDispatcher` de
  LibraGenda; `POST`/`GET /appointments/{id}/deposit` (admin+staff) y
  `POST /deposits/{id}/mark-paid`/`mark-failed`/`refund` (admin-only)
  sobre `DepositManager` de LibraGenda. Sin proveedor de notificaciones ni
  de pago todavía: `NotificationPort`/`PaymentPort` implementados como
  placeholders (`LoggingNotificationPort`, `ManualPaymentPort`) — ver
  `DECISIONS.md` ADR-010. Sin migración nueva (`deposits`/`sent_reminders`
  son tablas de LibraGenda, ya migradas por su propia cadena).
- Recetas (completo). El usuario eligió este ítem entre el resto de la
  Fase 2 (`AskUserQuestion`) y definió el alcance concreto: una receta
  puede tener varios items (medicamento, dosis, indicaciones) — no un
  medicamento por receta — y es append-only, sin ciclo de vida propio
  (igual que `clinical_notes`, la dispensa es resorte de la farmacia, no
  de MedLibra). `POST`/`GET /patients/{id}/prescriptions` (admin+staff),
  `DELETE` admin-only. Migración `0005_prescriptions`. Ver `DECISIONS.md`
  ADR-011.
- Estudios, documentos clínicos, consentimientos.
- Facturación/caja, solo si se decide incorporar LibraCore.
- Dashboard y reportes.

## Fase 3 — producto

- Onboarding multi-consultorio/centro médico.
- Branding y dominio por cliente.
- Deploy dev/prod, CI y backups verificados.
- Validación con primeros consultorios reales.
