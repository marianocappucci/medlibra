# Tasks — MedLibra

Trabajo concreto vigente. La dirección estratégica permanece en `ROADMAP.md`; este archivo no es un historial.

## En curso

Ninguna en curso registrada.

## Próximas

- [ ] CRUD de profesionales y consultorios (hoy solo vía `/demo/seed`; los
      pacientes ya tienen CRUD real en `/patients`).
- [ ] Agenda diaria/semanal y disponibilidad configurable por profesional
      (hoy ventana hardcodeada 9-18, portada tal cual del demo original).
- [ ] Cancelación y reprogramación con motivos (LibraGenda `v0.5.0` y
      Gestiolibra ya lo tienen; falta el lado de MedLibra — mismo patrón
      que `POST /appointments/{id}/cancel`/`reschedule` de Gestiolibra).
- [ ] Login y roles básicos (mismo patrón que Gestiolibra: `SessionAuth` de
      LibraCore + tabla `users` propia).
- [ ] MedLibra todavía no tiene Alembic propio: `patients`/`clinical_notes`
      solo se crean vía `Base.metadata.create_all()` en `create_app()` —
      documentado como "demo only" pero hoy es el único mecanismo real.
      Definir migraciones propias antes de un deploy real (mismo pendiente
      que tiene Gestiolibra con `users`).

## Decisiones pendientes

- [ ] Decidir si MedLibra incorpora LibraCore para facturación y caja.

## Bloqueadas

Ninguna bloqueada registrada.

Resuelto (2026-07-21): LibraGenda actualizado a `v0.5.0` (desde `v0.3.0`,
compatibilidad revisada — ver `CHANGELOG.md`).
