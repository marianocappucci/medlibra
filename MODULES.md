# Módulos de MedLibra

## Implementados

- `app/main.py`: factory FastAPI — configura LibraGenda, arma repos/servicios
  en `app.state`, monta routers.
- `app/dependencies.py`: providers de FastAPI que leen `app.state`.
- `app/services/appointments.py`: `AppointmentService` — capa de aplicación
  sobre `InMemoryScheduler` de LibraGenda. Ventana de disponibilidad
  hardcodeada 9-18 (mismo comportamiento que tenía el demo original,
  portado sin cambios de conducta) — disponibilidad real configurable es
  un ítem de "Próximas" en `TASKS.md`, no de esta ronda.
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
  edición). Diagnósticos estructurados, recetas, estudios y consentimientos
  quedan para la Fase 2 (ver `ROADMAP.md`).
- `app/routers/`: `health.py` (público), `demo.py` (`/demo/seed` — bootstrap
  placeholder de sucursal/recurso/servicio, mismo rol que tuvo en Gestiolibra
  antes de su CRUD real; los pacientes ya NO pasan por acá, son reales desde
  el día uno), `patients.py` (CRUD completo), `clinical_notes.py`
  (`/patients/{id}/notes` — crear/listar/obtener/borrar, sin `PUT`),
  `appointments.py` (crear/confirmar) — traducen excepciones de dominio a
  códigos HTTP (404/409/422).

## Próximos

- Disponibilidad real configurable por profesional (hoy hardcodeada 9-18).
- CRUD real de sucursales/recursos/servicios (hoy vía `/demo/seed`).
- Cancelar/reprogramar turnos con motivo (ya existe en LibraGenda `v0.5.0`
  y en Gestiolibra; falta el lado de MedLibra).
- Login y roles básicos (mismo patrón que Gestiolibra: `SessionAuth` de
  LibraCore + tabla propia).
- `billing` (opcional, no decidido): composición de LibraCore para facturación/caja.

## Después del MVP

- Recetas, estudios, documentos clínicos, consentimientos.
- Recordatorios y preferencias de comunicación (vía LibraGenda).
- Dashboard y reportes operativos.

## Fuera de alcance

Turnos genéricos no clínicos (Gestiolibra), mesas, comandas, cocina y food
cost (Restolibra), sistemas del Servidor Homei (PACS, Farmacia, Portal de
Pacientes — proyectos separados sin relación con MedLibra).
