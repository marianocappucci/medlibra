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

## ADR-012 — Estudios: varios items por pedido, resultado como registro separado por item

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: el usuario eligió "estudios" entre el resto de la Fase 2
  pendiente (`AskUserQuestion`). Antes de codificar, dos preguntas de
  modelado sin respuesta obvia: (1) ¿"estudios" cubre solo el pedido
  (qué se solicita) o también el resultado, cuando llega?; (2) ¿un pedido
  puede incluir varios estudios a la vez (ej. análisis de sangre +
  radiografía en una sola solicitud) o es un estudio por pedido?
  Preguntado al usuario (`AskUserQuestion`): eligió pedido + resultado
  como registros separados, y varios items por pedido.
- Decisión: `StudyOrderRow` (header: paciente, autor, fecha) +
  `StudyOrderItemRow` (tipo de estudio, motivo opcional), uno a muchos,
  mismo patrón que `PrescriptionRow`/`PrescriptionItemRow` (ADR-011,
  incluida la columna `position` propia por el mismo motivo: el `id` es
  un UUID, no sirve para ordenar). El resultado se modela como una tabla
  separada, `StudyResultRow`, con FK al **item** (no al pedido): cada
  estudio solicitado produce su propio resultado, que puede llegar en un
  momento distinto al de los demás items del mismo pedido (un análisis de
  sangre y una radiografía no se resuelven el mismo día necesariamente).
  Esta granularidad a nivel item, no decidida explícitamente por el
  usuario, es una extensión directa de las dos decisiones que sí tomó
  ("pedido + resultado separados" + "varios items por pedido") — no
  requirió una tercera pregunta porque no hay otra forma razonable de
  combinar ambas. Un item admite más de un resultado (ej. un resultado
  ampliado o corregido más adelante, sin sobreescribir el anterior).
  `create()` del pedido exige al menos un item (422 si la lista viene
  vacía). Mismo criterio append-only que recetas/notas clínicas en las
  tres capas (pedido, item, resultado): sin endpoint de actualización en
  ninguna, solo crear/listar/obtener/borrar (DELETE admin-only, para
  errores de carga). Sin estado de "pendiente"/"completado" en el
  pedido — se infiere de si sus items tienen o no resultados cargados,
  no se persiste como un campo aparte.
- Consecuencias: tres tablas nuevas (`study_orders`, `study_order_items`,
  `study_results`), migración `0006_study_orders`, con cascada de borrado
  a nivel ORM en las dos relaciones (`cascade="all, delete-orphan"`) para
  que borrar un pedido borre sus items y los resultados de esos items sin
  dejar nada huérfano. Borrar un paciente con pedidos de estudios
  existentes queda bloqueado (409), mismo mecanismo ya usado para notas y
  recetas — `PatientRepository.delete()` ahora chequea las tres tablas.
  El router valida la cadena completa de pertenencia (patient → order →
  item) antes de aceptar un resultado, para no permitir cargar un
  resultado sobre un item de un pedido de otro paciente.

## ADR-013 — Documentos clínicos: filesystem local, vinculado solo al paciente

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: el usuario eligió "documentos clínicos" entre el resto de la
  Fase 2 pendiente (`AskUserQuestion`). Antes de codificar, dos preguntas
  reales sin respuesta obvia: (1) ¿dónde se guardan los archivos subidos?
  — ningún repo de LibraGenda/Gestiolibra/MedLibra maneja archivos
  todavía; (2) ¿un documento se vincula solo al paciente o también puede
  asociarse a un registro puntual (ej. el PDF de un resultado de
  estudio)? Antes de preguntar se investigó si algún repo de la familia
  Libra ya resolvía esto: Contalibra/Restolibra sí tienen un patrón
  probado (`web/routers/config.py` — logo/certificados ARCA/backups en un
  directorio dedicado bajo `DATA_DIR`, `open(...,"wb")`, sin S3/MinIO).
  Preguntado al usuario con esa información como contexto
  (`AskUserQuestion`): eligió replicar ese mismo patrón filesystem, y
  vincular el documento solo al paciente.
- Decisión: `ClinicalDocumentRow` con solo metadata en la base (`title`,
  `description` opcional, `author`, `original_filename`, `content_type`,
  `size_bytes`); el archivo vive en filesystem bajo
  `MEDLIBRA_DOCUMENTS_DIR` (env var, default `./data/medlibra_documents`,
  mismo patrón que `DATA_DIR` de Contalibra). El nombre en disco es un
  UUID + extensión — nunca el nombre original del usuario — para evitar
  path traversal y colisiones de nombre; el original se guarda como
  metadata. `POST /patients/{id}/documents` usa `multipart/form-data`
  (`UploadFile` de FastAPI + campos `Form`), única excepción a que el
  resto de la API sea JSON puro — inevitable para un archivo binario.
  Validación en el borde: extensión en whitelist (`.pdf`, `.png`, `.jpg`,
  `.jpeg` — 422 si no matchea) y tamaño máximo 20MB (422 si se excede),
  ninguna de las dos pedida explícitamente por el usuario pero razonable
  para el caso de uso descrito (informes/estudios escaneados) y para no
  dejar el endpoint abierto a cualquier archivo de cualquier tamaño.
  `GET /patients/{id}/documents/{document_id}/file` sirve el archivo con
  `FileResponse`, gateado por el mismo rol que el resto del router (no
  `StaticFiles`, que no tiene auth). `delete()` borra la fila y el
  archivo del disco. Sin endpoint de reemplazo/actualización — para
  corregir un documento mal cargado, se borra (admin-only) y se sube de
  nuevo, mismo espíritu append-only que el resto del dominio clínico
  aunque un archivo no es exactamente "append-only" en el mismo sentido
  que una nota de texto.
- Consecuencias: suma `python-multipart` como dependencia nueva (requerida
  por FastAPI para parsear `multipart/form-data`, no estaba en ningún repo
  de la familia). El almacenamiento en filesystem local ata los archivos
  al filesystem del contenedor/host donde corre MedLibra — si el deploy
  real usa un volumen no persistente, los documentos se perderían en un
  redeploy; esto es responsabilidad del deploy (mismo supuesto que ya
  asume `DATA_DIR` en Contalibra/Restolibra), no algo que esta feature
  resuelva. Borrar un paciente con documentos existentes queda bloqueado
  (409), mismo mecanismo ya usado para notas/recetas/estudios —
  `PatientRepository.delete()` ahora chequea las cuatro tablas.

## ADR-014 — Consentimientos: solo registro, append-only sin revocación editable

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: el usuario eligió "consentimientos" entre el resto de la Fase
  2 pendiente (`AskUserQuestion`), último ítem clínico de la fase. Antes
  de codificar, dos preguntas reales sin respuesta obvia: (1) ¿un
  consentimiento requiere adjuntar el documento firmado (PDF/imagen) en
  el mismo endpoint, o alcanza con el registro?; (2) ¿un consentimiento
  puede revocarse más adelante (estado editable) o es un registro fijo
  desde que se otorga? Preguntado al usuario (`AskUserQuestion`): eligió
  solo el registro (sin archivo embebido) y append-only sin revocación
  editable.
- Decisión: `ConsentRow` — `procedure` (procedimiento/tratamiento),
  `granted_by` (texto libre: "paciente", o nombre + relación de un tutor/
  responsable), `text` (detalle acordado), `author` (quién lo obtuvo) y
  `created_at`. Sin archivo adjunto embebido: si hace falta el PDF
  firmado escaneado, se sube por separado como documento clínico
  (`/patients/{id}/documents`, ADR-013) — decisión explícita de no
  acoplar ambas features, aunque documentos clínicos ya existía como
  capacidad disponible para reusar. Mismo criterio append-only que
  `clinical_notes` (ADR-006): sin endpoint de actualización ni de
  transición de estado. Retirar un consentimiento no es una operación
  soportada por el dominio — se modela registrando un consentimiento
  **nuevo** cuyo `text` deja constancia del retiro, el original nunca se
  toca. `DELETE` sigue existiendo (admin-only), con el mismo alcance que
  el resto del dominio: corregir un error de carga, no revocar.
- Consecuencias: es la pieza más simple de las cuatro que resolvió la
  Fase 2 clínica (recetas, estudios, documentos, consentimientos) — una
  sola tabla, sin items ni relaciones adicionales, mismo shape que
  `clinical_notes` con dos columnas más. Con esto, la Fase 2 clínica
  queda completa; lo que resta de Fase 2 (facturación/caja, dashboard) no
  es dominio clínico. Borrar un paciente con consentimientos existentes
  queda bloqueado (409), mismo mecanismo ya usado para notas/recetas/
  estudios/documentos — `PatientRepository.delete()` ahora chequea las
  cinco tablas.

## ADR-015 — SQLite como destino de producción por defecto

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: al scopear si MedLibra debía componer LibraCore para
  facturación, salió a la luz que Contalibra/Restolibra despliegan con
  arquitectura silo real (instancia + base SQLite aislada por cliente) y
  que Gestiolibra/MedLibra ya prevén exactamente el mismo patrón de
  despliegue. Mantener MedLibra en PostgreSQL mientras el resto de la
  familia usa SQLite no aportaba nada real y complicaba cualquier
  composición futura con LibraCore (SQLite-only, sin capa de
  abstracción). Decisión del usuario, registrada como estándar de
  familia en LibraGenda (ver `DECISIONS.md` de ese repo, ADR-005) y en
  `estandares-desarrollo.md` del wiki. Mismo cambio aplicado el mismo
  día en Gestiolibra (ver `DECISIONS.md` de ese repo, ADR-010).
- Decisión: `DATABASE_URL` pasa a apuntar a un archivo SQLite por
  defecto en vez de una base Postgres. Sin cambios de código propios:
  `LibraGenda.configure(url)` ya activa `PRAGMA foreign_keys=ON`
  automáticamente para cualquier conexión SQLite (ver ADR-005 de
  LibraGenda). Al verificar contra un archivo real con FKs activas
  (nunca antes ejercido — solo se probaba contra SQLite en memoria en
  tests o contra Postgres real), salió a la luz un bug preexistente
  idéntico al de `PatientRepository` (ADR-011): `BranchRepository.delete()`
  — portado verbatim desde Gestiolibra el mismo día que se construyó la
  configuración comercial — borraba el `Branch` genérico antes que
  `BranchContactRow` (extensión con FK a `branches.id`). Postgres ya lo
  hubiera bloqueado siempre; nunca se ejerció ese camino específico
  contra Postgres real en las verificaciones anteriores. Corregido
  invirtiendo el orden, mismo fix que ya se aplicó en Gestiolibra. De
  paso se encontró que `DELETE /branches/{id}`, `/resources/{id}` y
  `/services/{id}` no traducían `IntegrityError` a un 409 limpio (solo
  capturaban `KeyError`) — devolvían 500 crudo al borrar una entidad de
  catálogo con dependientes. Agregado el `except IntegrityError`
  faltante en los tres routers (`/patients` ya tenía su propio manejo
  vía `PatientHasClinicalNotes`, no necesitaba el fix).
- Consecuencias: CI simplificado (sin servicio Postgres, smoke check
  contra un archivo SQLite plano). Verificado con la suite completa y
  end-to-end contra un archivo SQLite real: todo el dominio clínico
  (recetas, estudios, documentos, consentimientos) más los tres casos de
  borrado bloqueado por FK (sucursal con recurso, recurso y servicio con
  turno) devolviendo 409 en vez de 500. Postgres sigue funcionando si se
  pasa esa `DATABASE_URL`; no se retira como opción.

## ADR-016 — Facturación/caja con LibraCore: una factura por turno completado

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: retomó la decisión pausada el mismo día (ver TASKS.md) de
  incorporar LibraCore para facturación/caja. El plan acordado antes de
  pausar tenía tres pasos: (1) LibraGenda expone `complete()` para el
  turno (hecho, `v0.7.0`); (2) LibraCore extrae la orquestación de
  numeración/CAE de `web/helpers/arca_helper.py` de Contalibra a un
  módulo reutilizable propio (hecho, `libracore.arca_facturacion`,
  `v0.16.0` — resultó mucho más simple de lo estimado: toda la capa de
  datos (`libracore.db.facturas`/`arca_config`/`caja`) ya estaba
  centralizada desde la Fase 3 de LibraCore, solo faltaba mover la
  función de glue); (3) MedLibra construye la integración — este ADR.
  De paso, Contalibra y Restolibra migraron su propio `arca_helper.py` a
  un shim de 3 líneas sobre ese módulo nuevo (mismo patrón que el resto
  de LibraCore), con confirmación explícita del usuario en cada paso de
  producción.

  Antes de codificar la integración de MedLibra se resolvieron dos
  preguntas reales con el usuario (`AskUserQuestion`): (1) **cuándo se
  factura** — una sola factura al completar el turno (no una por seña +
  otra por saldo); (2) **cómo se determina el tipo de comprobante** —
  A si el paciente es Responsable Inscripto, B en cualquier otro caso
  (Consumidor Final, Monotributista, etc. — sin discriminar C).

