# Tasks — MedLibra

Trabajo concreto vigente. La dirección estratégica permanece en `ROADMAP.md`; este archivo no es un historial.

## En curso

Ninguna en curso registrada. Fase 1 (MVP operativo) quedó completa — ver
`ROADMAP.md`.

## Próximas

- [ ] Retomar la integración de facturación/caja con LibraCore (decisión
      de fondo ya tomada: sí integrar) — pausada el 2026-07-22 por
      alcance real mayor al esperado (toca 3 repos, incluida la
      orquestación de facturación ARCA que hoy solo vive en el código de
      Contalibra, no en el paquete `libracore`; requiere credenciales
      AFIP reales que solo el usuario puede cargar). Plan acordado antes
      de pausar: (1) LibraGenda agrega `complete()` al turno; (2)
      LibraCore extrae la orquestación de facturación de Contalibra a un
      módulo reutilizable y Contalibra migra a consumirlo; (3) MedLibra
      construye la integración (CUIT/condición de IVA como extensión del
      paciente, config ARCA del consultorio, disparo automático al
      completar turno/cobrar seña, y falta definir el campo "medio de
      pago" que hoy no existe en ningún lado de LibraGenda). El cambio a
      SQLite (ver más abajo) simplifica un poco el punto de la base
      separada para LibraCore que se había identificado al scopear esto
      — sigue siendo dos schemas/conexiones distintos (SQLAlchemy para
      LibraGenda/MedLibra, `sqlite3` crudo para LibraCore), pero ya no
      hace falta correr dos motores de base de datos en paralelo; a
      confirmar en detalle cuando se retome. Ver `ROADMAP.md`.
- [ ] Dashboard/reportes — único ítem de Fase 2 sin alcance definido.

## Decisiones pendientes

Ninguna. (SQLite vs. Postgres se resolvió — ver más abajo. Facturación
con LibraCore ya tiene decisión de fondo tomada, ver "Próximas".)

## Bloqueadas

Ninguna bloqueada registrada.

Resuelto (2026-07-21): LibraGenda actualizado a `v0.5.0` (desde `v0.3.0`,
compatibilidad revisada — ver `CHANGELOG.md`).

Resuelto (2026-07-21): Alembic propio de MedLibra para `users`/`patients`/
`clinical_notes` (`alembic_version_medlibra`, cadena independiente de la de
LibraGenda sobre la misma base) — ver `README.md`.

Resuelto (2026-07-22): configuración comercial del consultorio — horario
por sucursal, precio por servicio y sucursal, contacto de sucursal y datos
globales del negocio. Migración `0004_business_config`.

Resuelto (2026-07-22): recordatorios y señas — mismo alcance y código que
Gestiolibra, portado verbatim: `POST /reminders/dispatch`, `POST`/
`GET /appointments/{id}/deposit`, `POST /deposits/{id}/mark-paid`/
`mark-failed`/`refund`. Notificaciones y pago con puertos placeholder
(`LoggingNotificationPort`, `ManualPaymentPort`) hasta definir proveedor
real. Sin migración nueva (tablas de LibraGenda ya migradas).

Resuelto (2026-07-22): recetas — una receta puede tener varios items
(medicamento, dosis, indicaciones), append-only sin ciclo de vida propio
(mismo criterio que `clinical_notes`). `POST`/`GET /patients/{id}/prescriptions`
(admin+staff), `DELETE` admin-only. Migración `0005_prescriptions`. Bug
encontrado y corregido en el camino: `PatientRepository.delete()` borraba
el `Client` antes que la fila de extensión `PatientRow` (que tiene FK
hacia `clients.id`) — funcionaba por accidente en SQLite (no fuerza FKs)
pero rompía en PostgreSQL real; orden invertido.

Resuelto (2026-07-22): estudios — un pedido puede tener varios items
(tipo de estudio, motivo), y cada item puede tener uno o más resultados
propios como registros separados (nunca se edita el pedido). `POST`/
`GET /patients/{id}/study-orders`, `POST .../items/{item_id}/results`
(admin+staff), `DELETE` de pedido/resultado admin-only. Migración
`0006_study_orders`.

Resuelto (2026-07-22): documentos clínicos — filesystem local (mismo
patrón que Contalibra/Restolibra, sin S3/MinIO), vinculado solo al
paciente. `POST /patients/{id}/documents` (multipart), descarga vía
`/{document_id}/file`, `DELETE` admin-only (borra fila y archivo).
PDF/PNG/JPG/JPEG, hasta 20MB. Migración `0007_clinical_documents`. Suma
`python-multipart` como dependencia nueva.

Resuelto (2026-07-22): consentimientos informados — solo el registro
(procedimiento, quién autoriza, texto libre), sin archivo firmado
embebido; append-only sin revocación editable. `POST`/
`GET /patients/{id}/consents`, `DELETE` admin-only. Migración
`0008_consents`. Cierra el dominio clínico completo de Fase 2 — quedan
solo facturación/caja y dashboard/reportes, ninguno clínico.

Resuelto (2026-07-22): SQLite como destino de producción por defecto
(estándar de familia, ver `DECISIONS.md` ADR-015). LibraGenda a
`v0.6.0`. Bug real corregido: `BranchRepository.delete()` con orden de
borrado invertido (FK), portado verbatim desde Gestiolibra el mismo día
que la configuración comercial. `DELETE` de sucursales/recursos/
servicios ahora devuelve 409 en vez de 500 con dependientes. CI
simplificado (sin servicio Postgres).

## Notas de testing

- Igual que Gestiolibra: la suite usa cookies de sesión firmadas con
  timestamp (`itsdangerous`, vía `libracore.auth.SessionAuth`). En entorno
  WSL2 el reloj puede saltar hacia atrás ~20s en medio de una corrida
  (desincronización WSL2↔host Windows), invalidando un cookie válido
  (`SignatureExpired: age <0`) — 401 intermitente y no reproducible (~1
  cada 10-15 corridas). No es un bug de la app ni ocurre en el servidor
  real. Si un test de auth falla aislado sin cambios de código, reintentar
  antes de investigar.
