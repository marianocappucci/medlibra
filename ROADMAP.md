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
- Estudios (completo). El usuario eligió este ítem entre el resto de la
  Fase 2 y definió el alcance concreto (`AskUserQuestion`): un pedido de
  estudios puede tener varios items (análisis de sangre, radiografía,
  etc.), y cada item puede tener uno o más resultados propios como
  registros separados vinculados al item — nunca se edita el pedido
  original, mismo espíritu append-only que recetas/notas clínicas.
  `POST`/`GET /patients/{id}/study-orders` y
  `POST /patients/{id}/study-orders/{order_id}/items/{item_id}/results`
  (admin+staff), `DELETE` de pedido o resultado admin-only. Migración
  `0006_study_orders`. Ver `DECISIONS.md` ADR-012.
- Documentos clínicos (completo). El usuario eligió este ítem entre el
  resto de la Fase 2 y definió el alcance concreto (`AskUserQuestion`):
  almacenamiento en filesystem local (mismo patrón ya probado en
  Contalibra/Restolibra, sin sumar S3/MinIO) y un documento se vincula
  solo al paciente, no a un registro puntual. `POST /patients/{id}/documents`
  (multipart: archivo + título + descripción opcional + autor),
  `GET`/`DELETE` (admin+staff, DELETE admin-only), descarga vía
  `GET /patients/{id}/documents/{document_id}/file`. Formatos aceptados:
  PDF/PNG/JPG/JPEG, hasta 20MB. Migración `0007_clinical_documents`. Ver
  `DECISIONS.md` ADR-013.
- Consentimientos informados (completo). El usuario eligió este ítem
  entre el resto de la Fase 2 y definió el alcance concreto
  (`AskUserQuestion`): solo el registro (procedimiento, quién autoriza —
  paciente o tutor/responsable —, texto libre), sin archivo firmado
  embebido (si hace falta, se sube aparte como documento clínico); y
  append-only sin revocación editable — retirar un consentimiento se
  registra como un consentimiento nuevo, nunca editando el original.
  `POST`/`GET /patients/{id}/consents`, `DELETE` admin-only. Migración
  `0008_consents`. Ver `DECISIONS.md` ADR-014.

Con esto, el dominio clínico completo de la Fase 2 (configuración
comercial, recordatorios/señas, recetas, estudios, documentos clínicos y
consentimientos) queda cerrado. Quedan pendientes de Fase 2 solo las
decisiones no clínicas: facturación/caja (si se incorpora LibraCore) y
dashboard/reportes.
- SQLite como destino de producción por defecto (completo). Al scopear
  facturación con LibraCore salió a la luz que Contalibra/Restolibra
  despliegan con arquitectura silo real (instancia + SQLite aislada por
  cliente) y que MedLibra ya prevé el mismo patrón — mantenerlo en
  Postgres no aportaba nada y complicaba cualquier composición futura
  con LibraCore (SQLite-only). LibraGenda actualizado a `v0.6.0`
  (`PRAGMA foreign_keys=ON` automático en SQLite). Bug real corregido de
  paso: `BranchRepository.delete()` con orden de borrado invertido
  (mismo patrón que `PatientRepository`, portado verbatim desde
  Gestiolibra). `DELETE` de sucursales/recursos/servicios ahora 409 en
  vez de 500 con dependientes. Postgres sigue soportado. Ver
  `DECISIONS.md` ADR-015.
- Facturación/caja con LibraCore (completo). Retomada y cerrada el mismo
  día que se pausó: LibraGenda expone `complete()` (`v0.7.0`) y
  `Deposit.medio_pago` opcional (`v0.8.0`); LibraCore extrae la
  orquestación de numeración/CAE a `libracore.arca_facturacion`
  (`v0.16.1`, Contalibra/Restolibra migrados a un shim sobre ese
  módulo); MedLibra agrega CUIT/condición de IVA al paciente
  (migración `0009`), config ARCA de instancia única
  (`PUT`/`GET /config/arca`) y `POST /appointments/{id}/complete` —
  una sola factura por turno completado (tipo A/B según condición de
  IVA), seña y saldo como dos movimientos de caja separados apuntando
  a la misma factura. Ver `DECISIONS.md` ADR-016. Credenciales ARCA
  reales y revisión del cálculo de IVA con un contador quedan
  pendientes (ver `TASKS.md`) — el modo mock (`ENV=development`) ya
  funciona de punta a punta.
- Dashboard (completo, primer corte). Alcance elegido por el usuario
  (`AskUserQuestion`): turnos (total y por estado en un rango, turnos
  de hoy), pacientes (total activos, altas nuevas en el rango) y
  recordatorios enviados/señas pendientes — facturación/caja queda
  fuera de este corte, para una entrega futura. `GET /dashboard?
  date_from=&date_to=` (admin-only), puro de lectura sobre repositorios
  ya existentes más dos métodos nuevos en LibraGenda (`v0.9.0`:
  `SentReminderRepository.list_sent()`/`DepositRepository.
  list_by_status()`). Ver `DECISIONS.md` ADR-017. Con esto, Fase 2
  queda completa.

## Fase 3 — producto

- Onboarding multi-consultorio/centro médico (completo — ver
  ADR-018/ADR-019). Sistema de planes con enforcement real: todo el
  dominio clínico (pacientes, historia clínica, recetas, estudios,
  documentos, consentimientos) siempre libre, mismo criterio que
  "turnos nunca se gatea" en Gestiolibra extendido a lo clínico —
  Básico/Estándar/Premium ($25k/$40k/$60k) solo varían en
  recordatorios/señas/facturación/dashboard. `plans.py` + tabla
  `modulos` (migración `0011_modulos`) + `require_module()`, mismo
  patrón exacto que Gestiolibra. Primera infraestructura de deploy de
  MedLibra (`Dockerfile` sin stage de frontend, `docker-compose.yml`,
  `app/asgi.py`, `scripts/{nuevo_cliente,panel_admin,npm_api,npm_setup}.py`),
  reutilizando las deploy keys de LibraCore/LibraGenda ya cargadas en el
  VPS para Gestiolibra + una deploy key propia nueva
  (`id_ed25519_medlibra`). Build real de imagen Docker y primera alta
  de cliente de prueba (`prueba`, puerto 8078, plan Premium) verificados
  en el VPS — contenedor healthy, login, endpoint clínico sin gating y
  dashboard funcionando.
- Branding y dominio por cliente (completo para dev — ver ADR-020).
  `medlibra-dev` levantado por primera vez contra el VPS (puerto 8077).
  `dev.medlibra.com.ar` con proxy NPM + certificado Let's Encrypt real,
  reutilizando la misma instancia de NPM que ya usan Contalibra/
  Restolibra/Gestiolibra (DNS ya apuntaba al VPS, sin tocar). Dominio
  por cliente real (no solo dev) queda pendiente de un primer cliente
  real, mismo criterio que Gestiolibra.
- Deploy dev/prod, CI y backups verificados (completo). Backups
  probados de punta a punta contra el cliente real `prueba` (paciente
  marcador → backup → mutación → restore → confirmado que vuelve el
  dato original), mismo proceso que Gestiolibra.
- Validación con primeros consultorios reales (pendiente).