- Decisión — arquitectura: `libracore.db` es sqlite3 crudo con una
  conexión propia (`libracore.db.core.configure()`), completamente
  separada del engine SQLAlchemy que usa LibraGenda/MedLibra para el
  resto del dominio — dos archivos SQLite distintos, sin capa de
  abstracción compartida entre ambos (ver TASKS.md previo, que ya
  anticipaba esto). `app/services/billing.py` es el único punto que
  conoce `libracore.db`; el resto de la app no lo importa directo.
  `billing.configure(path)` se llama una vez al arrancar (mismo patrón
  que `libragenda.database.configure()`), asegura el schema compartido
  (`init_core_schema`, `CREATE TABLE IF NOT EXISTS` — no hay Alembic
  para esta parte, LibraCore nunca lo tuvo) y una caja por defecto.

- Decisión — dominio: **CUIT y condición de IVA como extensión del
  paciente** (`patients.cuit`/`condicion_iva`, mismo patrón que
  `dni`/`birth_date`, migración `0009_patient_billing_fields`). MedLibra
  es de **instancia única por cliente** (arquitectura silo, igual que
  Contalibra/Restolibra) — una sola "empresa" ARCA, constante fija
  (`EMPRESA = "consultorio"`), sin tabla de empresas para elegir.
  `POST /appointments/{id}/complete` (nuevo endpoint, junto con
  `AppointmentService.complete()`/`InMemoryScheduler.complete()` de
  LibraGenda `v0.7.0`) completa el turno y, **solo si hay un precio
  configurado** para el servicio en esa sucursal (`service_prices`,
  opt-in — sin precio, no factura nada, mismo criterio que
  `branch_hours`), factura el total. La seña ya cobrada (si existe,
  vía `Deposit`/`medio_pago` de LibraGenda `v0.8.0`) y el saldo restante
  se registran como **dos movimientos de caja separados** — cada uno
  con su propio medio de pago — apuntando a la **misma** factura; la
  seña nunca genera su propia factura. Si hay saldo positivo sin
  `medio_pago` en el body, 422 (validado **antes** de completar el
  turno en LibraGenda — si se validara después, un turno podría quedar
  completado sin facturar y sin forma de reintentar, ya que `COMPLETED`
  no admite otra transición).

- Decisión — tipo de comprobante e IVA: `IVA_CODES` (dict chico,
  replicado de `IVA_CODES` de Contalibra en
  `web/routers/facturas.py`, no migrado a LibraCore por ser estable y
  minúsculo) mapea la condición de IVA del paciente al código que exige
  ARCA. El cálculo de IVA (`_split_iva`, 21% sobre el monto final)
  es una **simplificación documentada**: no contempla servicios de salud
  exentos ni otras alícuotas — a revisar con un contador antes de
  facturar contra ARCA real (el modo dev sigue usando CAE simulado,
  ver `TASKS.md`).

- Decisión — certificados ARCA: `PUT /config/arca` acepta
  `certificado_path`/`clave_path` como **strings** (rutas en el
  filesystem del servidor), no upload multipart — a diferencia de
  `clinical_documents`, que sí sube archivos. El admin coloca los
  archivos a mano (mismo patrón que Contalibra usaba antes de tener
  cualquier UI de carga). Upload propio queda como mejora futura si
  hace falta, no bloqueante para el flujo de facturación en sí.

- Consecuencias: `libragenda` actualizado a `v0.8.0`, `libracore` a
  `v0.16.1` (incluye el fix de `python-multipart` como dependencia
  runtime faltante, encontrado al revisar el CI de LibraCore de paso).
  36 tests nuevos (11 en `test_billing.py`, 2 en `test_patients.py`, 1
  en `test_deposits.py`, más los de LibraGenda). Verificado con la
  suite completa (con reruns para descartar el flake ya documentado del
  reloj de WSL2 — esta ronda encontró además un bug real preexistente y
  no relacionado, `test_reminders.py::test_dispatch_sends_due_
  reminders_and_is_idempotent`, reproducible en checkout limpio antes de
  cualquier cambio de esta sesión — flagueado aparte, no corregido acá)
  + end-to-end completo contra archivos SQLite reales (no `:memory:` —
  `libracore.db` abre una conexión nueva por llamada, así que
  `:memory:` le daría una base vacía distinta cada vez): login, config
  ARCA, turno con seña parcial (mercadopago) + saldo (efectivo),
  factura tipo B con CAE simulado, dos movimientos de caja apuntando a
  la misma factura, verificado leyendo ambos archivos SQLite
  directamente. Migración `0009` verificada con `upgrade head` →
  `downgrade -1` → `upgrade head` contra un archivo real, después de
  aplicar primero la cadena de LibraGenda (la de MedLibra depende de
  `clients`).

## ADR-017 — Dashboard: turnos, pacientes y recordatorios/señas

- Estado: aceptada
- Fecha: 2026-07-22
- Contexto: último ítem de Fase 2 sin alcance definido. Antes de
  codificar se le preguntó al usuario qué debía mostrar el primer corte
  (`AskUserQuestion`, opciones múltiples): eligió turnos, pacientes y
  recordatorios/señas — dejó **facturación/caja fuera** de este primer
  corte (queda para una entrega futura, aunque `libracore.db.caja.
  get_caja_resumen()` ya existiría listo para reusar cuando se pida).
- Decisión — alcance de la consulta: `GET /dashboard?date_from=&date_to=`
  (admin-only, fechas requeridas — sin default implícito de "este mes"
  que pudiera sorprender). Devuelve: turnos (total en el rango, conteo
  por estado, turnos de **hoy** — fecha real del servidor, no del
  rango pedido), pacientes (total activos, altas nuevas en el rango) y
  recordatorios enviados en el rango + señas pendientes (sin acotar por
  fecha, es un conteo global de "lo que falta confirmar ahora").
- Decisión — sin tabla ni estado propio: `DashboardService` es pura
  lectura sobre repositorios que ya existían (`AppointmentRepository`,
  `PatientRepository`, y dos métodos nuevos en LibraGenda —
  `SentReminderRepository.list_sent()`/`DepositRepository.
  list_by_status()`, ver ADR-008 de LibraGenda, agregados porque
  ninguna de las dos consultas existía todavía). Nada se agrega a
  `PatientRepository` salvo dos métodos de conteo puntuales
  (`count_active()`, `count_created_between()`) — no se expone
  `created_at` en el CRUD público de `/patients` para no romper el
  schema existente, es un dato interno del dashboard.
- Decisión — `patients.created_at` (migración `0010_patient_created_at`,
  nullable, sin backfill): pacientes dados de alta antes de esta feature
  quedan con `created_at=NULL` y nunca cuentan como "nuevos" en ningún
  rango — comportamiento aceptado, no hay forma real de reconstruir esa
  fecha para datos preexistentes.
- Consecuencias: 7 tests nuevos (167 en total). Un bug real encontrado
  y corregido **en el propio test**, no en el código de producto: el
  primer intento de `test_dashboard_counts_appointments_by_status_and_
  today` usaba un turno a "+2 horas" y comparaba contra el rango de
  "hoy" calculado por separado — cerca de medianoche UTC (esta sesión
  corrió a las 23:57 UTC) el turno cae en el día siguiente y el conteo
  daba 0, no 1. No era un bug del dashboard: corregido derivando el
  rango de consulta de la fecha real del turno creado, no de una
  asunción de "hoy" separada. La verificación end-to-end posterior
  contra archivos SQLite reales **reprodujo este mismo cruce de
  medianoche en vivo** (corrió a las 23:58 UTC) y confirmó que cada
  métrica se comporta correctamente cuando el turno cae en una fecha
  distinta a "ahora": turnos.hoy=0 (turno es mañana), pacientes.
  nuevos_en_periodo=0 y recordatorios_enviados_en_periodo=0 (paciente y
  recordatorio se crearon "hoy", el rango consultado es "mañana"),
  senas_pendientes=1 (no acota por fecha, cuenta global). Migración
  `0010` verificada con el ciclo `upgrade`→`downgrade`→`upgrade` contra
  un archivo real. `libragenda` actualizado a `v0.9.0`.

## ADR-018 — Onboarding multi-consultorio: planes con enforcement real + infraestructura de deploy

- Estado: aceptada
- Fecha: 2026-07-25
- Contexto: Fase 3 ("producto") de `ROADMAP.md` no había arrancado —
  MedLibra nunca se había desplegado a ningún servidor. Antes de
  codificar se resolvieron con el usuario (`AskUserQuestion`) dos
  decisiones reales, replicando el mismo proceso que ya se siguió para
  el ADR-013 equivalente de Gestiolibra: (1) cómo repartir el catálogo
  de módulos gateables entre planes, dado que MedLibra suma un dominio
  clínico entero (pacientes, historia clínica, recetas, estudios,
  documentos, consentimientos) que Gestiolibra no tiene; (2) precio de
  referencia por plan.
- Decisión — estructura de planes: **todo el dominio clínico queda
  siempre libre**, igual criterio que "turnos nunca se gatea" en
  Gestiolibra pero extendido a todo lo clínico — necesidad profesional
  básica de un consultorio, no un extra comercial. Básico = catálogo +
  turnos + pacientes + historia clínica + recetas + estudios +
  documentos clínicos + consentimientos (siempre gratis, nunca
  gateable). Estándar = Básico + recordatorios/señas. Premium =
  Estándar + facturación/dashboard. Mismo split exacto de módulos
  gateables que Gestiolibra (`recordatorios`, `senas`, `facturacion`,
  `dashboard`), pero el conjunto "siempre libre" es mucho más grande acá.
- Decisión — precios: $25k/$40k/$60k (Básico/Estándar/Premium), más alto
  que Gestiolibra ($15k/$25k/$40k) — MedLibra apunta a consultorios y
  profesionales de salud, no a negocios de servicios chicos.
- Decisión — planes y gating: `plans.py` en la raíz del repo, mismo
  patrón exacto que Gestiolibra (`PLANES`, `PLAN_MODULOS`,
  `aplicar_plan_en_db()` con `sqlite3` crudo). Tabla `modulos`
  (migración `0011_modulos`, idéntica a la `0005_modulos` de
  Gestiolibra). Seed por defecto: todo habilitado (`habilitado=True`)
  hasta que se aplique un plan real. `require_module(nombre)`
  (`app/modules_gate.py`) gatea completo los routers de
  recordatorios/señas/facturación/dashboard con 403 — patients,
  clinical_notes, prescriptions, study_orders, clinical_documents,
  consents, appointments y agenda nunca se gatean. El caso más delicado,
  `complete()` de turno, replica el mismo criterio de Gestiolibra: el
  chequeo de `modules.is_enabled("facturacion")` corre *dentro* del
  propio endpoint (no como dependency de router completo), controlando
  si se busca el precio del servicio — sin el módulo habilitado,
  completar el turno nunca pide `medio_pago` ni factura, pero el turno
  igual se completa. Se encontró y corrigió un bug real durante la
  verificación por tests: la primera versión de `complete_appointment`
  no tenía ningún chequeo de módulo (a diferencia del endpoint
  equivalente de Gestiolibra, que sí lo tenía desde su propio ADR-013)
  — `test_complete_skips_invoicing_when_facturacion_module_disabled`
  falló con 422 en vez de 200 hasta agregar el `Depends(get_module_repository)`
  y el `if modules.is_enabled("facturacion")` alrededor de la búsqueda
  de precio, exactamente como en Gestiolibra.
- Decisión — infraestructura de deploy: `Dockerfile`, `docker-compose.yml`,
  `app/asgi.py`, `scripts/{nuevo_cliente,panel_admin,npm_api,npm_setup}.py`
  — mismo patrón que Gestiolibra (silo: una instancia + una base SQLite
  aislada por cliente). MedLibra no tiene frontend todavía (a diferencia
  de Gestiolibra), así que el `Dockerfile` no tiene stage de node —
  Python puro. **Reutiliza las mismas deploy keys de LibraCore/LibraGenda
  que ya usa Gestiolibra** (mismo ssh-agent multi-key persistente del
  VPS, `agent-multi-libra.sock`) — las deploy keys son por-repo-destino
  (LibraGenda, LibraCore), no por-consumidor, así que no hace falta
  generar ninguna nueva para estas dos dependencias; el propio repo
  MedLibra sí va a necesitar su propia deploy key dedicada de solo
  lectura al clonarse al VPS (mismo patrón que `id_ed25519_gestiolibra`),
  todavía no generada — ver `TASKS.md`. Puertos: `medlibra-dev` en
  `8077` (siguiente libre después de `gestiolibra-dev` en `8075`/`8076`
  y antes de `restolibra-web` en `8079`), `base_port=8078` para clientes
  reales vía provisioning.
- Consecuencias: 19 tests nuevos (`test_plans.py` + `test_module_gating.py`,
  188 en total), verificados contra la suite completa. Migración
  `0011_modulos` verificada con `alembic upgrade head` contra un archivo
  SQLite real con el schema completo de LibraGenda ya creado — la tabla
  `modulos` aparece correctamente, sin FKs hacia el dominio clínico.
  `app/asgi.py` verificado con ambos modos (`DATABASE_URL` explícito y
  el contrato `DATA_DIR`/`ADMIN_USER`/`ADMIN_PASSWORD` que genera
  `libracore.provisioning`). `scripts/panel_admin.py` verificado con un
  import real. El primer deploy real al VPS (build de imagen + alta de
  cliente de prueba) se hizo en la misma sesión, ver ADR-019 — a
  diferencia de Gestiolibra, que separó el scaffolding (su ADR-013) del
  primer deploy real (su ADR-014) en rondas distintas.

