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
