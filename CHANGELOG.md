# Changelog — MedLibra

## [Unreleased]

- **Onboarding multi-consultorio: planes con enforcement real +
  infraestructura de deploy**: `plans.py` (Básico/Estándar/Premium,
  $25k/$40k/$60k) — todo el dominio clínico siempre libre, solo
  recordatorios/señas/facturación/dashboard son gateables por plan.
  Tabla `modulos` (migración `0011_modulos`), `require_module()`
  (`app/modules_gate.py`). `Dockerfile`/`docker-compose.yml`/
  `app/asgi.py`/`scripts/{nuevo_cliente,panel_admin,npm_api,npm_setup}.py`
  — primera infraestructura de deploy de MedLibra, mismo patrón que
  Gestiolibra sin stage de frontend. Primer deploy real al VPS: deploy
  key propia (`id_ed25519_medlibra`), imagen `medlibra:latest`
  construida, cliente de prueba `prueba` (puerto 8078, plan Premium)
  dado de alta y verificado (healthy, login, endpoint clínico sin
  gating, dashboard). `medlibra-dev` levantado por primera vez (puerto
  8077) y `dev.medlibra.com.ar` con proxy NPM + certificado Let's
  Encrypt real. Backups (`panel_admin.py backup`/`restore-db`)
  verificados de punta a punta contra el cliente `prueba`. Ver
  `DECISIONS.md` ADR-018/ADR-019/ADR-020.
- **Dashboard**: `GET /dashboard?date_from=&date_to=` (admin-only) —
  turnos (total y por estado en el rango, turnos de hoy), pacientes
  (total activos, altas nuevas en el rango vía `patients.created_at`
  nuevo, migración `0010_patient_created_at`) y recordatorios enviados/
  señas pendientes. Facturación/caja queda para una entrega futura
  (decisión del usuario). `libragenda` a `v0.9.0` (agrega
  `list_sent()`/`list_by_status()`). Ver `DECISIONS.md` ADR-017.
- **Facturación/caja con LibraCore**: CUIT/condición de IVA como
  extensión del paciente (migración `0009_patient_billing_fields`),
  `PUT`/`GET /config/arca` (config ARCA de instancia única, admin-only),
  `POST /appointments/{id}/complete` — una factura por turno completado
  cuando el servicio tiene precio configurado (tipo A/B según condición
  de IVA), seña ya cobrada y saldo restante como movimientos de caja
  separados sobre la misma factura. `libragenda` a `v0.8.0`, `libracore`
  a `v0.16.1`. Ver `DECISIONS.md` ADR-016.
- **SQLite pasa a ser el destino de producción por defecto** (arquitectura
  silo, mismo estándar que toda la familia Libra) — Postgres sigue
  soportado, ver `DECISIONS.md` ADR-015. LibraGenda actualizado a
  `v0.6.0` (activa `PRAGMA foreign_keys=ON` en toda conexión SQLite). CI
  ya no levanta un servicio Postgres, corre contra un archivo SQLite.
  Bug real corregido de paso: `BranchRepository.delete()` borraba el
  `Branch` antes que `BranchContactRow` (FK invertida) — mismo patrón que
  `PatientRepository`, portado verbatim desde Gestiolibra. `DELETE` de
  sucursales, recursos y servicios ahora devuelve 409 (antes 500) cuando
  todavía tienen registros dependientes.
- Consentimientos: `POST`/`GET /patients/{id}/consents` y
  `GET`/`DELETE /patients/{id}/consents/{consent_id}` — admin+staff,
  DELETE admin-only. Registro de consentimiento informado (procedimiento,
  quién autoriza — paciente o tutor/responsable —, texto libre), sin
  archivo firmado embebido (se sube aparte como documento clínico si hace
  falta), append-only sin revocación editable — retirar un consentimiento
  se registra como uno nuevo, nunca editando el original — ver ADR-014.
  Migración `0008_consents`. Cierra la Fase 2 clínica completa (recetas,
  estudios, documentos, consentimientos); resta solo facturación/caja y
  dashboard, ninguno clínico.
- Documentos clínicos: `POST /patients/{id}/documents` (multipart:
  archivo + título + descripción opcional + autor), `GET`/`DELETE
  /patients/{id}/documents/{document_id}`, descarga vía
  `GET .../{document_id}/file` — admin+staff, DELETE admin-only. Solo
  metadata en la base; archivo en filesystem local bajo
  `MEDLIBRA_DOCUMENTS_DIR` (mismo patrón que Contalibra/Restolibra, sin
  S3/MinIO), nombre en disco normalizado (UUID) — ver ADR-013. Formatos
  aceptados: PDF/PNG/JPG/JPEG, hasta 20MB. Vinculado solo al paciente.
  Migración `0007_clinical_documents`. Suma `python-multipart` como
  dependencia nueva.
