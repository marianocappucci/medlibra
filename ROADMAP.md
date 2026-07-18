# Roadmap de MedLibra

## Fase 0 — scaffold (completa)

Repo privado, FastAPI, dependencia LibraGenda `v0.3.0`, PostgreSQL dedicado
real (base `medlibra`, usuario `medlibra_dev`, Postgres 16 del VPS Donweb)
migrado con la cadena Alembic completa de LibraGenda y verificado end-to-end
con los repositorios SQLAlchemy reales — no solo un smoke test sqlite del
demo. Cierra el ítem "MedLibra consume el mismo contrato sin contaminar el
motor con clínica" de la Fase 3 del roadmap de LibraGenda.

## Fase 1 — MVP operativo (siguiente)

- Separar el demo en routers y servicios de aplicación.
- Definir el dominio clínico propio: paciente, historia clínica básica.
- CRUD de profesionales, consultorios, servicios y pacientes.
- Agenda diaria/semanal y disponibilidad configurable por profesional.
- Cancelar y reprogramar con motivos.
- Login y roles básicos.

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
