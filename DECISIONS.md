# Decisiones arquitectónicas — MedLibra

Registro ADR. Las decisiones no se borran; si dejan de aplicar, se marcan como reemplazadas.

## ADR-001 — Separar MedLibra de los sistemas de salud de Homei

- Estado: aceptada
- Fecha: 2026-07-18
- Contexto: existen PACS, Farmacia y Portal de Pacientes en el Servidor Homei.
- Decisión: MedLibra es un producto independiente, sin relación ni infraestructura compartida con esos sistemas.
- Consecuencias: su despliegue, dominio, datos y evolución se gestionan por separado.

## ADR-002 — Mantener el motor de agenda fuera del dominio clínico

- Estado: aceptada
- Fecha: 2026-07-18
- Contexto: LibraGenda también es consumido por verticales no clínicos.
- Decisión: usar LibraGenda para turnos y agenda, pero mantener pacientes, historia clínica y demás lógica clínica en MedLibra.
- Consecuencias: el motor común permanece reutilizable y MedLibra conserva el control de sus reglas clínicas.

## ADR-003 — Mantener facturación con LibraCore como decisión abierta

- Estado: propuesta pendiente (actualizada 2026-07-21: LibraCore sí se sumó
  como dependencia, pero solo por `libracore.auth.SessionAuth` — ver
  ADR-007. Facturación/caja sigue sin decidir.)
- Fecha: 2026-07-18
- Contexto: algunos productos Libra usan LibraCore, pero el MVP clínico todavía no requiere facturación definida.
- Decisión: no incorporar LibraCore *para facturación* hasta confirmar el alcance de facturación y caja.
- Consecuencias: se evita acoplar el scaffold a un componente no necesario para el MVP.

## ADR-004 — Versionar LibraGenda con pin exacto

- Estado: aceptada
- Fecha: 2026-07-18 (actualizada 2026-07-21: pin llevado de `v0.3.0` a
  `v0.5.0` tras revisar compatibilidad — suite propia sigue pasando)
- Contexto: los consumidores necesitan un contrato reproducible.
- Decisión: pinear una versión exacta de LibraGenda y revisar las actualizaciones de forma explícita.
- Consecuencias: cada upgrade requiere pruebas de compatibilidad y una decisión documentada, no es automático.

## ADR-005 — Paciente como extensión clínica del Client de LibraGenda

- Estado: aceptada
- Fecha: 2026-07-21
- Contexto: MedLibra necesita modelar "paciente" para su MVP. LibraGenda ya
  tiene `Client` (identidad genérica usada para agendar turnos) pero sin
  ningún campo clínico, y no debe tenerlo — contaminaría un motor
  compartido con verticales no clínicos (Gestiolibra).
- Decisión: un paciente ES un `Client` de LibraGenda (id, nombre, teléfono,
  email) más una extensión propia de MedLibra en su propia tabla
  (`patients`: `dni`, `birth_date`), coordinadas en el borde de la API
  (`PatientRepository`) en vez de fusionarse en un solo modelo.
- Consecuencias: dos escrituras coordinadas (no una transacción atómica
  cross-repositorio) en `create`/`update`; riesgo aceptado y bajo, ya
  cubierto por la validación de unicidad del `Client` antes de tocar la
  extensión. El motor permanece genérico.

## ADR-006 — Historia clínica básica: notas de evolución, append-only

- Estado: aceptada
- Fecha: 2026-07-21
- Contexto: la Fase 1 del roadmap solo pide "historia clínica básica";
  diagnósticos estructurados, recetas, estudios y consentimientos quedan
  para la Fase 2.
- Decisión: una entidad simple (`ClinicalNoteRepository`) — notas de texto
  libre con fecha, autor y contenido, asociadas a un paciente. Sin endpoint
  de actualización: un registro clínico no debería reescribirse
  silenciosamente después de creado, solo agregarse (o borrarse por un
  admin, para corregir un error de carga real). Borrar un paciente con
  notas existentes está bloqueado (409) — no hay cascada automática.
- Consecuencias: cualquier corrección de una nota pasa por crear una nota
  nueva, no por editar la anterior — coherente con la práctica clínica real
  de un registro auditable. Reabrir esta decisión si aparece una necesidad
  real de edición (ej. corrección de un error tipográfico menor).

## ADR-007 — Reusar SessionAuth de LibraCore; staff con acceso clínico, a diferencia de Gestiolibra