- Estudios: `POST`/`GET /patients/{id}/study-orders`,
  `GET`/`DELETE /patients/{id}/study-orders/{order_id}` y
  `POST /patients/{id}/study-orders/{order_id}/items/{item_id}/results`
  (+ `DELETE` de resultado) — admin+staff, DELETE admin-only. Un pedido
  tiene uno o más items (tipo de estudio, motivo); cada item puede tener
  uno o más resultados propios como registros separados, append-only en
  las tres capas — ver ADR-012. Migración `0006_study_orders`. Borrar un
  paciente con pedidos existentes queda bloqueado (409), mismo mecanismo
  ya usado para notas/recetas.
- Recetas: `POST`/`GET /patients/{id}/prescriptions` y
  `GET`/`DELETE /patients/{id}/prescriptions/{prescription_id}`
  (admin+staff, DELETE admin-only). Una receta tiene uno o más items
  (medicamento, dosis, indicaciones), append-only, sin ciclo de vida
  propio (mismo criterio que `clinical_notes`) — ver ADR-011. Migración
  `0005_prescriptions`. Bug de fondo corregido de paso:
  `PatientRepository.delete()` borraba el `Client` antes que la extensión
  `PatientRow` (FK invertida), invisible en SQLite pero rompía contra
  PostgreSQL real.
- Recordatorios y señas: mismo alcance y código que Gestiolibra, portado
  verbatim. `POST /reminders/dispatch` (admin-only, dispara avisos vencidos
  — 24h y 2h antes, fijo) y `POST`/`GET /appointments/{id}/deposit`
  (admin+staff) + `POST /deposits/{id}/mark-paid`/`mark-failed`/`refund`
  (admin-only). Notificaciones y pago sin proveedor real todavía: puertos
  placeholder (`LoggingNotificationPort`, `ManualPaymentPort`) — ver
  ADR-010. Sin migración nueva (`deposits`/`sent_reminders` son tablas de
  LibraGenda).
- Configuración comercial del consultorio: `/branches/{id}/hours` (horario
  comercial semanal por sucursal, opt-in), `/services/{id}/prices` (precio
  por servicio y sucursal), `/branches` ahora acepta `phone`/`address`,
  `/business` (nombre comercial y moneda, singleton). Mismo feature y
  mismo código que Gestiolibra, portado verbatim. Migración
  `0004_business_config`.
- CI (GitHub Actions): `pytest` + smoke check de las dos cadenas de Alembic
  (LibraGenda + propia) contra Postgres de servicio, en cada push/PR a
  `main`. Requiere el secret `LIBRA_PAT` (ver `README.md`).
- Alembic propio (`migrations/`) para `users`/`patients`/`clinical_notes`
  — antes solo se creaban vía `create_all()`, sin efecto en un deploy real.
  Cadena de versión independiente (`alembic_version_medlibra`) para no
  colisionar con la de LibraGenda sobre la misma base.
- Login y roles básicos: `POST /auth/login`, `/auth/logout`, `GET /auth/me`,
  CRUD de usuarios admin-only en `/users`. Reusa `libracore.auth.SessionAuth`
  (mismo patrón que Gestiolibra). Dos roles: `admin` (todo) y `staff`
  (personal médico — turnos + pacientes/historia clínica, sin poder
  borrar). Completa la Fase 1 (MVP operativo). Suma `libracore` como
  dependencia nueva.
- CRUD de sucursales/recursos/servicios (`/branches`, `/resources`,
  `/services`) y disponibilidad configurable por profesional
  (`/resources/{id}/availability`/`/blocks`/`/exceptions`), reemplazando
  `/demo/seed`. `/resources/{id}/agenda` para ver los turnos de un
  profesional en un rango de fechas.
- `POST /appointments/{id}/cancel` y `POST /appointments/{id}/reschedule`,
  ambos con `reason` opcional (usa el campo agregado en LibraGenda `v0.5.0`).
  `AppointmentService.create()`/`reschedule()` dejaron de usar la ventana
  9-18 hardcodeada, leen la disponibilidad real configurada.
- Routers y servicios de aplicación separados del demo monolítico
  (`app/routers/`, `app/services/`).
- Dominio clínico inicial: `/patients` (CRUD completo, paciente = Client de
  LibraGenda + `dni`/`birth_date` propios) y `/patients/{id}/notes`
  (historia clínica básica: notas de evolución en texto libre, append-only,
  sin endpoint de actualización). Borrar un paciente con notas existentes
  devuelve 409.
- LibraGenda actualizado de `v0.3.0` a `v0.5.0` (incorpora CRUD completo de
  catálogo, fix de datetimes cross-dialecto y motivo opcional en
  cancelación/reprogramación). Base `medlibra` migrada a
  `0007_appointment_reason`.
- Normalización documental al estándar híbrido por producto.

## 2026-07-18 — Scaffold inicial

- Repo privado creado con FastAPI y paquete de aplicación.
- LibraGenda `v0.3.0` pineado como motor de agenda.
- PostgreSQL dedicado documentado para el entorno real.
- Smoke test HTTP inicial.
