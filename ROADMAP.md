# Roadmap de MedLibra

## Fase 0 — scaffold (completa)

Repo privado, FastAPI, dependencia LibraGenda `v0.3.0`, PostgreSQL dedicado
real (base `medlibra`, usuario `medlibra_dev`, Postgres 16 del VPS Donweb)
migrado con la cadena Alembic completa de LibraGenda y verificado end-to-end
con los repositorios SQLAlchemy reales — no solo un smoke test sqlite del
demo. Cierra el ítem "MedLibra consume el mismo contrato sin contaminar el
motor con clínica" de la Fase 3 del roadmap de LibraGenda.

## Fase 1 — MVP operativo (en curso)

- Separar el demo en routers y servicios de aplicación (completo).
  `app/routers/` (health, demo, patients, clinical_notes, appointments) +
  `app/services/` (`AppointmentService`, `PatientRepository`,
  `ClinicalNoteRepository`) + `app/dependencies.py`. `/demo/seed` queda
  como placeholder solo para sucursal/recurso/servicio — los pacientes ya
  no pasan por ahí.
- Definir el dominio clínico propio: paciente, historia clínica básica
  (completo). Paciente = `Client` de LibraGenda + extensión propia (`dni`,
  `birth_date`) en tabla `patients`. Historia clínica = notas de evolución
  en texto libre por paciente, append-only (sin update; borrar un paciente
  con notas está bloqueado). Diagnósticos estructurados, recetas, estudios
  y consentimientos quedan para Fase 2. Ver `DECISIONS.md` ADR-005/006.
- CRUD de profesionales y consultorios (pendiente — pacientes ya completo
  arriba).
- Agenda diaria/semanal y disponibilidad configurable por profesional
  (pendiente — hoy ventana hardcodeada 9-18).
- Cancelar y reprogramar con motivos (pendiente).
- Login y roles básicos (pendiente).

## Fase 2 — operación clínica

- Recetas, estudios, documentos clínicos, consentimientos.
- Recordatorios y señas (composición de LibraGenda).
- Facturación/caja, solo si se decide incorporar LibraCore.
- Dashboard y reportes.

## Fase 3 — producto

- Onboarding multi-consultorio/centro médico.
- Branding y dominio por cliente.
- Deploy dev/prod, CI y backups verificados.
- Validación con primeros consultorios reales.
