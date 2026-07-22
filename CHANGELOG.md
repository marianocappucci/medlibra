# Changelog — MedLibra

## [Unreleased]

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
