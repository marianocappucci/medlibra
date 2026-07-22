# Arquitectura — MedLibra

## Propósito y límites

MedLibra será el producto vertical de turnos y gestión clínica para consultorios, profesionales independientes y centros médicos.

LibraGenda aporta el motor genérico de agenda. MedLibra debe mantener el dominio clínico propio — pacientes, historia clínica, evoluciones y diagnósticos — separado del motor común.

No confundir con PACS, Farmacia ni Portal de Pacientes del Servidor Homei; son proyectos separados y no comparten infraestructura.

## Componentes

- `app/main.py`: factory FastAPI, configuración y composición de dependencias.
  Aplica el gating por rol a nivel de router (`include_router(..., dependencies=[...])`),
  con un `Depends(require_admin)` extra en los endpoints `DELETE` de
  pacientes/notas clínicas (ver "Roles" abajo).
- `app/dependencies.py`: providers que leen el estado de la aplicación.
- `app/auth.py`: sesión por cookie firmada (reusa `libracore.auth.SessionAuth`,
  mismo patrón que [[gestiolibra]]) + dependencias FastAPI propias
  (`get_current_user`, `require_role`) que responden 401/403 JSON.
- `app/security.py`: hashing de contraseñas (PBKDF2, mismo algoritmo que
  `libracore.db.usuarios` y que Gestiolibra).
- `app/services/appointments.py`: capa de aplicación sobre LibraGenda
  (turnos, disponibilidad real configurable, cancelar/reprogramar con
  motivo).
- `app/services/patients.py`: pacientes — extensión clínica (`dni`,
  `birth_date`) del `Client` genérico de LibraGenda, coordinada en el borde
  de la API, no mezclada en el schema del motor.
- `app/services/clinical_notes.py`: historia clínica básica — notas de
  evolución en texto libre, append-only (sin update).
- `app/services/users.py`: tabla y repositorio de usuarios propios de
  MedLibra (no pertenecen al dominio de LibraGenda).
- `app/routers/`: health (público), auth (login/logout/me), users
  (admin-only), branches/resources/services/availability (admin-only),
  patients/clinical_notes (admin+staff, DELETE admin-only), appointments/
  agenda (admin+staff).
- `MODULES.md`: inventario operativo de módulos.
- LibraGenda `v0.5.0`: dependencia versionada para dominio, persistencia y
  migraciones propias.
- LibraCore: dependencia versionada solo por `libracore.auth.SessionAuth`
  (facturación/caja sigue sin decidir, ver `DECISIONS.md` ADR-003).

## Roles

Dos roles, distintos de Gestiolibra por una razón de dominio real: en
Gestiolibra `staff` solo toca turnos, pero en MedLibra el personal médico
(`staff`) necesita leer y escribir historia clínica para hacer su trabajo.
`admin` tiene acceso completo (catálogo, disponibilidad, usuarios, y es el
único que puede borrar pacientes o notas clínicas — la historia clínica es
append-only por diseño, ver ADR-006, así que hasta el borrado admin-only es
una excepción pensada solo para corregir errores de carga, no para editar
contenido). `staff` gestiona turnos y pacientes/historia clínica sin poder
borrar ninguno de los dos.

## Dominio clínico vs. motor genérico

LibraGenda no sabe nada de pacientes ni historia clínica — solo conoce
`Client` (identidad genérica para agendar) y `Resource`/`Service`/
`Appointment`. MedLibra extiende esa identidad con lo clínico en sus
propias tablas (`patients`, `clinical_notes`), vinculadas por FK al `id`
del `Client` — mismo principio que "no duplicar reglas de LibraGenda" de
`CONVENTIONS.md`, aplicado en la dirección inversa: lo clínico no
contamina el motor, vive enteramente en MedLibra.

## Persistencia e integración

La aplicación configura LibraGenda mediante `LIBRAGENDA_DATABASE_URL` y usa PostgreSQL dedicado para MedLibra. Las migraciones de LibraGenda se ejecutan desde un checkout del repositorio upstream en la versión exacta pineada, antes de iniciar la API; no se usa `create_all()` en producción para las tablas de LibraGenda.

`pyproject.toml` pinea LibraGenda `v0.5.0` (actualizado desde `v0.3.0`, ver
`DECISIONS.md` ADR-004). Las tablas propias de MedLibra (`patients`,
`clinical_notes`, `users`) todavía no tienen Alembic propio — solo se crean vía
`Base.metadata.create_all()` en `create_app()`, igual que le pasaba a
`users` en Gestiolibra antes de que decidiera su propio pipeline de
migraciones; pendiente antes de un deploy real (ver `TASKS.md`).

## Entornos y deploy

- Desarrollo: entorno dev con base `medlibra` y usuario dedicado.
- Demo: producción controlada para validación.
- Producción: dominio del cliente.

La rama observada actualmente es `main`. La adopción de `develop` como rama de integración queda pendiente de una decisión operativa explícita.