- Estado: aceptada
- Fecha: 2026-07-21
- Contexto: MedLibra necesita login y roles. Gestiolibra ya resolvió el
  mismo problema (`libracore.auth.SessionAuth` + tabla `users` propia en
  SQLAlchemy/Postgres, ver `DECISIONS.md` de ese repo ADR-005/006) — mismo
  motor, mismo stack de persistencia, sin motivo para reinventar. La única
  pregunta real era el modelo de roles: en Gestiolibra `staff` solo toca
  turnos, pero en MedLibra el rol `staff` representa personal médico, que
  necesita leer y escribir historia clínica para hacer su trabajo — un
  `staff` sin acceso a pacientes/notas clínicas sería inútil acá.
- Decisión: portar `SessionAuth`/`security.py`/`services/users.py`/
  `routers/auth.py`/`routers/users.py` de Gestiolibra sin cambios de fondo
  (cookie `ml_session` propia para no colisionar si algún día conviven).
  Dos roles (`admin`/`staff`), pero `patients`/`clinical_notes` quedan
  gateados a `admin`+`staff` (no solo `admin` como el resto del catálogo),
  con un `Depends(require_admin)` adicional solo en los endpoints `DELETE`
  de esos dos routers (borrar sigue siendo admin-only, coherente con
  ADR-006).
- Consecuencias: el modelo de permisos de MedLibra diverge intencionalmente
  del de Gestiolibra en este punto — no es un error de copiar-pegar, es una
  decisión de dominio: cada vertical define qué significa "staff" según su
  propio negocio.

## ADR-008 — Alembic propio de MedLibra, cadena independiente de la de LibraGenda

- Estado: aceptada
- Fecha: 2026-07-21
- Contexto: `users`, `patients` y `clinical_notes` solo se creaban vía
  `Base.metadata.create_all()` en `create_app()` — sin efecto en un deploy
  real, que corre las migraciones de LibraGenda pero no conoce estas tres
  tablas propias de MedLibra. Mismo problema que resolvió Gestiolibra el
  mismo día (ver `DECISIONS.md` de ese repo, ADR-007).
- Decisión: `migrations/` propio (mismo layout que LibraGenda y
  Gestiolibra: `alembic.ini`, `env.py`, `versions/`), con
  `target_metadata = None` (los tres modelos comparten el `Base`
  declarativo de LibraGenda; las migraciones se escriben a mano) y
  `version_table = "alembic_version_medlibra"` (ambas cadenas corren
  contra la misma base física, el nombre default colisionaría). Orden de
  migraciones respeta las FKs: `users` (sin dependencias) → `patients`
  (FK a `clients.id`, tabla de LibraGenda) → `clinical_notes` (FK a
  `patients.id`).
- Consecuencias: el deploy real de MedLibra corre dos pasos de Alembic
  (LibraGenda primero, MedLibra después) — verificado contra PostgreSQL
  real que las dos cadenas conviven sin pisarse y que las FKs cruzadas
  (`patients.id` → `clients.id`) se crean correctamente. Cualquier tabla
  nueva propia de MedLibra se agrega acá, nunca en el repo de LibraGenda.