## ADR-019 — Primer deploy real de MedLibra al VPS Donweb

- Estado: aceptada
- Fecha: 2026-07-25
- Contexto: cerrando ADR-018, se hizo el primer build de Docker y la
  primera alta de cliente real en el VPS — nunca antes desplegado a
  ningún servidor (a diferencia de Gestiolibra, que ya tenía su cliente
  de prueba corriendo desde su propio ADR-014).
- Decisión — deploy key propia: generada `id_ed25519_medlibra` (ed25519,
  sin passphrase) en el VPS, registrada como deploy key de solo lectura
  en el repo `medlibra` vía `gh repo deploy-key add` (ejecutado desde la
  sesión WSL local con `gh` ya autenticado — el asistente no maneja
  tokens/contraseñas directamente, coherente con el estándar del wiki).
  Alias `github-medlibra` agregado a `~/.ssh/config` del VPS, **antes**
  del bloque genérico `Host *` (mismo cuidado que el resto del
  ecosistema — ver `wiki/entities/vps-donweb.md`). Verificado con
  `ssh -T github-medlibra` → "Hi marianocappucci/medlibra!" antes de
  clonar.
- Decisión — reutilizar deploy keys existentes para las dependencias:
  ninguna deploy key nueva para LibraCore/LibraGenda — el ssh-agent
  multi-key persistente del VPS (`agent-multi-libra.sock`, cargado
  originalmente para Gestiolibra) ya tenía ambas cargadas, y las deploy
  keys son por-repo-destino, no por-consumidor. `panel_admin.py
  actualizar` con `LIBRACORE_SSH_KEY=/root/.ssh/agent-multi-libra.sock`
  construyó `medlibra:latest` sin ningún bug de identidad SSH (el
  problema de "primera key que acepta el agente" que sí apareció en el
  primer build de Gestiolibra, ver su ADR-014, ya estaba resuelto por
  los alias `IdentitiesOnly yes` horneados en el `Dockerfile` desde
  ADR-018 — replicados de Gestiolibra desde el principio, no
  descubiertos de nuevo).
- Decisión — instalación de `panel_admin.py` en el host (fuera de
  Docker): `.venv-scripts` propio necesita solo `libracore` (no
  `libragenda`, que `panel_admin.py` no importa). En vez de pasar por
  el ssh-agent multi-key (con riesgo de ambigüedad si algún día se
  necesitaran ambas identidades en la misma operación), se instaló
  apuntando `GIT_SSH_COMMAND` directo al archivo de la deploy key de
  LibraCore (`-i /root/.ssh/id_ed25519_libracore -o IdentitiesOnly=yes`)
  — sin pasar por el agente, sin ambigüedad posible, mismo patrón
  implícito que ya usaba el `.venv-scripts` de Gestiolibra.
- Consecuencias: repo clonado a `/root/medlibra` (el directorio ya
  existía con un `.env.dev` residual de la Fase 0, movido a
  `/root/medlibra.env.dev.bak` sin borrar — quedó obsoleto desde que
  MedLibra pasó a SQLite-only, ver ADR-015). Imagen `medlibra:latest`
  construida con éxito (LibraGenda `v0.9.0` + LibraCore `v0.16.1`
  resueltos por SSH sin conflicto de identidad). Cliente de prueba
  `prueba` (puerto `8078`, plan Premium) dado de alta con
  `nuevo_cliente.py`: contenedor `medlibra-prueba` healthy, verificado
  con `curl` (`/health` 200), login real (`admin`/contraseña generada),
  endpoint clínico (`GET /patients`) respondiendo `200 []` sin ningún
  gating (confirma ADR-018: lo clínico nunca se bloquea por plan) y
  `GET /dashboard` respondiendo con datos reales (plan Premium incluye
  el módulo). `panel_admin.py listar` confirma el cliente `running`.
  Queda corriendo en el VPS como evidencia del pipeline completo — sin
  build de Docker previo desde cero en este VPS para MedLibra hasta
  esta ronda. Dominio propio (`dev.medlibra.com.ar` + proxy NPM + SSL)
  se resolvió en la sesión siguiente, ver ADR-020.

## ADR-020 — Dominio y SSL real: dev.medlibra.com.ar

- Estado: aceptada
- Fecha: 2026-07-25 (continuación)
- Contexto: siguiente pendiente elegido por el usuario entre los que
  quedaron abiertos tras ADR-018/ADR-019. `medlibra.com.ar` ya estaba
  registrado con DNS apuntando a este VPS (confirmado con `getent
  hosts` para `medlibra.com.ar` y `dev.medlibra.com.ar`, ambos
  resolviendo a la IP del VPS — no hacía falta tocar DNS), a diferencia
  de lo que se pensaba antes de verificar.
- Decisión — levantar `medlibra-dev` primero: el dominio de dev tiene
  que apuntar al contenedor de desarrollo (bind-mount + `--reload`,
  puerto `8077`), no al cliente de prueba `prueba` (puerto `8078`,
  pensado como evidencia de onboarding, no como entorno de desarrollo
  expuesto). `docker compose up -d --build` con
  `LIBRACORE_SSH_KEY=/root/.ssh/agent-multi-libra.sock` (mismo valor
  que usa `panel_admin.py actualizar`) — sin esa variable, el build
  default cae a un solo archivo de key (`~/.ssh/id_ed25519_libracore`)
  y falla al clonar LibraGenda con el mismo problema de identidad única
  ya documentado. `.env` con `SECRET_KEY`/`MEDLIBRA_ADMIN_PASSWORD`
  generados (no existía todavía, nunca se había levantado este
  servicio). Bug menor encontrado y corregido: `dev-data/` (donde
  `docker-compose.yml` apunta el SQLite de dev) no existía en el host
  — `sqlite3.OperationalError: unable to open database file` hasta
  crear el directorio.
- Decisión — reutilizar la instancia de NPM de Gestiolibra: mismo
  criterio que su propio ADR-016 — se copió `scripts/.npm_config.json`
  de Gestiolibra a MedLibra tal cual (misma instancia NPM, mismas
  credenciales admin), corrigiendo `forward_host` a `172.18.0.1`
  (gateway de la red docker compartida `stack_stack-net`) desde el
  principio — ya no hizo falta redescubrir el hallazgo de Gestiolibra
  (el nombre de contenedor heredado del `.npm_config.json` de
  Contalibra que causó el primer proxy mal apuntado en su momento).
  `client.create_proxy_host("dev.medlibra.com.ar", forward_host,
  8077, ssl=True)` sobre `libracore.npm_api.NPMClient` — certificado
  Let's Encrypt real solicitado automáticamente por NPM.
- Consecuencias: `dev.medlibra.com.ar` sirviendo tráfico real por
  HTTPS con certificado válido (verificado con `curl -v` mostrando
  handshake TLS 1.3 completo y `200 OK` en `/health`, tanto desde el
  propio VPS como desde la máquina de desarrollo — no solo loopback).
  Sin cambios de código en el repo (`.env`/`scripts/.npm_config.json`
  gitignoreados, igual que en el resto de la familia). Proxy host id
  `30` en NPM.

## ADR-021 — Primer frontend de MedLibra: MVP de login + agenda/turnos

- Estado: aceptada
- Fecha: 2026-07-25 (sesión siguiente)
- Contexto: MedLibra fue, desde el scaffold, API JSON pura — a
  diferencia de [[gestiolibra]] (mismo motor de turnos, mismo stack de
  backend), nunca tuvo Fase 4 de frontend. El usuario confirmó
  `dev.medlibra.com.ar` sirviendo `{"detail":"Not Found"}` en la raíz y
  preguntó si eso era correcto — lo era: no había ningún frontend
  buildeado, solo la API. Se decidió arrancar el frontend, con el mismo
  alcance de primer corte que tuvo Gestiolibra en su propio ADR-019:
  **login + agenda/turnos**, dejando pacientes/historia clínica/
  recetas/estudios/documentos/consentimientos/dashboard/facturación
  para rondas siguientes.
- Decisión — mismo stack, mismo patrón exacto que Gestiolibra: React 19
  + TypeScript + Vite, Tailwind CSS + shadcn/ui, TanStack Table, React
  Hook Form + Zod (el estándar ya consolidado de la familia, ver
  `estandares-desarrollo.md` del wiki) — arrancado directo en el
  estándar actual, sin repetir el recorrido histórico de Gestiolibra
  (que empezó con `useState` a mano y sumó TanStack/RHF/Zod en una
  ronda posterior, ADR-026 de ese repo). Scaffold copiado tal cual
  desde el `frontend/` de Gestiolibra (config de Vite/Tailwind/shadcn,
  `components.json`, primitivos `ui/*`, `data-table.tsx`,
  `AuthContext.tsx`, `main.tsx` — todos genéricos, sin lógica de
  negocio) y adaptado: `api.ts` con `Patient` en vez de `Client`
  (mismos campos que ya expone `/patients`: `dni`/`birth_date` además
  de los genéricos), `Login.tsx`/`Layout.tsx` con branding "MedLibra",
  `Agenda.tsx` con "Paciente" en vez de "Cliente" en toda la UI. El
  selector de paciente del formulario de turno lee `GET /patients`
  (ya abierto a `staff`+`admin` desde el MVP del backend) — el CRUD de
  pacientes desde el frontend queda para una ronda siguiente, mismo
  orden que Gestiolibra (Clientes/Dashboard se sumaron después del MVP
  de login+agenda, no en el mismo corte).
- Decisión — sin diálogo de medio de pago/factura todavía: a
  diferencia del `Agenda.tsx` *actual* de Gestiolibra (que ya tiene el
  flujo de ADR-027/028 de ese repo), el de MedLibra usa el `POST
  .../complete` directo y sin body, igual que la primera versión
  histórica de Gestiolibra antes de que existiera facturación en su
  frontend — coherente con el alcance acordado (solo login+turnos).
  Cuando se sume facturación al frontend de MedLibra, se portará el
  mismo patrón de diálogos ya probado en Gestiolibra.
- Decisión — Dockerfile/asgi.py: mismo patrón exacto que Gestiolibra
  (stage `node:20-slim` horneado en `/opt/frontend-dist`, fuera del
  árbol `/app` bind-montado por el compose de dev — ver ADR-022 de
  Gestiolibra sobre por qué horneado fuera de `/app` en vez de un
  volumen anónimo). `app/asgi.py` monta `/assets` + catch-all a
  `index.html`. `npm install` sin lockfile propio falló por un
  conflicto de resolución de peer dependencies entre
  `@hookform/resolvers`/`valibot` — se copió el `package-lock.json` de
  Gestiolibra (mismas versiones exactas ya probadas) en vez de dejar
  que npm resolviera de cero.
- Consecuencias: `npm run build` sin errores de tipos (bundle ~540 KB
  gzip ~166 KB). 187 tests de backend sin cambios de comportamiento
  (solo `app/asgi.py` tocado del lado backend). Build de Docker
  reconstruido y desplegado en `dev.medlibra.com.ar` real: la raíz ya
  no devuelve `404`, sirve la SPA. Verificado en el browser real:
  login con las credenciales del contenedor `medlibra-dev`, página de
  Agenda con el label "Paciente" en vez de "Cliente" en todos lados,
  ciclo completo de un turno (alta → confirmar → completar) verificado
  contra la API real — `GET /resources/{id}/agenda` confirma
  `"status": "completed"` después de usar el botón "Completar" de la
  UI real. Sin errores de consola. Un `dialog.tsx` copiado sin uso (no
  hace falta para este alcance) se sacó antes de este commit final —
  hallazgo de proceso, no del producto: un primer intento de borrarlo
  con una ruta Windows no llegó a escribir en el filesystem de WSL,
  quedó commiteado por error y se corrigió en un commit aparte.

## ADR-022 — Frontend: página de Pacientes (CRUD)

- Estado: aceptada
- Fecha: 2026-07-25 (continuación de la sesión anterior)
- Contexto: primer ítem de contenido tras el MVP de login+agenda
  (ADR-021). El usuario definió el orden de las páginas que faltan
  (pacientes → dominio clínico → dashboard → facturación, mismo orden
  que siguió Gestiolibra) y eligió empezar por Pacientes — hoy el
  selector de paciente del formulario de turno en `Agenda.tsx` es de
  solo lectura, sin forma de dar de alta un paciente nuevo desde la UI.
- Decisión — mismo patrón que `Clientes.tsx` de Gestiolibra
  (formulario React Hook Form + Zod, tabla TanStack), con dos
  diferencias reales de dominio, no de mecanismo:
  1. **Campos propios de Patient**: `dni` y `birth_date` (fecha de
     nacimiento) se suman a los genéricos (teléfono, email, CUIT,
     condición de IVA) que ya tenía `Client`.
  2. **Gating por rol distinto**: en Gestiolibra el CRUD de catálogo
     completo (incluidos Clientes) es admin-only. En MedLibra, `staff`
     representa personal médico con necesidad real de dar de alta y
     editar pacientes como parte de su trabajo diario — el backend ya
     lo refleja así (`POST`/`PUT /patients` sin restricción de rol más
     allá de estar logueado, solo `DELETE` exige admin, ver
     `app/routers/patients.py`). El frontend replica exactamente ese
     gating: alta/edición visibles para `staff`+`admin`, botón
     "Eliminar" solo para `admin`.
