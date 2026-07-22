# Tasks — MedLibra

Trabajo concreto vigente. La dirección estratégica permanece en `ROADMAP.md`; este archivo no es un historial.

## En curso

Ninguna en curso registrada. Fase 1 (MVP operativo) quedó completa — ver
`ROADMAP.md`.

## Próximas

- [ ] Configuración comercial por consultorio más allá del CRUD básico de
      sucursales (mismo ítem que tiene Gestiolibra pendiente).
- [ ] Definir alcance de Fase 2 (recetas, estudios, documentos clínicos,
      consentimientos, recordatorios/señas, facturación si se decide
      LibraCore, dashboard) — ver `ROADMAP.md`.

## Decisiones pendientes

- [ ] Decidir si MedLibra incorpora LibraCore además para facturación y
      caja (ya se sumó como dependencia para `SessionAuth`).

## Bloqueadas

Ninguna bloqueada registrada.

Resuelto (2026-07-21): LibraGenda actualizado a `v0.5.0` (desde `v0.3.0`,
compatibilidad revisada — ver `CHANGELOG.md`).

Resuelto (2026-07-21): Alembic propio de MedLibra para `users`/`patients`/
`clinical_notes` (`alembic_version_medlibra`, cadena independiente de la de
LibraGenda sobre la misma base) — ver `README.md`.

## Notas de testing

- Igual que Gestiolibra: la suite usa cookies de sesión firmadas con
  timestamp (`itsdangerous`, vía `libracore.auth.SessionAuth`). En entorno
  WSL2 el reloj puede saltar hacia atrás ~20s en medio de una corrida
  (desincronización WSL2↔host Windows), invalidando un cookie válido
  (`SignatureExpired: age <0`) — 401 intermitente y no reproducible (~1
  cada 10-15 corridas). No es un bug de la app ni ocurre en el servidor
  real. Si un test de auth falla aislado sin cambios de código, reintentar
  antes de investigar.
