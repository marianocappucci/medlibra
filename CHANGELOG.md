# Changelog — MedLibra

## [Unreleased]

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