- Decisión — sin auto-generar el `id`: a diferencia del `Client.id` de
  Gestiolibra (que se volvió opcional en su propio ADR-024 por ser una
  operación de alta frecuencia), `PatientCreate` sigue exigiendo un
  `id` explícito en el formulario — mismo comportamiento que
  branches/resources/services en este repo hoy, ningún otro endpoint
  de MedLibra autogenera id todavía. Queda anotado en `TASKS.md` como
  mejora posible, no aplicado de entrada para no tomar una decisión de
  arquitectura sin que el usuario la pida.
- Consecuencias: `npm run build` sin errores de tipos (bundle ~547 KB
  gzip ~168 KB). Verificado de punta a punta en `dev.medlibra.com.ar`
  real, con ambos roles:
  - **admin**: alta de un paciente nuevo (`Ana García`, DNI y teléfono)
    confirmada contra la API real (`POST /patients` → `201`), edición
    del teléfono confirmada (`PUT` → `200`, tabla refleja el cambio),
    borrado confirmado (`DELETE` → `204`, paciente ya no aparece en
    `GET /patients`).
  - **staff** (usuario `staff-1` creado para esta verificación): el
    botón "+ Nuevo paciente" y "Editar" están presentes, el botón
    "Eliminar" **no aparece** — confirma que el gating de rol del
    frontend coincide exactamente con el del backend.
  Sin errores de consola en ningún caso. Sin cambios de backend.

## ADR-023 — Frontend: ficha del paciente (dominio clínico completo)

- Estado: aceptada
- Fecha: 2026-07-25 (continuación de la sesión anterior)
- Contexto: segundo ítem del orden acordado (pacientes → dominio clínico
  → dashboard → facturación, ver ADR-022). El backend ya expone historia
  clínica, recetas, estudios, documentos clínicos y consentimientos
  desde la Fase 2 (ADR-011 a ADR-014), pero ninguno tenía UI todavía.