## ADR-009 — Configuración comercial: mismo alcance y código que Gestiolibra

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: mismo ítem pendiente que tenía Gestiolibra ("configuración
  comercial" anotado sin detallar). El usuario ya había definido el
  alcance concreto para Gestiolibra el mismo día (horario, precio,
  contacto/marca) y pidió el mismo feature para MedLibra.
- Decisión: portar `branches.py`/`branch_hours.py`/`service_prices.py`/
  `business_settings.py` de Gestiolibra verbatim — ninguna de las cuatro
  piezas tiene lógica clínica ni específica del vertical (horario de
  consultorio, precio de consulta y contacto/marca son conceptos
  igual de genéricos que en un negocio de servicios). Mismas decisiones
  de diseño que ADR-008 de Gestiolibra: horario opt-in, precio por par
  (servicio, sucursal) no un campo único en `Service`, `business_settings`
  como fila única.
- Consecuencias: mismo razonamiento que ADR-008 de Gestiolibra sobre no
  subir esto a LibraGenda todavía — si en el futuro se repite en un
  tercer vertical, evaluar la extracción al motor común en ese momento.

## ADR-010 — Recordatorios y señas: mismo alcance y puertos placeholder que Gestiolibra

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: mismo ítem pendiente que resolvió Gestiolibra el mismo día
  (ver `DECISIONS.md` de ese repo, ADR-009): LibraGenda ya resuelve el
  dominio (`ReminderDispatcher`, `DepositManager`) vía dos puertos
  (`NotificationPort`, `PaymentPort`) que el consumidor debe implementar, y
  ni Gestiolibra ni MedLibra tienen todavía un proveedor de notificaciones
  ni de pago elegido.
- Decisión: portar `app/notifications.py` (`LoggingNotificationPort`,
  `DEFAULT_REMINDER_POLICIES`), `app/payments.py` (`ManualPaymentPort`),
  `app/routers/reminders.py` y `app/routers/deposits.py` de Gestiolibra
  verbatim — ninguna de las cuatro piezas tiene lógica clínica ni
  específica del vertical (un recordatorio de turno y una seña son igual
  de genéricos en un consultorio que en una peluquería). Gating de rol
  igual que Gestiolibra: `/reminders/dispatch` y confirmación de señas
  (`/deposits/{id}/...`) admin-only; pedir/consultar una seña
  (`/appointments/{id}/deposit`) admin+staff, coherente con que el
  personal médico ya gestiona sus propios turnos.
- Consecuencias: mismo trade-off que Gestiolibra — la feature es usable en
  producción sin esperar una integración externa, a costa de seguimiento
  manual (logs para recordatorios, confirmación a mano para señas) hasta
  que se reemplacen los puertos. Ningún campo clínico involucrado, así que
  no hay divergencia de dominio que documentar como en ADR-007 (roles) o
  ADR-005 (paciente).

## ADR-011 — Recetas: varios items por receta, append-only sin ciclo de vida

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: el usuario eligió "recetas" entre el resto de la Fase 2
  pendiente (`AskUserQuestion`). Antes de codificar, dos preguntas de
  modelado real sin respuesta obvia: (1) ¿una receta tiene un solo
  medicamento o varios?; (2) ¿la receta tiene estado propio (emitida/
  dispensada/anulada) o es un registro simple como `clinical_notes`?
  Preguntado al usuario (`AskUserQuestion`): eligió varios items por
  receta y append-only sin estado.
- Decisión: `PrescriptionRow` (header: paciente, autor, fecha) +
  `PrescriptionItemRow` (medicamento, dosis, indicaciones opcionales), uno
  a muchos. `create()` exige al menos un item (422 si la lista viene
  vacía). Mismo criterio append-only que `clinical_notes` (ADR-006): sin
  endpoint de actualización, solo crear/listar/obtener/borrar (DELETE
  admin-only, para errores de carga). Sin estado de dispensa — eso es
  resorte de la farmacia, no de MedLibra. Borrar un paciente con recetas
  existentes queda bloqueado (409), mismo mecanismo ya usado para notas
  clínicas — `PatientRepository.delete()` ahora chequea ambas tablas antes
  de permitir el borrado.
- Consecuencias: los items de una receta se ordenan por una columna
  `position` propia (no por `id`, que es un UUID no secuencial) — sin
  esto, el orden de carga se hubiera perdido o quedado ambiguo entre
  motores (SQLite vs. PostgreSQL pueden devolver filas en orden distinto
  sin un `ORDER BY` explícito sobre una columna con esa semántica).
  Migración `0005_prescriptions` (dos tablas, con cascada de borrado a
  nivel ORM — `cascade="all, delete-orphan"` en la relación — para que
  borrar una receta borre sus items sin dejarlos huérfanos).

  **Bug real encontrado en el camino, no relacionado con recetas en sí**:
  al verificar contra PostgreSQL real, borrar un paciente sin notas ni
  recetas (el camino "feliz" del flujo de borrado) fallaba con
  `ForeignKeyViolation` — `PatientRepository.delete()` borraba el `Client`
  genérico de LibraGenda **antes** que la fila `PatientRow` (que tiene FK
  hacia `clients.id`), violando esa FK. En SQLite (usado en toda la suite
  de tests) esto pasaba desapercibido porque no fuerza FKs por default, así
  que el bug nunca se detectó hasta esta ronda de verificación con Postgres
  real. Corregido invirtiendo el orden: primero se borra `PatientRow`,
  después el `Client`. No es un bug introducido por recetas — ya afectaba
  a `clinical_notes`/pacientes desde ADR-005, solo que ningún camino de
  verificación anterior había ejercido el borrado de un paciente sin
  registros clínicos contra Postgres real hasta ahora.