- Decisión — una sola página "ficha del paciente" con pestañas, en vez
  de páginas sueltas por dominio: `/pacientes/:id`
  (`frontend/src/pages/PacienteFicha.tsx`), con un componente `Tabs` de
  shadcn nuevo (`components/ui/tabs.tsx`, wrapper sobre
  `radix-ui`'s `Tabs`) y 5 `TabsContent`: Historia clínica, Recetas,
  Estudios, Documentos, Consentimientos. Se llega desde un link "Ver
  ficha" nuevo en cada fila de la tabla de `Pacientes.tsx`. Todas las
  secciones respetan el mismo diseño append-only del backend — crear y
  listar, nunca editar; borrar solo para `admin` (mismo patrón
  `isAdmin && (...)` copiado en las 5 secciones, sin lógica especial
  por pestaña).
- Decisión — formularios dinámicos con `useFieldArray` para recetas y
  estudios: una receta o un pedido de estudios pueden tener varios
  ítems (igual que el backend los modela), así que el formulario de
  alta permite agregar/quitar filas antes de enviar, en vez de forzar
  un ítem por request.
- Decisión — resultados de estudio como mini-formulario por ítem: cada
  ítem de un pedido de estudios puede recibir uno o más resultados
  propios (`POST .../items/{item_id}/results`), append-only y
  desacoplado del pedido. En vez de sumar otro nivel de React Hook Form
  anidado, cada ítem renderiza un `AddResultForm` chico con estado
  local (`useState`, no RHF) — la complejidad de un formulario anidado
  dentro de un `useFieldArray` no se justificaba para dos campos
  (autor, texto).
- Decisión — documentos clínicos vía `api.postForm` nuevo: la única
  ruta multipart de todo el frontend. Se agregó `postFormData()` a
  `api.ts` (fetch sin `Content-Type` manual, el browser arma el
  boundary) en vez de reusar `request()` (que siempre serializa a
  JSON). El input de archivo es un `<input type="file">` nativo, sin
  componente shadcn — no hay ninguno en el stack estándar de la
  familia para esto.
- Decisión — autor pre-cargado desde la sesión: todos los formularios
  de alta (`author`) arrancan con `user.name` del usuario logueado
  como valor por defecto, editable — la mayoría de las veces quien
  carga el registro es quien lo firma, pero no siempre (ej. un
  administrativo cargando en nombre de un profesional), de ahí que
  quede editable en vez de fijo o solo lectura.
- Consecuencias: dos componentes shadcn nuevos (`Tabs`, `Textarea`,
  ninguno existía en el frontend de MedLibra ni en el de Gestiolibra
  todavía). `npm run build` sin errores de tipos. Verificado de punta a
  punta en `dev.medlibra.com.ar` real como `admin` contra la API real:
  nota de historia clínica (`POST /patients/{id}/notes` → `201`),
  receta con un ítem (`POST .../prescriptions` → `201`), pedido de
  estudios con un ítem más un resultado agregado sobre ese ítem
  (`POST .../study-orders` → `201`, `POST .../results` → `201`),
  documento subido y descargado con el contenido exacto
  (`POST .../documents` → `201`, `GET .../file` → `200`,
  `content-type: application/pdf`), consentimiento con selector
  "Paciente"/"Tutor o responsable" (`POST .../consents` → `201`). Como
  `staff-1`, la pestaña de historia clínica muestra la nota sin el
  botón "Eliminar" — mismo gating `isAdmin` verificado en ADR-022,
  reutilizado sin cambios en las 5 secciones nuevas. Sin errores de
  consola. Sin cambios de backend.

## ADR-024 — Frontend: dashboard

- Estado: aceptada
- Fecha: 2026-07-25 (continuación de la sesión anterior)
- Contexto: penúltimo ítem del orden acordado (pacientes → dominio
  clínico → dashboard → facturación, ver ADR-022/023). El backend ya
  expone `GET /dashboard?date_from=&date_to=` desde la Fase 2
  (ADR-017), admin-only y gateado por el módulo `"dashboard"` del plan
  (solo Premium lo incluye, ver `plans.py`), pero sin UI todavía.
- Decisión — mismo componente que `Dashboard.tsx` de Gestiolibra, sin
  la card de facturación: selector de rango de fechas (`Desde`/`Hasta`)
  + tres cards (Turnos por estado en el rango, Pacientes activos/
  nuevos en el rango, Recordatorios enviados/señas pendientes).
  MedLibra nunca sumó facturación/caja al dashboard (decisión ya
  tomada del lado del backend, ver `DECISIONS.md` ADR-017 — "queda
  para una entrega futura"), así que el frontend simplemente no tiene
  esa cuarta card que sí tiene Gestiolibra.
- Decisión — ruta `/reportes`, no `/dashboard`: mismo motivo que
  llevó a Gestiolibra a este mismo nombre en su momento — el catch-all
  del SPA (`app/asgi.py`, `spa_fallback`) se registra *después* de
  incluir todos los routers de la API, así que una navegación directa
  o un refresh en `/dashboard` sería interceptado por el endpoint real
  `GET /dashboard` (que exige `date_from`/`date_to` como query params
  obligatorios) en vez de servir el `index.html` del SPA. Se evitó la
  colisión de entrada, sin repetir el hallazgo que ya le costó el
  rename a Gestiolibra.
- Decisión — ítem de menú oculto para `staff`: mismo patrón
  `adminOnly` que ya usa Gestiolibra en su `Layout.tsx` (filtro sobre
  `NAV_ITEMS`), replicado tal cual — coherente con que el endpoint es
  admin-only del lado del backend. La página en sí sigue siendo
  alcanzable navegando directo a `/reportes` (no hay guard de ruta por
  rol, solo el filtro del menú), y en ese caso muestra el mismo
  mensaje de error dedicado para 403 que ya usa Gestiolibra ("no
  tenés acceso... requiere rol admin y el módulo habilitado en el
  plan") en vez de un error genérico.
- Consecuencias: `npm run build` sin errores de tipos. Verificado de
  punta a punta en `dev.medlibra.com.ar` real: como `admin`, `GET
  /dashboard` responde `200` con datos reales (paciente de prueba
  reflejado en "activos"/"nuevos en el rango"), ítem de menú "Dashboard"
  visible. Como `staff-1`, el ítem de menú no aparece, y navegando
  directo a `/reportes` la página muestra el mensaje de acceso
  denegado (`GET /dashboard` responde `403` real, confirmado en la
  pestaña de red). Sin errores de consola. Sin cambios de backend.

## ADR-025 — Frontend: facturación (cierra la Fase 4)

- Estado: aceptada
- Fecha: 2026-07-25 (continuación de la sesión anterior)
- Contexto: último ítem del orden acordado (pacientes → dominio
  clínico → dashboard → facturación, ver ADR-022/023/024). El backend
  ya exponía `PUT`/`GET /config/arca` (admin-only) y facturaba
  automáticamente al completar un turno con saldo pendiente
  (`POST /appointments/{id}/complete`, 422 si falta `medio_pago`)
  desde la Fase 2 (ADR-016), pero sin ninguna de las dos piezas en la UI.
- Decisión — mismo componente que `Facturacion.tsx` de Gestiolibra,
  sin cambios de campos: el schema `ArcaConfigIn`/`ArcaConfigOut` de
  MedLibra ya coincidía exactamente (CUIT, punto de venta, ambiente,
  paths de certificado/clave — MedLibra tampoco tiene upload real,
  mismo pendiente documentado que Gestiolibra). Página `/facturacion`
  con el formulario de configuración ARCA.
- Decisión — diálogo de medio de pago en `Agenda.tsx`, portado tal
  cual del mismo lugar en Gestiolibra: al hacer clic en "Completar",
  si el backend responde `422` (saldo pendiente sin `medio_pago`), se
  abre un diálogo para elegir cómo se cobró en vez de mostrar el error
  crudo; al confirmar, se reintenta `complete` con el `medio_pago`
  elegido. Si la respuesta incluye una factura, se abre un segundo
  diálogo mostrando tipo de comprobante, número, CAE y total. Los
  cuatro medios de pago (`efectivo`/`transferencia`/`tarjeta`/
  `mercadopago`) son los mismos que ya usa `libracore.db.caja` en
  ambos productos.
- Decisión — ítem de menú "Facturación" oculto para `staff`, mismo
  filtro `adminOnly` ya usado para el dashboard (ADR-024) — coherente
  con que tanto `/config/arca` como la parte de facturación de
  `complete` son admin-only/gateadas por el módulo `"facturacion"` del
  plan.
- Componente `Dialog` (shadcn) recreado en `components/ui/dialog.tsx`
  — se había sacado del scaffold inicial por no usarse todavía en el
  MVP de login+agenda (ver ADR-021).
- Consecuencias: `npm run build` sin errores de tipos. Verificado de
  punta a punta en `dev.medlibra.com.ar` real como `admin`: config ARCA
  guardada (`PUT /config/arca` → `200`), precio de servicio configurado
  (`PUT /services/{id}/prices`), turno completado con saldo pendiente
  → diálogo de medio de pago → `POST .../complete` primero `422` (sin
  `medio_pago`) y luego `200` (con `medio_pago: efectivo`) → diálogo de
  factura emitida con datos reales (Factura B, número `0003-00000001`,
  CAE, total `$15.000,00`, coincidiendo con el punto de venta
  configurado). Como `staff-1`: ni "Dashboard" ni "Facturación"
  aparecen en el menú, y navegando directo a `/facturacion` se ve el
  mismo mensaje de acceso denegado dedicado. Sin errores de consola.
  Sin cambios de backend. **Con esto se completa el frontend de
  MedLibra (Fase 4): login, agenda/turnos, pacientes, dominio clínico
  completo, dashboard y facturación.**

## ADR-027 — Alícuota de IVA configurable por servicio

**Fecha:** 2026-08-02
**Estado:** aceptada

### Contexto

`billing._split_iva()` separaba subtotal e IVA asumiendo **21% fijo**. El
propio docstring lo marcaba como simplificación a revisar con un contador
antes de facturar contra ARCA real. En un producto de salud el 21% no es
una simplificación menor: la mayoría de las prestaciones médicas están
**exentas** de IVA y algunas tributan al 10,5%, así que el caso por defecto
estaba mal.

Al relevarlo apareció algo que cambia el diseño: `libracore.arca_wsfe`
**deriva la alícuota de los números**, no de un campo. Calcula
`pct = round(iva / sub * 100, 1)` y con `pct == 0` arma el comprobante con
`ImpNeto=0.00`, el importe en `ImpOpEx` y **sin** bloque `<AlicIva>` — que
es exactamente como ARCA espera una operación exenta. **No hace falta tocar
LibraCore**: alcanza con que MedLibra calcule bien el par subtotal/IVA.

Y una trampa: `_iva_id()` resuelve el `Id` de ARCA con
`_IVA_ID.get(round(pct, 1), _IVA_ID.get(round(pct), 5))`. Ante un
porcentaje que no conoce **cae al Id 5, que es 21%**. Una alícuota
arbitraria (13%, por ejemplo) no fallaría: se declararía como 21% ante
ARCA, sin error a la vista.

### Decisión

1. **La alícuota vive en una tabla propia de MedLibra**
   (`service_iva_rates`, clave `service_id`), no en el `Service` de
   LibraGenda: el motor de turnos es genérico y no sabe de impuestos.
   Mismo patrón que `service_prices` (ADR-013).
2. **Default por instancia** en `business_settings.default_iva_rate`. Un
   consultorio con todas sus prestaciones exentas lo baja a 0 una sola vez,
   en vez de servicio por servicio. Un servicio sin alícuota propia hereda
   ese default, y el endpoint lo dice explícitamente (`inherited: true`) —
   sin ese flag la pantalla no puede distinguir "exento porque alguien lo
   decidió" de "exento porque lo es todo el consultorio".
3. **Lista cerrada de alícuotas**: 0%, 10,5%, 21% y 27%, las cuatro que
   `_IVA_ID` mapea. Cualquier otra se rechaza con 422. No es validación
   cosmética: es lo que evita que una alícuota inválida se declare
   silenciosamente como 21%.
4. **El default arranca en 21%**, el valor que ya estaba hardcodeado. La
   migración no le cambia la facturación a ninguna instalación existente;
   el cambio de comportamiento es siempre una acción explícita del usuario.
5. **`default_iva_rate` es opcional en el `PUT /business`** y omitirla deja
   la que estaba. Un PUT que sólo renombra el consultorio no tiene por qué
   moverle la alícuota a la facturación.

### Consecuencias

- Una prestación exenta se factura con el total entero como subtotal e IVA
  0, y viaja a ARCA en `ImpOpEx`. Hay un test que arma el **XML real** de
  `libracore.arca_wsfe` con el transporte interceptado y lo verifica, junto
  con su contracara al 21% — sin esa segunda mitad, un bug que mandara todo
  a `ImpOpEx` también pasaría el primero.
- **Esto no decide la política fiscal.** Qué alícuota le corresponde a cada
  prestación lo carga el usuario con su contador; lo que se cierra acá es
  que antes no había forma de expresarlo.
- Falta la pantalla: hoy la alícuota se configura por API. Cuando se sume
  al frontend, va en la misma pantalla donde ya se carga el precio del
  servicio.

## ADR-026 — Endpoint `POST /auth/verify` para el login de `/docs/` de medlibra_web

- Estado: aceptada
- Fecha: 2026-07-26
- Contexto: se construyó `medlibra_web`, la landing de marketing del
  producto, con documentación técnica en `/docs/` gateada por login —
  mismo patrón que ya usan Contalibra/Restolibra/Gestiolibra: la landing
  no guarda usuarios propios, valida en tiempo real contra la instancia
  real del cliente vía un endpoint interno protegido por un secreto
  compartido (`DOCS_AUTH_SECRET`). Ese endpoint no existía todavía en
  MedLibra.
- Decisión: mismo diseño exacto que Gestiolibra (ADR-029 de ese repo,
  construido el mismo día). `POST /auth/verify` en
  `app/routers/auth.py`, junto a `/login`/`/logout`/`/me`. Recibe
  `username`/`password`, exige el header `X-Internal-Auth` comparado
  con `hmac.compare_digest()` contra `DOCS_AUTH_SECRET` (leído del
  entorno en cada request, no al importar el módulo) y responde
  `{"valid": bool}` reusando `UserRepository.check_credentials()`, sin
  crear cookie de sesión. Falla cerrado (401) si el secreto no está
  configurado.
- Consecuencias: 5 tests nuevos (`tests/test_auth_verify.py`), mismo
  set que Gestiolibra. Suite completa verificada en verde salvo el
  flake ya documentado del reloj de WSL2 (un test distinto en cada
  corrida, no relacionado con este cambio). Sin cambios de frontend ni
  de ningún otro endpoint. Detalle del lado de la landing en
  `medlibra_web` (`auth/app.py`).

## ADR-028 — La agenda corre en hora de pared, no en UTC

**Fecha**: 2026-08-22
**Estado**: Aceptada

### Contexto

El producto maneja dos unidades de tiempo distintas y las estaba mezclando:

- **Hora de pared**: lo que alguien escribe en el formulario y lo que dice el
  reloj del consultorio. Es la unidad de la disponibilidad del profesional
  (`Availability`, `(día de la semana, 09:00, 19:00)`), del horario de atención
  (`branch_hours`) y de las excepciones por fecha.
- **Instante**: lo que se guarda (`DateTime(timezone=True)`, normalizado a UTC
  por LibraGenda).

🔴 **El defecto de MedLibra no era el mismo que el de Gestiolibra**, y conviene
decirlo porque los dos productos comparten el archivo y la confusión ya dejó
rastro (ver abajo). Gestiolibra interpretaba el valor naive del formulario como
hora local del negocio y lo convertía a UTC **antes** de validar, así que
comparaba las 20:00 UTC contra una ventana cargada 9-19 y **rechazaba** el turno
de las 17:00: un 409 en la cara del usuario.

MedLibra nunca tuvo esa conversión. Trataba el valor naive como UTC de punta a
punta, así que su validación era internamente consistente —comparaba 17:00
contra 9-19 y aceptaba— y el defecto salía por el otro lado, **callado**: el
turno que la secretaria daba para las 17:00 se guardaba como `17:00Z`, o sea
las 14:00 del reloj del consultorio. Tres horas de corrimiento en el instante,
que es lo que después leen los recordatorios y cualquier consumidor que no esté
en UTC. Y por la puerta de un `starts_at` **con offset explícito** —lo que
manda una integración, no este formulario— MedLibra sí llegaba al 409 de
Gestiolibra: `20:00Z` se comparaba como las 20:00 contra 9-19.

Ninguno de los dos se veía en la práctica todavía, por una sola razón: las
sedes nacían en `UTC`. **Con offset cero, validar en el terreno equivocado da
exactamente el mismo resultado que validar en el correcto.**

El rastro de la confusión estaba en `scripts/seed_demo.py`, con una advertencia
que restringía los turnos de ejemplo a la mañana y culpaba a
`AppointmentService._resolve_utc` — **una función que nunca existió en este
repo**: era el nombre del código de Gestiolibra, copiado junto con la nota.

### Decisión

**La validación entera corre en hora de pared de la sede, y la conversión a
instante ocurre en el repositorio.** Es el mismo diseño que Gestiolibra
(su ADR-030), portado con el mismo pin de LibraGenda (`v0.9.0`) — no hace falta
cortar versión del motor.

No se toca el motor, y no por comodidad: `libragenda/timezones.py` declara el
contrato al revés — *"verticals are expected to collect wall-clock times ... and
convert at the boundary using this module, rather than teaching the scheduling
engine about civil time zones"*. El borde es este producto.

- `app/services/husos.py` (nuevo) concentra las cuatro conversiones.
- `_TurnosEnHoraLocal` adapta el repositorio de turnos: hacia el motor devuelve
  todo en hora de pared —la misma unidad de las ventanas, las excepciones y el
  horario de atención— y hacia la base guarda en UTC. Con eso el motor compara
  ventanas, excepciones, bloqueos y **choques entre turnos** en un solo terreno.
- Los bloqueos (`TimeBlock`) se cargan por el mismo formulario que un turno pero
  se guardan como instante: el router de disponibilidad los convierte en el alta
  y en la edición. Sin eso, un bloqueo cargado de 10 a 11 tapa de 7 a 8.
- `agenda()` filtra por el día **del calendario de la sede**.
- El huso por defecto de una sede nueva pasa de `UTC` a
  `America/Argentina/Buenos_Aires` (regla de arranque de la familia, 2026-08-12).

### Consecuencias

- **La suite pasa a correr con offset distinto de cero**, que es lo que hace
  visible el defecto. Cinco tests existentes cambiaron su valor esperado.
  `tests/test_reminders.py` pide explícitamente una sede en UTC porque mide
  plazos contra `now()` y el huso no es lo que prueba.
- 6 tests nuevos (325 en la suite). **Sólo tres fallan contra el código viejo**
  —los dos que asertan el instante guardado y el del `starts_at` con offset
  explícito—, y está dicho en el archivo: los otros tres cubren los síntomas que
  tuvo Gestiolibra y el estado intermedio de un arreglo a medias, no lo que
  MedLibra tenía roto. La primera versión de esos tres se escribió creyendo que
  reproducían el defecto de acá y **pasaban en verde contra el código viejo**.
- `test_block_prevents_booking_within_an_otherwise_open_window`, que ya existía,
  pasa a ser el único guard de la conversión de bloqueos — y lo es sólo porque
  la sede del fixture quedó en UTC-3. Está anotado en el test: volver esa sede a
  UTC apaga el guard sin poner nada en rojo.
- `scripts/seed_demo.py`: la advertencia se reemplaza por lo que pasó de
  verdad, y los turnos de ejemplo pasan a cubrir **de 9 a 17**, con dos
  profesionales solapados a la misma hora. Con todo amontonado antes del
  mediodía y sin superposiciones, una grilla horaria rota se ve igual que una
  sana — y la grilla llega en el próximo cambio.
- El umbral de turnos sembrados que el test de la demo verificaba pasa de
  `>= 7` (sobre un plan de 9) a **`== 11` exacto**: un turno que el alta rechaza
  no rompe nada, `sembrar()` lo saltea, y con margen la demo queda con menos
  turnos de los que dice tener, en verde.

## ADR-029 — La agenda como calendario, con el componente compartido

**Fecha**: 2026-08-22
**Estado**: Aceptada

### Contexto

Pedido del humano: *"agregar agenda normalizada, la que tiene libradesk y
gestiolibra por libra-ui"*.

`/agenda` era un formulario de alta arriba y una tabla abajo, con dos
`<input type="date">` de rango. Podía decir **qué** turnos hay, pero no **cuánto
ocupa cada uno ni dónde está el hueco**, que es la pregunta de quien atiende el
teléfono. Y para saber qué había el jueves había que mover el rango y perder de
vista el resto.

El calendario ya existía: salió de LibraDesk a `libra-ui/agenda` el mismo día
(v0.38.0) y Gestiolibra lo adoptó en su ADR-031. Traerlo acá es consumir el
paquete, no escribir un tercer calendario.

### Decisión

`libra-ui` sube de `v0.37.0` a `v0.38.0`. **El bump es puramente aditivo**: el
diff entre los dos tags son `src/agenda/*`, el export nuevo en `package.json` y
un stub de test — nada de lo que MedLibra ya consumía cambia.

El reparto es el que fija el propio paquete: de `libra-ui` la aritmética de días,
la paleta por posición, el reparto de ancho entre bloques que se pisan, la
rejilla horaria y las vistas de semana y mes; **de MedLibra** de dónde salen los
turnos, qué es un evento, el alta, las acciones sobre un turno y **la vista de
día**, cuyo encabezado es lo más específico de cada agenda (acá, el profesional
y su sede).

- `components/agenda/datos.ts` — una llamada por profesional con el rango
  entero, no siete de un día. El filtro de profesional recorta **al dibujar, no
  al pedir**: recortando el fetch, el "+N más" de la celda del mes pasaría a
  mentir en cuanto alguien elige uno.
- `components/agenda/eventos.ts` — **el título es el paciente**, no la
  prestación: en una agenda de turnos lo que se busca de un vistazo es a quién
  se atiende.
- `components/agenda/vista-dia.tsx` — una columna por profesional.
- **Todo el estado de la pantalla vive en la URL** (`?vista=`, `?dia=`,
  `?profesional=`, `?turno=`): se puede mandar "mirá el jueves" por mensaje, el
  botón atrás vuelve del turno al día y del día a la semana, y recargar deja al
  usuario donde estaba.

🔴 **El día de un turno es el de la sede, no el del navegador.** Es el mismo
defecto de ADR-028, del otro lado del cable: un turno de las 21:30 del lunes en
Buenos Aires viaja como `2026-07-21T00:30:00Z`. Agrupar por el primer tramo del
string lo pone en la columna del martes; agrupar con la zona del navegador pone
a cada usuario el turno en un día distinto. Se agrupa por la hora de pared de la
sede, que es la misma cuenta que hace el backend al filtrar.

### Consecuencias

- 11 tests nuevos (20 en la suite del frontend). **Medido**: reemplazando la
  conversión por el string crudo de UTC, dos se ponen en rojo — el del turno de
  la noche y el que lee la hora en el detalle. El tercero, *"la conversión no
  corre todos los turnos un día"*, es el control que impide arreglar el primero
  restándole un día a todo.
- **La paleta del calendario se verificó en el CSS emitido, no en el fuente.**
  `colores.ts` escribe las ocho clases enteras a mano porque Tailwind escanea
  texto, y el consumidor necesita `@source "../node_modules/libra-ui"` en su
  `index.css` o los bloques salen sin fondo. MedLibra ya lo tenía; se confirmó
  que las 16 clases (`bg-*-100` y `bg-*-400`) están en `dist/assets/index-*.css`,
  con una clase inventada como control negativo en 0.
- `api.ts` suma el tipo `Branch` y la pantalla pide `/branches`: el huso sale de
  ahí y sin eso no hay forma de saber a qué día pertenece cada turno.
- El alta, el diálogo de medio de pago y el de factura emitida **no se tocaron**:
  siguen siendo los de ADR-025.

## ADR-030 — El consultorio es una entidad, y la agenda se arma por bloques

**Fecha**: 2026-08-23
**Estado**: Aceptada

### Contexto

Pedido del humano (2026-08-22): *"parametrizar consultorios, entonces la agenda
del profesional se parametriza en un consultorio, en un rango horario, en un día
o días de la semana y se repite hasta determinada fecha"*, más *"agregar duración
de consulta (poner 10, 15, 20, 25, 30 minutos) y posibilidad de armar la agenda
por turnos o por demanda espontánea"*.

Lo único que MedLibra sabía ocupar era el **profesional** — el `Resource` de
LibraGenda. De ahí salían dos límites:

1. **El consultorio no existía.** La pregunta *"¿la Dra. Vidal y el Dr. Molina no
   están los dos en el Consultorio 2 a las 10?"* no se podía ni formular. Una
   sala tiene capacidad uno y es el recurso más escaso de una clínica chica: dos
   agendas correctas por separado se pisan en la puerta.
2. **`Availability` no sabe vencer.** Es `(profesional, día de la semana, 09:00,
   19:00)`: una vez cargada vale para siempre. El *"se repite hasta determinada
   fecha"* del pedido no era expresable, y tampoco la duración del turno ni la
   modalidad.

### Decisión

**Un consultorio no es un `Resource`.** El motor asocia un turno a *un solo*
recurso y busca choques sobre él (`find_conflicts`); modelar la sala como un
segundo `Resource` obligaría a un turno a ocupar dos, que es justo lo que el
motor no hace. La sala vive en MedLibra (`app/services/consultorios.py`) y su
choque lo valida `AppointmentService`. Es el reparto que LibraGenda ya declara:
el vertical resuelve lo que el motor no modela, en vez de deformar el motor.

**Un bloque de agenda no se guarda como `Availability`: se deriva.** El bloque
—profesional × consultorio × día de la semana × rango horario × vigencia ×
duración × modalidad— vive en `agenda_blocks`, y las ventanas que el motor
necesita se construyen **para el día que se está validando**. Así la vigencia
por rango de fechas se resuelve antes de que el motor la vea, sin enseñarle un
concepto nuevo ni cortar versión del paquete.

- **La duración la manda el bloque** (decisión del humano): la prestación dice
  *qué* se hace, el bloque dice cuánto dura un turno de esa agenda. La lista es
  cerrada (10/15/20/25/30) y la sirve el backend en `GET
  /agenda-blocks/opciones` — repetida en el frontend, las dos copias divergen y
  la pantalla termina ofreciendo un valor que el alta rechaza con 422.
- **El choque de sala se compara en UTC**, no en hora de pared: un consultorio
  puede recibir turnos de profesionales de sedes distintas, y dos horas de pared
  de husos distintos no se pueden comparar entre sí.
- **Un bloque `espontanea` no genera ventana.** Si la generara, se le podrían dar
  turnos con horario encima de una franja que justamente no trabaja con
  horarios. La cola por orden de llegada es un mecanismo aparte y llega en el
  cambio siguiente.
- **En qué sala ocurre un turno va en una tabla propia** (`appointment_rooms`) y
  no en una columna del turno: el turno es un dataclass del motor. Mismo patrón
  con el que `Patient` extiende al `Client` y `branch_contacts` a la sede. Sin
  FK a `appointments` a propósito — el motor no conoce esta tabla y no la
  limpiaría, y una FK dejaría su borrado fallando por algo que no ve.

### Compatibilidad

**Los bloques se suman a la disponibilidad semanal, no la reemplazan ni la
migran.** Las instancias que hoy están andando —dev, la demo— tienen su jornada
cargada por `/resources/{id}/availability` y tienen que seguir dando turnos
igual; sin bloque que cubra el horario, la duración sigue siendo la de la
prestación y no hay sala que declarar. La migración `0015` sólo crea tablas
vacías: un `upgrade` sobre una base con datos no le cambia el comportamiento a
nadie.

### Consecuencias

- 23 tests nuevos (348 en la suite). **Verificados por mutación**: apagando el
  chequeo de sala y la vigencia, se ponen en rojo exactamente tres —el choque de
  sala en el alta, el mismo al reprogramar, y el corte por `valid_to`— y los
  controles siguen verdes. Cada test que exige un rechazo tiene al lado el que
  exige que en el caso vecino **entre**: sin eso, "rechazar siempre" los pasaría
  a todos.
- **El log de actividad llamaba "consultorio" al `Resource`.** Con el
  consultorio como entidad propia eso pasó de confuso a incorrecto: el log
  habría dicho "consultorio Dr. Molina" al lado de consultorios de verdad. La
  etiqueta pasa a `profesional`, que es lo que el `Resource` es en este producto
  —lo dicen el seed y los mensajes de la agenda— y se suman las tres tablas
  nuevas al mapa.
- `app/services/agenda_blocks.py` lleva `from __future__ import annotations` y
  está dicho por qué: los repositorios de este proyecto tienen un método `list`
  (y acá además uno `set`), y dentro del cuerpo de la clase ese nombre tapa al
  builtin — `def vigentes(...) -> list[dict]` explota con *"'function' object is
  not subscriptable"*.
- Migración probada contra `postgres:16` real, con datos: `upgrade head` →
  filas cargadas → `downgrade -1` (las tres tablas se van, `resources` y
  `branches` quedan) → `upgrade head`.
- **Un hallazgo del cambio anterior, que apareció recién acá.** Al pasar el test
  de la demo de `>= 7` a una cuenta exacta (ADR-028), un lunes se puso en rojo
  con 9 de 11: la ventana que ese test mira iba de `hoy - 2` a `hoy + 5` en días
  de **calendario**, y el plan de la demo está en días **hábiles** — un lunes,
  los dos turnos de "ayer hábil" caen el viernes, tres días atrás, y quedaban
  afuera. El margen del `>= 7` se comía justo ese agujero, así que el test decía
  verde mirando 9 de 11 turnos. La ventana pasa a `hoy - 7` … `hoy + 10`.

## ADR-031 — La demanda espontánea es una fila, no un turno sin hora

**Fecha**: 2026-08-24
**Estado**: Aceptada

### Contexto

ADR-030 dejó los bloques de agenda con dos modalidades y **una a medias**: un
bloque `espontanea` se podía crear y, deliberadamente, no generaba ventana de
disponibilidad — así que no se le podía dar ningún turno y tampoco había otra
forma de anotar a nadie. Faltaba el mecanismo.

Al preguntarle al humano qué significaba operativamente *"por demanda
espontánea"*, eligió **sin horario, por orden de llegada**.

### Decisión

**No es un `Appointment` de LibraGenda, ni siquiera uno con horario inventado.**

Un `Appointment` **es** un horario: tiene `starts_at` y una duración, y todas
sus reglas —choques, ventanas, bloqueos, ocupación de sala— se calculan sobre
ese rato. Una demanda espontánea no tiene rato: tiene una **posición en una
fila**. Darle un `starts_at` de mentira —el inicio del bloque, digamos— haría
que ese horario falso choque contra los turnos de verdad, ocupe el consultorio y
aparezca en la grilla horaria como si alguien tuviera reservada esa media hora.
El dato inventado no se queda quieto: se propaga a todas las reglas que miran
horarios.

Entonces: tabla propia (`walkins`), sin pasar por el `InMemoryScheduler`. Lo que
sí comparte con un turno es **de dónde cuelga**: un bloque de agenda, con su
profesional, su consultorio y su vigencia.

- **El orden de llegada es histórico y no se renumera nunca.** Cancelar al
  segundo de la fila no convierte al tercero en segundo: el número dice en qué
  momento llegó cada uno, y reescribirlo borraría el único dato que la cola
  tiene — además de dejar a dos personas distintas habiendo sido "la segunda"
  del mismo día. Quién sigue se calcula filtrando por estado (`solo_activos`),
  no por el número.
- **El máximo para el número siguiente incluye a los cancelados**, por lo mismo.
- **Un único por `(block_id, day, arrival_order)`.** El número se asigna con un
  `max + 1`, que entre dos llegadas simultáneas es una condición de carrera.
  Sin la restricción, dos pacientes quedan en la misma posición y la fila se ve
  perfectamente bien.
- **Registrar una llegada valida el bloque, no sólo su existencia**: tiene que
  ser `espontanea` (sobre uno de `turnos` habría dos maneras simultáneas de
  ocupar la misma franja, cada una ciega a la otra) y el día tiene que caer en su
  día de la semana y su vigencia (si no, es una fila que nadie va a llamar).
- **Estados más chicos que los de un turno**: `waiting → in_progress →
  completed`, más `cancelled`. No hay `pending` ni `confirmed` —quien está en la
  fila ya llegó, no hay nada que confirmar— ni `no_show`, que es exactamente lo
  que la demanda espontánea no puede tener.
- **Va con los turnos y no con la configuración** (`staff_or_admin`): armar el
  bloque lo hace quien parametriza, pero anotar a quien acaba de entrar por la
  puerta lo hace la secretaria todas las mañanas. Con `admin_only` la función
  existiría y no la podría usar nadie del mostrador.

### Consecuencias

- 14 tests nuevos (372 en la suite), **verificados por mutación**: apagando la
  validación de modalidad, la de día y la tabla de transiciones se ponen en rojo
  exactamente cuatro, y los controles siguen verdes.
- Migración `0016_walkins`, probada contra `postgres:16` real: `upgrade` → filas
  cargadas → `downgrade -1` (la tabla se va, `agenda_blocks` queda) → `upgrade`.
  El único se verificó **en la base**, no en el modelo: un segundo `INSERT` con
  el mismo `(bloque, día, orden)` es rechazado por PostgreSQL.
- **Todavía no tiene pantalla.** Como el resto de la parametrización de agenda,
  hoy se opera por API. La pantalla llega con Configuración.

## ADR-032 — La parametrización de la agenda, adentro de Configuración

**Fecha**: 2026-08-24
**Estado**: Aceptada

### Contexto

ADR-030 y ADR-031 dejaron el backend entero —consultorios, bloques de agenda,
bloqueos, excepciones, fila de llegada— y **ninguna pantalla**. Los endpoints
existían y sólo se llegaba a ellos por API o por `scripts/seed_demo.py`: un
consultorio nuevo no podía parametrizar nada de lo suyo, que es exactamente el
estado en el que Gestiolibra estaba antes de su ADR-031.

### Decisión

Cuatro secciones nuevas **adentro de Configuración**, no como ítems propios del
sidebar: lo que se configura vive en un solo lugar, y estas cuatro son
exactamente eso — se cargan al arrancar y se tocan poco, a diferencia de la
agenda y los pacientes, que se usan todos los días.

🔴 **El orden es el del arranque de un consultorio nuevo**: Sedes →
Consultorios → Prestaciones → Profesionales. Al revés, un consultorio se carga
sin sede a la cual pertenecer, una prestación sin poder ponerle precio (el
precio es por sede) y un bloque de agenda sin consultorio donde ubicarlo — que
es el único campo del bloque que no se puede dejar vacío.

- **El armador de bloques deja elegir varios días de una vez y crea un bloque
  por día.** El backend modela un bloque por día de la semana a propósito —así
  el miércoles puede estar en otra sala—, pero cargar "lunes a viernes de 9 a
  13" como cinco altas idénticas a mano, por cada profesional, es el gesto que
  más se repite en la pantalla. **La multiplicación va en la UI**: el modelo de
  datos no tiene por qué cargar con una comodidad de la pantalla.
- **Las altas van secuenciales y no en `Promise.all`.** Si una falla —una
  duración que el backend no acepta— hay que cortar ahí; en paralelo se crearían
  las otras cuatro igual y el error diría una sola cosa con la agenda a medio
  cargar. Y se recarga la lista **también en el error**, para que los días que
  sí entraron se vean: si no, el usuario los vuelve a cargar y se duplican.
- **En demanda espontánea no se ofrece el campo de duración.** No hay turnos que
  durar; ofrecerlo igual haría creer que hace algo.
- **La jornada del profesional ya no se carga como ventana semanal.** El
  endpoint viejo (`/resources/{id}/availability`) sigue existiendo y sigue
  sumando —ADR-030 lo conserva a propósito—, pero la pantalla no lo ofrece: dos
  maneras de cargar lo mismo, una más pobre que la otra, es cómo se termina con
  la mitad de los profesionales configurados de un modo y la otra mitad del
  otro. `ventanas.tsx` queda sólo para el horario de atención de la sede.

### Consecuencias

- 16 tests nuevos (36 en la suite del frontend), **con su control al lado**: el
  atajo de "lunes a viernes" tiene el test de que no pisa un día ya cargado, y
  el de los cinco bloques tiene el de que deseleccionar días cambia cuántos se
  crean — sin ese, "mandar siempre los cinco hábiles" pasaría igual.
- **Dos cosas que este producto no tenía y aparecieron al escribir los tests:**
  - `src/test/setup.ts` no tenía el polyfill de **captura de puntero**. Sin él,
    abrir un `Select` de Radix desde un test tira `hasPointerCapture is not a
    function` y no despliega ninguna opción — que se lee como un defecto de la
    pantalla y no lo es. No se notaba porque ningún test de acá abría un
    `Select`. Gestiolibra ya lo tenía.
  - `waitFor`/`findBy*` corrían con el **default de 1 segundo**. Medido: en la
    corrida inmediatamente posterior a un `npm ci` —con el transform tardando
    9 s en vez de 2,6— se cayeron dos tests del calendario que en las tres
    corridas siguientes pasaron sin tocar una línea. Se sube a 5 s en vez de
    convivir con el flake: un rojo intermitente enseña a re-correr el CI hasta
    que salga verde, que es el hábito que vuelve inútil al CI. No hace más lenta
    ninguna corrida sana — `waitFor` corta apenas la condición se cumple.
- Cobertura del frontend: **55,29 % de líneas**, muy por encima del trinquete de
  22.
- **La fila de demanda espontánea sigue sin pantalla**: esta ronda cubre la
  parametrización (dónde, cuándo, quién, cuánto), no la operación diaria del
  llamador.

## ADR-033 — Honorarios: el valor de la consulta por profesional

**Fecha**: 2026-08-24
**Estado**: Aceptada

### Contexto

Pedido del humano (2026-08-22): *"agregar cobro de honorarios por médico,
permitiendo setear valor de la consulta por profesional"*.

`service_prices` modela **(prestación × sede)**: la misma consulta puede costar
distinto en dos consultorios. Lo que no puede decir es que la consulta con la
Dra. Vidal salga más cara que con el Dr. Molina **en la misma sede**, que es
justamente lo que distingue a un honorario de un precio de lista.

### Decisión

Una tabla `(prestación × profesional)` que **pisa** al precio de la sede cuando
existe.

**El orden no es arbitrario.** El precio por sede es el de lista —lo que sale
esa prestación en ese consultorio— y el del profesional es la excepción
explícita que alguien cargó para él; una excepción que no pisara al general no
serviría para nada. Y **sacar el honorario no deja la prestación sin precio**:
vuelve a cobrarse la de lista. Si dejara un hueco, el turno se completaría sin
facturar y el consultorio perdería la consulta sin que nada avise.

🔴 **Un solo resolvedor, y tiene que seguir siendo uno.** `precio_del_turno()`
es el único lugar donde se decide qué se cobra. Hoy tiene un único consumidor
—`complete_appointment`— y ahí está la trampa: es fácil que mañana la seña, un
presupuesto o el envío a facturar copien la línea `service_prices.get(...)` en
vez de llamar acá. Con dos lugares resolviendo lo mismo, el honorario aplica en
un camino y no en el otro, y la diferencia aparece como un descuadre de caja que
nadie sabe de dónde sale. Queda dicho en el código, en los dos lados.

**El honorario alcanza solo**: no es un descuento sobre un precio de lista que
tenga que existir. Un consultorio que cobra distinto por profesional y no maneja
precio de lista es un caso normal, y tiene su test.

**El endpoint cuelga del profesional** (`/resources/{id}/prices`) y no de la
prestación, porque es como se carga: se entra a la ficha de la persona y se le
ponen sus honorarios. La otra forma obligaría a recorrer las prestaciones una
por una para configurar a alguien.

### Consecuencias

- 9 tests nuevos de backend (381 en la suite) y 5 de frontend (41). **El que
  manda no mira la fila de la tabla**: completa un turno de verdad y verifica el
  **total de la factura emitida**.
- **Verificados por mutación**: ignorando el honorario propio se ponen en rojo
  cinco, y el control —*sin honorario se cobra el precio de la sede*— sigue
  verde.
- El control que distingue *"pisa el precio"* de *"cambió el precio"* va con las
  **dos filas cargadas y distintas**: el turno de la Dra. Vidal sale 2500 y el
  del Dr. Molina, que no tiene honorario propio, sigue en los 1000 de la sede.
  Con una sola fila, un bug que aplicara el honorario a todo el mundo pasaría
  igual.
- **La tabla nace vacía**: sin honorario propio se factura exactamente como
  hasta ahora, y hay un test que lo fija. La migración `0017` no le cambia la
  facturación a ninguna instancia existente.
- En la pantalla, la card de Honorarios lista **todas las prestaciones activas
  con el precio de la sede al lado**, no sólo las que tienen honorario propio: un
  honorario es una excepción, y mostrar sólo las excepciones deja invisible lo
  que se cobra en todo lo demás. Cuando no hay ninguno de los dos precios, lo
  dice — *"se completa sin facturar"* es un estado válido pero silencioso.
- Migración probada contra `postgres:16` real, ida y vuelta; el único por
  `(prestación, profesional)` verificado **en la base**.

## ADR-034 — La facturación sale de la vista de MedLibra

**Fecha**: 2026-08-24
**Estado**: Aceptada

### Contexto

Pedido del humano (2026-08-22): *"sacar la opción de facturación en el sidebar, y
sacar la opción de facturación dentro de configuración, permitir enviar a
facturar consultas con enlace a contalibra"*.

La facturación de este producto pasa a **Contalibra**, que es donde vive la
contabilidad del ecosistema. Este cambio hace la primera mitad —sacarla de la
vista— y deja la segunda para su propio trabajo, que además toca otro repo con
clientes reales.

### Decisión

**Se saca de la vista, no del producto.** Al preguntarlo, el humano eligió sacar
la pantalla y **dejar el motor**: el turno completado sigue emitiendo su factura
hasta que Contalibra la reciba, para que ninguna instancia quede sin poder
facturar en el medio.

Sale entonces:

- El ítem **Facturación** del sidebar (`components/Layout.tsx`).
- La sección **ARCA** de Configuración (`pages/Configuracion.tsx`).
- 🔴 **Y la ruta `/facturacion` del router.** Sacar sólo el ítem del sidebar
  habría dejado la pantalla viva y accesible escribiendo la URL. Una pantalla
  que el producto ya no ofrece pero que sigue funcionando es peor que cualquiera
  de las dos cosas por separado: nadie la mantiene y sigue escribiendo en la
  base.

**No se borra `pages/Facturacion.tsx`.** Es la única forma de configurar ARCA, y
el backend **sigue facturando**: si a un cliente se le vencen los certificados
antes de que Contalibra esté recibiendo, borrar el componente sacaría el único
camino de recuperación mientras el motor está vivo. Queda sin referenciar y con
fecha de vencimiento: se va con el cambio que conecte Contalibra.

### Consecuencias

- ⚠️ **Una instancia NUEVA ya no puede configurar ARCA desde la interfaz.** Las
  que ya tienen su configuración cargada siguen facturando igual; las nuevas
  dependen de que la integración con Contalibra esté lista. Es una consecuencia
  buscada —el destino es Contalibra— pero conviene tenerla escrita, porque es
  exactamente lo que vuelve urgente al cambio siguiente.
- Los endpoints `/config/arca` y `/billing` **no se tocan**: siguen ahí y siguen
  siendo `admin_only`. Lo que se saca es la interfaz.
- 1 test nuevo (37 en la suite del frontend). 🔴 **La ruta se mide del lado del
  router de React y no pidiéndosela al backend**: el catch-all del SPA devuelve
  `index.html` con 200 para cualquier ruta, así que un `GET /facturacion` daría
  200 aunque la ruta no exista. Verificado por control: volviendo a poner la
  ruta, el test se pone rojo.
- El guard de títulos (`titulos-con-icono.test.ts`) exigía **7 ítems de menú** y
  se puso en rojo con 6 — no encontró nada raro, encontró un ítem menos. Era un
  número calcado de la foto del día que se escribió, y con él **toda baja
  legítima es un rojo que no dice nada**. Baja a 5, que sigue siendo un piso de
  "midió algo" con margen para otra baja.

## ADR-035 — Las consultas se mandan a Contalibra, y acá se deja de facturar

**Fecha**: 2026-08-24
**Estado**: Aceptada

### Contexto

ADR-034 sacó la facturación **de la vista** y dejó el motor vivo a propósito,
para que ninguna instancia quedara sin poder facturar en el medio. Esta es la
otra mitad del pedido: *"permitir enviar a facturar consultas con enlace a
contalibra"*.

Del otro lado, Contalibra sumó el endpoint que las recibe (su
`POST /api/integraciones/consultas`, PR #142). El hallazgo que definió ese
diseño: **el token de servicio no es un usuario**, y en Contalibra el
`usuario_id` de una venta es lo que la engancha al turno de caja — una venta
creada con el token quedaría fuera de todo turno y el cierre no la vería.

### Decisión

🔴 **O factura Contalibra, o factura MedLibra. Nunca las dos.**

`complete_appointment` emite la factura con LibraCore/ARCA desde ADR-016. Si
además mandara la consulta a Contalibra —que también factura— saldrían **dos
comprobantes por una consulta**, y un CAE emitido no se borra: se anula con una
nota de crédito. Por eso el destino es un **interruptor**, no un agregado:

- Con `CONTALIBRA_URL` configurada → se manda y **este producto no emite**.
- Vacía → se factura acá, exactamente como hasta ahora.

**El token va en una variable propia** (`CONTALIBRA_SERVICE_TOKEN`) y no en la
`LIBRA_SERVICE_TOKEN` que este producto ya lee para su propio guard de entrada:
son dos permisos distintos —el que nos dejan usar y el que nosotros aceptamos— y
compartir el nombre haría que rotar uno rote el otro sin que nadie lo pida.

**Lo que viaja pasa por el mismo resolvedor que la factura local**
(`precio_del_turno`, ADR-033). Si el envío leyera el precio por su cuenta, el
honorario del profesional aplicaría facturando acá y no mandando allá.

### Un fallo del otro lado no rompe el turno, pero tampoco es invisible

Son las dos mitades, y las dos importan:

- **No rompe el completar.** La atención ya ocurrió; negarse a completarla
  porque la contabilidad de otro producto no contesta sería castigar al
  consultorio por una falla que no es suya. Y `COMPLETED` no admite otra
  transición: un turno que no se puede completar queda trabado para siempre.
- **No es invisible.** Una consulta que no se facturó y de la que nadie se
  entera es plata que se pierde en silencio. Cada envío deja su fila en
  `envios_a_contalibra` con su estado y su error; `GET /facturacion-externa` los
  lista y `POST /facturacion-externa/{id}/reintentar` los reintenta.

El reintento **recalcula todo desde el turno** en vez de guardar el cuerpo del
envío fallido: si entre el intento y el reintento cambió el honorario, lo que
tiene que viajar es el precio de hoy. Y es seguro repetirlo — Contalibra es
idempotente por `(sistema, referencia)`, y la referencia es el id del turno.

### Consecuencias

- 14 tests nuevos (412 en la suite). **Verificados por mutación**: forzando a
  que nunca mande, se ponen en rojo seis.
- 🔴 **Tres de esos tests miden el pedido HTTP de verdad**, no el doble. Todo lo
  demás reemplaza `enviar_consulta`, así que el nombre de los campos, la URL y
  el header quedarían sin cubrir — y son exactamente lo que hace que el otro
  lado conteste 401 o 422 sin que nada de acá se ponga rojo. **Escribiendo eso
  ya apareció uno**: el header se había puesto como `X-Service-Token` y el que
  libraauth valida es `x-internal-auth`. Ahora la constante se importa del
  motor en vez de escribirse.
- **La respuesta de completar suma `contalibra`**, con el estado del envío. Sin
  eso, el mostrador no tendría forma de saber que la consulta no llegó.
- `GET /facturacion-externa` devuelve **el destino junto a la lista**: una lista
  vacía significa cosas opuestas —"todo salió bien" contra "esto ni siquiera
  está prendido"— y sin ese dato la pantalla no las puede distinguir.
- Migración `0018`, probada contra `postgres:16` real, ida y vuelta. La tabla
  nace vacía y sólo se escribe si la instancia tiene `CONTALIBRA_URL`.
- **Todavía sin pantalla.** `GET /facturacion-externa` se opera por API, como el
  resto de lo que se construyó esta semana.

## ADR-036 — Se va el motor de facturación local: Contalibra es el único camino

**Fecha**: 2026-08-24
**Estado**: Aceptada
**Reemplaza el interruptor de**: ADR-035

### Contexto

Pedido del humano: *"borrar Facturacion.tsx y limpiar /config/arca"*.

ADR-034 sacó la facturación de la vista y ADR-035 la mandó a Contalibra, pero
los dos dejaron el motor local vivo: `Facturacion.tsx` seguía en el repo aunque
nada la ruteara, `/config/arca` seguía respondiendo, y `complete_appointment`
tenía un `else` que emitía el comprobante acá cuando `CONTALIBRA_URL` estaba
vacía.

### Decisión

**Se borra el motor, no sólo la pantalla.** Se van `app/services/billing.py`,
`app/routers/billing.py`, `frontend/src/pages/Facturacion.tsx` y
`tests/test_billing.py`. `/config/arca` deja de existir: **404, no 403**.

De `billing.py` sobrevive una sola función, `configure()`, en un archivo con el
nombre que le corresponde: `app/services/libracore_setup.py`. No factura nada —
configura la base de LibraCore donde viven **los usuarios**, crea el schema y la
caja por defecto. Es load-bearing y no tiene nada que ver con facturar; el
nombre `billing` era el que mentía.

### 🔴 Lo que reemplaza al `else`: `sin_destino`, no silencio

Borrar el motor deja una pregunta que no se puede contestar borrando: **qué pasa
cuando una instancia no tiene `CONTALIBRA_URL`**. La respuesta obvia —completar
el turno y no hacer nada— es la peor: la consulta se atendió, se cobró, y no hay
ningún rastro de que faltó facturarla.

Así que el turno se completa igual —la atención ocurrió— y el envío se registra
con estado **`sin_destino`**, que entra en `envios_a_contalibra` como cualquier
otro y **aparece en `GET /facturacion-externa`** junto a los que fallaron.
Configurar el destino y reintentar las factura; no hacerlo las deja a la vista.
Es la misma regla de ADR-035 llevada a su último caso: *una consulta sin
facturar de la que nadie se entera es plata que se pierde en silencio*.

Con el módulo `facturacion` **apagado** el envío es `None`, y ahí sí no se
registra nada: no es que falte a dónde mandarlo, es que **esta instancia no
cobra**. Registrarlo llenaría la pantalla de consultas que nunca hay que
facturar.

### La alícuota se queda, y ahora viaja

`app/services/iva_rates.py` **no se va con el motor**. Qué alícuota le
corresponde a una prestación es configuración *de la prestación*, y las
prestaciones viven acá; en salud la mayoría están **exentas**. Lo que cambia es
a dónde va el dato: en vez de alimentar el `_split_iva` propio, viaja con la
consulta en `iva_rate` y Contalibra la guarda con la venta
([contalibra PR de `ventas_origen_externo.iva_rate`]).

Sin eso, del otro lado no hay forma de saber que una consulta era exenta: se
declararía al **21% en silencio**, que es un error fiscal que nadie ve hasta la
inspección.

### Consecuencias

- **Una instancia sin `CONTALIBRA_URL` ya no puede emitir comprobantes.** Es el
  punto de la decisión, no un efecto colateral: este producto no factura. Pero
  no pierde el dato — queda en `/facturacion-externa`.
- Los tests que medían el motor local se fueron con él (`test_billing.py`), y
  los que medían el XML de ARCA salieron de `test_iva_rates.py`: ese contrato
  ahora es de Contalibra. Lo que se agregó en su lugar:
  - `test_no_queda_ningun_camino_de_facturacion_local`, que mide **el schema de
    OpenAPI** —no el árbol de routers, que no expone `path`— con control
    positivo (`len(rutas) > 20`), para que un `paths` vacío no lo pase.
  - `test_sin_contalibra_configurada_la_consulta_queda_SIN_FACTURAR`, el caso
    que reemplaza al `else`.
  - `test_la_alicuota_de_la_prestacion_viaja_con_la_consulta` y su control
    `test_sin_alicuota_propia_viaja_la_de_la_instancia`.
  - 🔴 Esos dos **interceptan `enviar_consulta`**, así que miden que
    `complete_appointment` resuelva la alícuota y la pase — no que llegue al
    pedido. Con ese doble puesto, escribir mal la clave del cuerpo (o mandar
    `None` siempre) los deja en verde y la consulta exenta se declara al 21%
    del otro lado. **Lo encontró la mutación, no la lectura**: forzando
    `"iva_rate": None` en el cuerpo, los 17 tests pasaban. Lo cubre ahora
    `test_el_pedido_lleva_el_vocabulario_de_contalibra`, que mide el pedido
    HTTP real, más su control
    `test_sin_alicuota_el_cuerpo_la_manda_nula_y_no_la_omite` — porque `None`
    (usá tu default, 21%) y `0.0` (exento) no son lo mismo, y confundirlos es
    IVA no declarado.
- `test_ya_no_hay_configuracion_de_arca_que_gatear` reemplaza al test que
  verificaba el 403 de `/config/arca` sin módulo. El módulo `facturacion` sigue
  existiendo y ahora gatea **el envío**, no la emisión.
- La respuesta de completar deja de traer `factura`: es `{id, status,
  contalibra}`. El frontend perdió `ArcaConfig`, `Factura` y
  `TIPO_COMPROBANTE_LABELS`.
- El diálogo de "Factura emitida" de la agenda se reemplaza por uno que aparece
  **sólo cuando la consulta NO se facturó**. El caso bueno no necesita
  interrumpir a nadie; el malo sí.
- **Sin migración.** No se borra ninguna tabla: las facturas que una instancia
  ya emitió siguen donde están. Se va el código que emite nuevas, no el
  histórico.

### Dos cosas que aparecieron al vaciar el archivo

**1. `tests/test_billing.py` no medía sólo facturación.** Cinco de sus once
tests cubrían la validación del medio de pago, la seña que descuenta del saldo y
que un turno no se pueda completar dos veces — todo eso sigue vivo en
`complete_appointment`. Borrar el archivo entero los habría dejado sin una sola
aserción encima. Se rescataron en `tests/test_completar_turno.py`, que es donde
tenían que estar desde el principio. Los que sí se fueron son los del
comprobante (tipo A contra tipo B, el CAE): ese contrato ahora es de Contalibra.

**2. La guarda de `configure()` no cubría la URL que este producto usa.** El
`billing.configure()` que se renombró traía escrito a mano
`startswith(("postgres://", "postgresql://"))` para no crear una carpeta cuando
el destino es PostgreSQL — el defecto de VentaLibra del 2026-08-10, donde
`os.makedirs()` terminaba creando **un directorio con la contraseña en el
nombre**. Pero `"postgresql+psycopg://".startswith("postgresql://")` es `False`,
y ésa es exactamente la forma que este arranque usa: `app/main.py` la nombra
unas líneas más abajo, al armar el engine de libraauth. **La guarda existía y el
defecto pasaba igual.** Ahora el criterio sale de
`libracore.db.core.es_url_postgres`, que existe para ser el mismo criterio en un
solo lugar, con `tests/test_libracore_setup.py` encima — verificado por mutación:
con la lista a mano de vuelta, el caso `postgresql+psycopg://` se pone en rojo.

### Lo que quedaba abierto

> ✅ **Cerrado el mismo día, en ADR-037.** El test que asertaba el defecto se
> puso en rojo, que era exactamente para lo que estaba escrito. Lo de abajo es
> el planteo original.

⚠️ **La seña no se reparte por medio de pago.** Un turno señado manda a
Contalibra **una sola venta por el precio entero, con el medio de pago del
saldo**: con 400 de seña por MercadoPago y 600 en efectivo, allá entran 1000 en
efectivo. La venta cierra por el total correcto, pero la caja queda mal
repartida entre medios. El motor local sí repartía —seña y saldo como dos
movimientos— y eso se perdió al mudarse. Arreglarlo necesita que
`POST /api/integraciones/consultas` acepte una lista de pagos, como ya hace
`POST /api/ventas`; o sea, un PR en Contalibra primero. Queda **asertado tal cual
es hoy** en `test_con_sena_parcial_viaja_el_precio_ENTERO_con_el_medio_del_saldo`,
para que el día que se toque se ponga rojo y obligue a decidir en vez de cambiar
en silencio.

## ADR-037 — La seña y el saldo viajan como dos pagos, cada uno con su medio

**Fecha**: 2026-08-24
**Estado**: Aceptada
**Cierra el pendiente de**: ADR-036

### Contexto

ADR-036 dejó esto anotado como *"lo que queda abierto"*, con un test que
asertaba el defecto tal cual era para que el día que se tocara se pusiera rojo.
Se tocó, y se puso rojo.

Un turno señado se cobra en dos momentos: la seña al reservar y el saldo al
atender, y pueden ser medios distintos. Lo que viajaba a [[contalibra]] era **el
precio entero con un solo medio, el del saldo**.

Con 400 de seña por MercadoPago y 600 en efectivo, allá entraban **1000 en
efectivo**. La venta cerraba por el total correcto —la plata bien contada— y el
reparto de la caja quedaba mal: el cierre no cuadra contra el arqueo y la
diferencia no tiene de dónde salir. El motor de facturación local que se borró
sí repartía, con un movimiento de caja por medio; eso se perdió al mudarse.

### Decisión

`enviar_consulta` manda **`pagos`, una lista**, y del otro lado
`POST /api/integraciones/consultas` la acepta (contalibra#146).

`contalibra.pagos_del_turno()` la arma, y **vive en el servicio y no en un
router** porque la usan los dos caminos: completar el turno y reintentar el
envío. Escrita en uno solo, el otro seguiría mandando un pago único y el defecto
quedaría vivo por la mitad — hay un test para cada camino.

Los montos **cierran contra el importe por construcción**: el saldo es
`importe - seña`, no un número aparte. Contalibra igual lo verifica y rebota con
422 si no suman, porque una venta que se marca cobrada tiene que estar cobrada
entera.

Cuando la seña cubre todo el precio el saldo es cero y **no viaja**: un pago de 0
crearía un movimiento de caja vacío allá, y además Contalibra lo rechaza
(`monto: float = Field(gt=0)`), o sea que tumbaría el envío entero.

### 🔴 El medio del saldo se guarda, porque no se puede recalcular

El reintento **recalcula todo desde el turno** —si cambió el honorario, viaja el
precio de hoy—, pero con qué se cobró no es algo que se recalcule: pasó, y ya. La
seña queda en `deposits` con su medio; el del saldo llega en el pedido de
completar y no se guardaba en ningún lado.

Hasta acá el reintento asumía `"efectivo"`, y eso **reintroducía en el reintento
el mismo defecto que esta decisión arregla**. Ahora va en
`envios_a_contalibra.medio_del_saldo` (migración `0019`), y se guarda **también
cuando el envío falla y cuando no hay destino** — que es justamente cuando más
falta hace: una consulta puede quedar meses esperando a que alguien configure
`CONTALIBRA_URL`.

`registrar(medio_del_saldo=None)` **conserva el que ya estaba** en vez de pisarlo
con vacío: el reintento no lo sabe, y borrarlo ahí dejaría al siguiente reintento
sin el dato que este campo existe para guardar.

### El vocabulario de medios de pago

Arreglando esto apareció que **`tarjeta`, uno de los cuatro medios que ofrecía
`Agenda.tsx`, no existía en el vocabulario de la familia**. Llegaba igual a
Contalibra, creaba su movimiento de caja y aparecía en el cierre como un bucket
suelto con el nombre crudo — la plata bien contada y el reparto mal, por segunda
vez y por otra razón.

Peor: era la misma copia byte a byte que tiene Gestiolibra, así que dos productos
inventaron el mismo medio por separado. Tirando de ahí, la lista estaba declarada
**28 veces en 11 repos** y ya divergía en seis formas
(`wiki/concepts/medios-de-pago-familia-libra.md`).

- La lista canónica subió a `libracore.medios_pago` (libracore#123, v1.50.0), con
  la **tarjeta partida en débito y crédito** — que es como la declara ARCA.
- Este producto la sirve en `GET /medios-pago`, **sin gatear por admin**: la
  consume el selector del mostrador al completar un turno, y ahí no hay un admin.
  Es una lista de constantes del motor; no expone nada de la instancia.
- `Agenda.tsx` la pide en vez de declararla.
- La cuenta corriente **no se ofrece**: no es un medio de cobro, es la marca de
  que la operación se hizo a crédito.

### Consecuencias

- Migración `0020`, probada ida y vuelta contra `postgres:16` real: el
  `downgrade` saca la columna y **deja las filas**, y el `upgrade` de vuelta las
  encuentra con el campo vacío. Sin backfill posible — el dato nunca existió.
- 🔴 **La migración nació como `0019` y tuvo que correrse a `0020`.** Otra
  sesión mergeó `0019_sin_users` en `develop` mientras esta rama estaba abierta,
  y las dos colgaban de `0018`: Alembic quedaba con **dos cabezas** y
  `upgrade head` falla con *"Multiple head revisions are present"*. **La suite
  local no lo vio** —este worktree tenía una sola de las dos— sino el CI, que
  corre sobre el *merge* con `develop`.
- 🔴 **Y tuvo que hacerse defensiva.** El test que la sesión paralela escribió
  ejercita una instancia **estampada en `0018` sin haber ejecutado `0018`**, que
  es lo que se le hace a las instancias vivas. Ahí `envios_a_contalibra` no
  existe y un `add_column` pelado revienta — y desde LibraCore v1.48.0 **una
  migración fallida aborta el deploy**. Ahora chequea con `inspect().has_table`,
  igual que `0019_sin_users` usa `DROP TABLE IF EXISTS`.
- De paso, ese test comparaba la revisión aplicada contra **su propia
  revisión** escrita a mano, así que se ponía en rojo con cualquier migración
  nueva. Ahora pregunta la cabeza real al `ScriptDirectory`, y de paso afirma
  que hay **una sola** — el trinquete que habría atajado lo de arriba.
- 🔴 **Dos tests medían lo que creían y no lo que pasaba**, y los encontró la
  mutación:
  - El del cuerpo HTTP **nunca serializaba nada**: el doble reemplaza
    `httpx.AsyncClient.post`, así que un `Decimal` en `monto` quedaba capturado
    tal cual — y `Decimal("500") == 500.0` es `True`. Los montos vienen de
    `deposits`, que los guarda como `Decimal`: **todos los envíos de un turno
    señado fallaban** con *"Object of type Decimal is not JSON serializable"* y
    ningún test lo veía. Ahora el test hace `json.dumps(cuerpo)`.
  - El de la agenda no abría el `Select` de Radix, que no rendea sus opciones
    hasta que se clickea el trigger: un `queryByRole('option')` pasaba por no
    encontrar nada, no por el filtro.
- El `EnvioOut` suma `medio_del_saldo`: quien dispara un reintento tiene derecho
  a ver con qué se va a mandar antes de mandarlo.