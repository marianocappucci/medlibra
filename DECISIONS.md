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
**Estado**: Aceptada — **en parte reemplazada por ADR-042** (2026-10-17)

> ⚠️ **Dos afirmaciones de este ADR dejaron de valer.** «Un consultorio no es un
> `Resource`» y «en qué sala ocurre un turno va en `appointment_rooms`» se
> reemplazaron por ADR-042: la sala es un `Resource` y un recurso secundario del
> turno, y `appointment_rooms` se migró y se borró. El resto (bloques de agenda,
> duración, vigencia, modalidad) sigue como está escrito.

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

## ADR-038 — La fila de demanda espontánea tiene su pantalla, y el mostrador la lee por su propio router

**Fecha**: 2026-09-11
**Estado**: Aceptada
**Cierra el pendiente de**: ADR-031 (*"Todavía no tiene pantalla"*)

### Contexto

ADR-031 dejó la fila por orden de llegada entera en el backend —registrar,
listar, llamar, completar, cancelar— y **ninguna forma de usarla desde la
pantalla**. La parametrización de ADR-032 sumó el alta de bloques con modalidad
`espontanea`, así que el producto dejaba **configurar** una agenda por demanda
espontánea y no **operarla**: la secretaria podía armar el bloque del lunes y el
lunes no tenía dónde anotar a nadie.

### Decisión

Una pantalla propia, `/demanda-espontanea`, en el menú junto a la Agenda y **sin
`adminOnly`**: la opera el mostrador, igual que los turnos. Se elige el día
(`?dia=`, ISO) y el bloque (`?bloque=`), se ve la fila en orden de llegada, se
anota una llegada y cada llegada avanza con los botones de su estado.

🔴 **Dos lecturas nuevas en el router de la fila, y no `staff` sobre los routers
de configuración.** La pantalla necesita saber qué bloques de demanda
espontánea rigen ese día y qué prestaciones se pueden anotar, y
`/agenda-blocks` y `/services` son `admin_only`: el mostrador recibe 403 en los
dos. Abrirlos a `staff` le habría dado también el alta, la edición y el borrado
de la agenda y del catálogo. En cambio:

- `GET /walkins/bloques?day=` — los bloques `espontanea` que rigen ese día, de
  todos los profesionales, con el nombre del profesional y del consultorio ya
  resueltos y **el huso de la sede**.
- `GET /walkins/prestaciones` — sólo las activas, sólo `id` y `name`.

Las dos quedan bajo `staff_or_admin` porque el router ya lo estaba.

- **La lista usa el mismo criterio que el alta** (`_bloque_para_la_fila`): día
  de la semana, vigencia y modalidad. Un bloque ofrecido que el alta rechazara
  sería una fila en la que anotar da siempre 409. Por eso tampoco filtra por
  profesional activo: el alta no lo mira.
- **La hora de llegada es la de la sede**, no la del navegador ni la de
  Argentina (ADR-028): `created_at` viaja en UTC y se pasa por `enHoraDePared`
  con el huso del bloque antes del helper de fechas.
- **"Sigue" es el primero que espera, no el N° 1.** El número es histórico y no
  se renumera (ADR-031), así que quién sigue se calcula por estado.
- **Los botones son la tabla `TRANSICIONES` vista desde la pantalla**: esperando
  → Llamar o Sacar de la fila; en atención → Atendido o Sacar de la fila;
  atendido y fuera de la fila, ninguno. Un botón que el backend rechaza siempre
  enseña a ignorar los errores.
- **La llegada se anota en el día de la pantalla**, no en el de hoy: el backend
  lo pide explícito justamente para no adivinarlo con su reloj.
- La fila se vuelve a pedir cada 30 s: la operan dos puntas a la vez —el
  mostrador anota, el consultorio llama— y ninguna ve a la otra si la pantalla
  no se refresca sola.

### Lo que queda abierto

- **La espera se ve sólo para quien espera.** No se guarda cuándo lo llamaron
  (`walkins` tiene `created_at` y nada más), así que "cuánto esperó" el ya
  atendido no se puede decir. Sumarlo es una columna y una migración.
  *(Cerrado por el ADR-048: `called_at`.)*
- **No hay estado "ausente"**: la máquina de ADR-031 no tiene `no_show` a
  propósito. "Se fue" es `cancelled` y conserva su número.
- **La fila sólo anota pacientes existentes** (`client_id` es FK). El alta de
  uno nuevo se hace en Pacientes; la pantalla lo dice y enlaza.
  *(Cerrado por el ADR-041: el alta se hace ahí mismo, con `SelectCliente`; y sin
  conexión, por el ADR-045, con número provisorio.)*

### Consecuencias

- 7 tests nuevos de backend y 13 de frontend, verificados por mutación.

## ADR-039 — La Agenda lee su catálogo por el router de la agenda, no por los de configuración

**Fecha**: 2026-09-11
**Estado**: Aceptada

### Contexto

`pages/Agenda.tsx` cargaba el catálogo con un solo `Promise.all` sobre
`/resources`, `/branches`, `/services`, `/patients` y `/medios-pago`. Los tres
primeros son `admin_only`. Para el mostrador —staff, que es quien atiende el
teléfono y da los turnos— el primer 403 rechazaba el `Promise.all` entero: la
pantalla mostraba el error arriba, el cartel *"No hay profesionales activos.
Cargá uno en Configuración."* y "Nuevo turno" apagado, en una instancia que sí
tenía profesionales. Verificado el 2026-09-11 contra `origin/develop`
(`dc5019c`): staff recibe 403 en los tres, 200 en `/patients`, `/medios-pago` y
`/resources/{id}/agenda`.

Se había visto de pasada al cerrar ADR-038, que resolvió el mismo problema para
la fila de demanda espontánea.

### Decisión

Mismo criterio que ADR-038: **una lectura recortada en un router que ya es
`staff_or_admin`**, y no `staff` sobre los routers de configuración —que le
darían también el alta, la edición y el borrado de profesionales, sedes y
prestaciones—.

- `GET /agenda/catalogo`, en `app/routers/agenda.py`, devuelve
  `{profesionales, sedes, prestaciones}` en **una** llamada.
- **La sede viaja sin teléfono ni dirección**: la Agenda sólo usa el nombre y el
  huso (ADR-028).
- **Trae también los dados de baja, con su `active`.** La pantalla ya filtraba
  los activos para ofrecer y para dibujar carriles; filtrar en el backend haría
  que un turno viejo con una prestación dada de baja mostrara el id en vez del
  nombre.
- La Agenda deja de pedir `/resources`, `/branches` y `/services`.

### Consecuencias

- Los routers de configuración quedan como estaban: el test
  `test_el_catalogo_sigue_cerrado_para_staff` recorre `GET`/`POST`/`PUT`/`DELETE`
  de los tres y exige 403 para staff.
- En el test de la Agenda, el stub contesta **403 siempre** a los routers de
  configuración, como el backend real a staff: una pantalla que vuelva a
  pedirlos se pone roja en todo el archivo, no sólo en el test que lo mira.
- Tests nuevos verificados por mutación.

## ADR-040 — `create_app()` es el arranque de varios procesos: el candado va en la base de LibraCore y el captcha usa `UsadosEnBase` (2026-10-13)

- Estado: aceptada
- Contexto: el motor quedó listo para `uvicorn --workers N` (ADR-044 de libracore, ADR-023 de libraauth) y MedLibra sigue con **un** proceso (`WEB_CONCURRENCY` por defecto 1; decisión del dueño). Este producto no tiene un hook `startup`: `create_app()` ES el arranque y lo corre cada worker al importar `app.asgi`. Sus «si no existe, crear» (`ModuleRepository.ensure_seeded()`, `ensure_default_admin`, `ensure_demo_user`, `migrar_secretos`, `AuditoriaBase.metadata.create_all`) se contestarían «no existe» en los dos workers antes de que ninguno cree, y el anti-replay del captcha era un `dict` del proceso.
- Decisión:
  - Esos pasos van dentro de `una_vez_al_arrancar("medlibra-arranque", destino=libracore_db_path)`. Se pasa `destino` explícito porque el candado es de **una base** y este producto tiene dos (dominio y LibraCore): sirve cualquiera mientras sea la misma para todos los workers, y la de LibraCore es la que `create_app()` ya conoce por nombre antes de sembrar. Cada paso sigue preguntando adentro (idempotente); el candado sólo los ordena.
  - `app.state.captcha = Captcha(app.state.session_auth.secret_key, usados=UsadosEnBase(auth_sessions))` en `create_app()`: es lo que el router armaría solo con la misma clave, pero con `usados=`. No se pasa `captcha_usados=` al `build_json_api_auth_router` de `app/routers/auth.py` porque ese módulo se construye al importar, antes de que exista el session factory de la instancia.
  - `pool_pre_ping=True` en el engine de auth y en el del dominio (`libragenda.configure(url, pool_pre_ping=True)` lo pasa a `create_engine`).
- Consecuencias: con un solo worker no cambia nada observable. **Subir `WEB_CONCURRENCY` es una decisión aparte**; antes hay que releer `docs/varios-procesos.md` de libracore (reiniciar el contenedor tras un restore en caliente, el `config.json` sigue siendo *last write wins*). `tests/test_varios_procesos.py` levanta `uvicorn --workers 2` de verdad y fija que quede un admin y cada módulo una vez.

## ADR-041 — El paciente se da de alta donde se lo elige, y su número lo genera el backend (2026-10-16)

- Estado: aceptada
- Contexto: el humano pidió que **todo** campo de la suite donde se elige un cliente —en MedLibra, el paciente— ofrezca darlo de alta ahí mismo (ADR-071 de libra-ui, `SelectCliente`). En «Nuevo turno» y «Anotar llegada» un paciente no cargado obligaba a salir, ir a Pacientes, crearlo y volver; en la segunda, a lo sumo había un link. Además `POST /patients` exigía un `id` que tipeaba el usuario, y un alta de mostrador, con la persona esperando, no puede pedir que se invente un código.
- Decisión:
  - **Las dos pantallas usan `SelectCliente`** con `entidad="paciente"`, `etiquetaDocumento="DNI"` y los campos `documento`, `telefono`, `email`. El `crear` (`altaDePaciente`, `src/api.ts`) manda `POST /patients` con `{name, dni, phone, email}` **sin `id`** y devuelve la opción a elegir. El resto (fecha de nacimiento, CUIT, condición frente al IVA) se completa después en la ficha. Una guarda de fuentes (`campos-de-paciente.test.ts`, con las palabras `client`, `paciente`, `patient`) impide que nazca un campo de paciente sin alta; un filtro que no crea nada se marca con `cliente-sin-alta: <motivo>`.
  - **`id` es opcional en `POST /patients`.** Sin `id` se genera `p-NNN` (tres cifras con ceros, y sigue sin truncar pasado `p-999`), igual que los pacientes de la demo. Con `id` se respeta (compatibilidad con lo cargado a mano y con la semilla). Un `id: ""` explícito no cuenta como ausente: es un 422, como hoy.
  - **El número sale de un contador, `patient_sequences`**, y no de `max(id) + 1`. Con el máximo, borrar al último paciente devuelve su número y el alta siguiente hereda un id que puede seguir en un turno, un mensaje o un comprobante viejo. El contador avanza con `UPDATE ... SET last = last + 1 RETURNING last`, una sola sentencia que toma el candado de la fila: dos altas simultáneas esperan una a la otra y reciben números distintos. Si el `p-NNN` ya está ocupado (alguien lo escribió a mano), el alta toma el siguiente en vez de fallar (hasta 50 intentos).
  - **Migración `0021_patient_sequences`**: crea la tabla vacía. La fila de la serie se crea en el primer alta sin id, partiendo del `p-NNN` más alto que ya exista, así no hace falta un backfill en SQL que repita la expresión regular del código. Es idempotente en los dos mundos (instancia armada por `create_all` o por migraciones).
- Dónde vive la numeración: ni `libracore` ni `libragenda` generan el id del paciente. `libragenda` (`add_client`) recibe el `Client` con el id ya armado, que es una cadena libre; los clientes de `libracore.db.clients` son otra tabla, con ids enteros, que este producto no usa para los pacientes. El formato `p-NNN` y el contador son de MedLibra (el id del paciente es su identidad clínica), y por eso `PatientRepository` los pone en `app/services/patients.py`. Si otro producto de la familia que usa `libragenda` quiere lo mismo para sus clientes, hay que subir el contador a `libragenda` y no copiarlo.
- Consecuencias: un alta que falla después de tomar el número (un 422 por un email inválido, por ejemplo) **deja un hueco** en la serie; es el costo de un contador que nunca devuelve números, y no es un defecto. Los números no son correlativos para una auditoría; si algún día lo tienen que ser, es otra decisión. Tests verificados por mutación: sin `id` opcional, seis tests del backend se ponen rojos; sin `SelectCliente` en la Agenda, la guarda se pone roja nombrando `pages/Agenda.tsx:454`; el test de Escape (panel abierto dentro de «Nuevo turno») cubre el arreglo del kit v0.158.1, que corta Escape antes que el `Dialog`.

## ADR-042 — El consultorio es un recurso secundario del turno, y el motor lo traba (2026-10-17)

- Estado: aceptada. Corrige a ADR-030 en lo que dice del consultorio.
- Contexto: **dos profesionales podían quedarse el mismo consultorio a la misma hora.** ADR-030 modelaba la sala como entidad propia (`consultorios` + `appointment_rooms`) porque «el motor asocia un turno a un solo recurso»; para entonces ADR-009 de LibraGenda (recurso secundario) ya existía. `AppointmentService` chequeaba la sala con `_consultorio_libre()` leyendo los turnos **antes** de llamar al motor, y recién después `reserve()` abría su transacción: dos pedidos simultáneos veían los dos la sala libre, cada uno trababa su propia fila de profesional —no se cruzaban— y entraban los dos. Medido con dos hilos sobre `AppointmentService.create` y sobre `reschedule` contra PostgreSQL (`tests/test_consultorio_concurrente.py`): **entraban los dos** en las dos operaciones; con el cambio, entra uno y el otro recibe `ConsultorioOcupado`. Los tests de `test_agenda_blocks.py`, que corren de a un pedido, nunca lo veían.
- Decisión: **la sala es un `Resource` de LibraGenda y va en `Appointment.secondary_resource_ids`** (ADR-009 y ADR-016 del motor, v0.13.0). El motor traba el profesional y la sala en la misma transacción (`SELECT … FOR UPDATE` en orden de id) y compara la intersección de recursos; el choque de sala es un `AppointmentConflict` como el del horario. Nada del chequeo vive ya en MedLibra.
  - **Cada consultorio son dos filas con el mismo id**: el `Resource` (lo que el motor traba) y la `ConsultorioRow` (la extensión del vertical), como `PatientRow` sobre `Client`. `ConsultorioRepository` escribe las dos en una transacción y las mantiene al editar y al borrar. Sin FK entre ellas: la invariante la sostienen el repositorio y la migración.
  - **El `Resource` de una sala no es un profesional.** `/resources` y `/agenda/catalogo` lo sacan con `ConsultorioRepository.ids()`; sin eso la Agenda dibujaría un carril «Consultorio 2» al lado de la Dra. Vidal. Un consultorio con el id de un profesional da 409 y no deja nada escrito.
  - **La sala sigue al bloque**: el turno ocupa el consultorio del bloque que cubre su horario, y al **reprogramar** cambia de sala si el horario nuevo cae en otro bloque (la sala nueva se valida y se traba con la hora nueva, en la misma transacción). Sin bloque que lo cubra, el turno no ocupa sala —como uno dado por la disponibilidad semanal—, **y al reprogramar a un horario así libera la que tenía** (antes la conservaba sin validarla).
  - **Qué mensaje se da**: `AppointmentConflict.resource_ids` dice qué chocó. Si fue **sólo** la sala, `ConsultorioOcupado` («el consultorio ya está ocupado… por otro profesional»); si el profesional estaba ocupado —solo o con la sala—, el «horario ya está ocupado» de siempre. Antes, un mismo profesional repetido sobre el mismo bloque decía «consultorio ocupado»: era cierto pero no era lo primero que había que mirar.
  - **El choque se compara en instantes**, como antes: `_TurnosEnHoraLocal` pasa ahora los turnos que **comparten algún recurso** con el candidato (no sólo los del profesional) y los lleva a la hora de pared de la sede que valida; dos sedes de husos distintos que piden la misma sala al mismo instante chocan (`test_la_sala_se_comparte_entre_sedes_de_husos_distintos`).
- Migración `0022_consultorio_recurso` (con datos, reversible): crea un `Resource` por consultorio, pasa cada fila de `appointment_rooms` a `appointment_resources` (después de otros secundarios que el turno ya tuviera), verifica los conteos **antes** de borrar la tabla y la borra. Corta, sin escribir nada, si el id de un consultorio ya es el de un profesional. El downgrade recrea `appointment_rooms`, devuelve a cada turno su sala y borra los `Resource` de las salas. Probada en `tests/test_migracion_consultorio_recurso.py`: subida, bajada y resubida con conteos, el solapamiento que ya existía conservado, una sala huérfana descartada.
- Consecuencias:
  - 🔴 Requiere **libragenda v0.13.0** (`AppointmentConflict.resource_ids` y `reschedule(secondary_resource_ids=…)`); con el pin en v0.12.0 reprogramar falla con `TypeError` y un choque de sala con `AttributeError`: ruidoso, no en silencio.
  - **Los turnos que ya estaban solapados en una sala siguen así**: la migración no mueve ni borra turnos ajenos. A partir de ahora no entran más.
  - Se retiran `AppointmentRoomRow`/`AppointmentRoomRepository`, `AppointmentService._consultorio_libre()` y el parámetro `rooms` del servicio; la auditoría etiqueta `AppointmentResourceRow` como «sala del turno».
  - No se carga todavía el `TimeBlock` de una sala (consultorio en mantenimiento) al motor: ADR-009 lo permite sin concepto nuevo, y falta sólo pasárselo a `_agenda_local`.

## ADR-043 — El código anda con una base o con dos: `agenda_clients`, `medlibra_modulos` y `Config` (2026-10-25)

- Estado: aceptada. Una migración de esquema (`0023_medlibra_modulos`, un `RENAME`) y una revisión vieja retocada (`0011`); ninguna de datos. **Este PR no une ninguna instancia**: `medlibra-dev` y `medlibra-demo` siguen con dos bases. Exige **libragenda `v0.14.0`**.
- Fecha: 2026-10-25
- Contexto: el humano decidió (2026-10-22) una sola base por producto; es el PR 4 del plan «GestioLibra, MedLibra y LibraDesk en la versión de escritorio» (wiki del ecosistema). MedLibra llevaba dos bases porque libracore y libragenda declaraban los dos una tabla `clients` con `id` de tipos distintos. `libracore-unir-bases` (ADR-078) corta con cualquier nombre de tabla repetido entre las dos bases, así que antes de unir hay que sacar los choques del lado del producto. Son tres: `clients` (de libragenda), `modulos` (del producto) y `alembic_version` (de libragenda).
- Qué ya existía (se miró antes): libragenda `v0.14.0` (ADR-017: `alembic_version_libragenda` con autorrenombre; ADR-018: `clients` pasa a `agenda_clients`), el molde de LibraClub (ADR-020: `Config` que resuelve una base o dos, `misma_base`, el respaldo con base extra sólo si es otra), el `libracore-unir-bases` del motor y su `_UNA_SOLA_BASE`, y la `modulos` de LibraDesk (`libradesk:app/database.py`). GestioLibra hace lo mismo en paralelo, en su repo.
- Medido el 2026-10-25, sobre PostgreSQL 16 con libracore `v1.192.1` y libragenda `v0.14.0`:
  - **`patients.id` es a la vez clave primaria y clave foránea a la tabla de clientes** (`patients_pkey` y `patients_id_fkey`, `\d patients`), y `walkins.client_id` es foránea. En una base «de antes» (se baja la `0010_agenda_clients` de libragenda para dejarla con `clients`) las dos claves apuntan a `clients`; al correr `libragenda-migrar upgrade` **se mueven solas** a `agenda_clients`, la clave primaria de `patients` sigue siéndolo y los datos están (`tests/test_agenda_clients.py`). Lo que sí hay que cambiar son los modelos y las revisiones `0002` y `0016` (una base nueva corre libragenda antes y ahí ya no hay `clients`).
  - **Las dos `modulos` guardan lo mismo con otra forma.**

    | | MedLibra | LibraCore |
    |---|---|---|
    | clave | `modulo VARCHAR(50)` | `id BIGSERIAL`; `modulo TEXT UNIQUE` |
    | `habilitado` | `BOOLEAN` | `INTEGER` |
    | `plan` | `VARCHAR(20)`, default `premium` | `TEXT`, default `estandar` |

    Compatibles por contenido: una fila es un nombre, un sí/no y la etiqueta del plan. Pasar de una a otra es un `CAST`, no una conversión (lo ata `tests/test_una_sola_base.py`). Es la forma que ya usa LibraDesk, que está en una sola base.
  - **Las cuatro cadenas conviven en una base nueva y única**: `alembic_version`, `_libragenda`, `_libraauth` y `_medlibra`. Corren igual con `libraauth-migrar` antes o después de `libracore-migrar` (se probaron los dos órdenes sobre bases vacías).
  - **`libracore-unir-bases verificar` sobre la cadena de dos bases con este cambio** (libracore `v1.192.1`): un solo impedimento, `cadena_desconocida` por `alembic_version_libraauth` en el core, que es de libracore#430 (ADR-082). **Renombrando a mano las dos tablas de vuelta** (`agenda_clients` → `clients`, `medlibra_modulos` → `modulos`) aparecen dos `choque_de_tablas` más: eso es lo que este PR saca.
- Decisión:
  - **Pin de libragenda a `v0.14.0`.** `PatientRow.id` y `WalkinRow.client_id` apuntan a `agenda_clients.id`; igual las revisiones `0002_patients` y `0016_walkins`, que sólo se ejecutan en bases nuevas (en una viva no cambian nada). Una guarda de fuentes (`tests/test_agenda_clients.py`) falla si vuelve a aparecer `"clients.id"` o un `FROM/JOIN/INTO/UPDATE clients` en `app/`, `migrations/` o `scripts/`. `scripts/reset_demo.sh` contaba `clients`: ahora `agenda_clients`.
  - **`modulos` pasa a `medlibra_modulos`** (`ModuleRow.__tablename__` y la migración `0023`, que además renombra la clave primaria: `modulos_pkey` es un nombre de toda la base y es el que necesita la tabla del motor).
    - La `0023` sólo actúa si `modulos` es la de MedLibra (no tiene `id`). Si es la del motor, o no existe, no hace nada. Si el arranque nuevo corrió antes de migrar (`create_all()` + `ensure_seeded()` dejaron una `medlibra_modulos` sembrada con todo habilitado), **pasa las filas de la vieja por encima del sembrado** y la borra, verificando antes que no falte ninguna. Baja devolviendo el nombre, salvo que ya haya una `modulos` (la del motor, en una base unida).
    - **La `0011` crea la tabla con el nombre nuevo.** En una base nueva y única `libracore-migrar` corre antes y deja su `modulos`; un `create_table("modulos")` moría con «already exists». Su `downgrade` borra la de MedLibra con cualquiera de los dos nombres y nunca la del motor.
  - **`app/database.py` (el contrato del backoffice) deja de delegar en `libracore.db.modulos`**: ese módulo lee y escribe una tabla llamada `modulos`, que en el dominio ya no existe. `get_modulos()` y `set_addon()` leen y escriben `medlibra_modulos` por la base del dominio (misma semántica que el motor: fila nueva con `plan="addon"`, sólo cambia `habilitado` si existe). Sirve igual adentro y afuera de la app, así que desaparece el `RuntimeError` de `_asegurar_core_configurado`. **`plans.aplicar_plan_en_db`**, que era un shim sobre `libracore.provisioning.apply_plan_modules` (tabla `modulos` escrita a mano), tiene ahora el mismo cuerpo contra `medlibra_modulos`.
  - **`app/config.py`: `Config` con una base o con dos**, como LibraClub (ADR-020). Sin `MEDLIBRA_LIBRACORE_DATABASE_URL` (ni el histórico `MEDLIBRA_LIBRACORE_DB_PATH`), o con la misma base que el dominio, `libracore_database_url` **es** la URL del dominio y `core_en_la_del_dominio` es verdadero; con otra, sigue como hasta hoy. `create_app()` la usa (en vez de leer `url_de_instancia(..., core=True)`), `exigir_schema_al_dia` dice `--base dominio` o `--base core` según corresponda, y `_instancia_a_respaldar` declara el core como segunda base sólo si es otra (si no, volcaría y restauraría la misma base dos veces). `app/asgi.py` sólo traspasa la variable del core si la instancia dice una. El modo SQLite sigue rechazado por `libracore_setup`; un dominio que no es PostgreSQL no se declara «una sola base». `scripts/reset_demo.sh` acepta las dos variables y no resetea dos veces la misma base.
  - **El orden de las cadenas en `scripts/panel_admin.py`, `scripts/nuevo_cliente.py` y el `command:` del compose no cambia**: libragenda, libraauth (`--base core`), libracore, la propia. Se probó también libracore antes de libraauth sobre una base única y anda, pero no hace falta moverlo y tiene tests que lo fijan; el cambio a `--base dominio` es del PR que une las instancias.
  - **El paso a `libracore.db.modulos` queda para después de unir**, no antes: hoy la `modulos` del motor vive en `medlibra_core`, y la del dominio no existe. Cuando las bases estén unidas (`modulos` del motor y `medlibra_modulos` en la misma base) el paso es una migración del producto con este SQL, que `tests/test_una_sola_base.py` corre tal cual y verifica que el motor lee lo mismo que `ModuleRepository` y puede seguir escribiendo:

    ```sql
    INSERT INTO modulos (modulo, habilitado, plan)
    SELECT modulo, CASE WHEN habilitado THEN 1 ELSE 0 END, plan FROM medlibra_modulos
    ON CONFLICT (modulo) DO UPDATE SET habilitado = EXCLUDED.habilitado, plan = EXCLUDED.plan
    ```

    y después `app.database` y `plans.aplicar_plan_en_db` vuelven a delegar en el motor, `ModuleRepository` lee la del motor y se borra `medlibra_modulos`.
- Consecuencias:
  - 🔴 **Orden de despliegue.** (1) La imagen con este cambio, **con la base ya migrada por la cadena del compose** (`libragenda-migrar upgrade` renombra `clients` y la tabla de versión; después las otras tres, la última con la `0023`). La cadena corre antes de `uvicorn`, así que un deploy normal no se ve; **arrancar la app nueva sobre una base sin migrar** deja a `crear_esquema()` crear una `agenda_clients` vacía y la migración de libragenda aborta. (2) Una imagen con el pin viejo sobre una base ya migrada no arranca (`clients` no existe): no volver atrás sin `downgrade` de la `0023` y de la `0010` de libragenda. (3) La unión de las bases va después, y exige además libracore con ADR-082 (PR 2 del plan).
  - 🔴 **Abierto para el motor: dar de alta una instancia nueva de MedLibra con dos bases.** `libracore.provisioning.nuevo_cliente` espera la tabla `modulos` en la base del dominio (`_esperar_tabla_en_sidecar`, sobre `db_urls[0]`) antes de aplicar el plan; con el renombre esa tabla no existe en el dominio y la espera se agota, así que el alta informaría que el plan no se aplicó. La aplicación del plan en sí ya está resuelta (`plans.aplicar_plan_en_db`). No hay altas de MedLibra planeadas; antes de hacer una, o el motor aprende el nombre de la tabla de módulos del producto, o la instancia nace con una sola base (PR 5 y 6 del plan).
  - `docker/postgres-init/10-base-de-libracore.sql` y la variable del core del compose se quedan hasta que se unan las instancias.
  - La suite sigue corriendo con dos bases (`tests/motor_de_test.py`, es la forma de `-dev` y `-demo`); la de una sola base la miden `tests/test_una_sola_base.py` y las otras dos nuevas con **bases propias descartables** (`tests/bases_temporales.py`) y la cadena corrida como el deploy.
  - Verificado por mutación (rojo sin el cambio): `ForeignKey("clients.id")` en `PatientRow` o en `0002`; `ModuleRow` con `modulos`; `0023` sin `upgrade`; `0011` creando `modulos`; `Config` que no cae al dominio; el respaldo con el core como extra siempre.


## ADR-044 — Una sola base: se va la variable del core, el alta nace con `medlibra` y nada más, y la suite también (2026-10-25)

- Estado: aceptada. Es el PR 6 del plan «GestioLibra, MedLibra y LibraDesk en la versión de escritorio» (wiki del ecosistema, `libraedge-gestiolibra-medlibra-libradesk-2026-10-24`) y cierra lo que el ADR-043 dejó anotado («el cambio a `--base dominio` es del PR que une las instancias», «o el motor aprende el nombre de la tabla de módulos del producto, o la instancia nace con una sola base»). Exige **libracore `v1.194.0`** (ADR-083: `_UNA_SOLA_BASE` suma a `medlibra`; `configure(tabla_modulos=)`), ya pineado. **`dev` ya está unida** (una sola base en el VPS, con un `docker-compose.override.yml` temporal que apunta `MEDLIBRA_LIBRACORE_DB_PATH` a la base del dominio); **la demo todavía tiene dos**. Por eso el código sigue andando con las dos formas (`app/config.py` no cambia) y este PR retira la forma de dos bases de **todo lo que este repo define**, no de lo que la demo ya tiene desplegado.
- Contexto: con `agenda_clients` y `medlibra_modulos` (ADR-043) y `libraauth` copiado por `libracore-unir-bases` (ADR-082 del motor), `medlibra_core` dejó de hacer falta. Lo que seguía diciendo «dos bases» era: la variable del core del compose de dev, el `docker/postgres-init/10-base-de-libracore.sql` que creaba la segunda, `base_core_separada=True` en los dos scripts del provisioning (que el motor ya ignora para este producto), y la suite entera (`tests/motor_de_test.py` armaba `medlibra_gw0` **y** `medlibra_core_gw0` por worker).
- Qué ya existe (se miró antes de tocar): ADR-083 de libracore y su `CHANGELOG` («Para los productos (PR 6)»), `url_de_auth` de libraauth v0.55.0, `libracore-unir-bases verificar`, el ADR-043 de este repo y el ADR-035 de GestioLibra (el mismo PR, en paralelo). `plans.aplicar_plan_en_db` ya tiene el cuerpo propio contra `medlibra_modulos` desde el ADR-043 y **no envuelve** a `apply_plan_modules`, así que no necesita `tabla=` (punto 6 del ADR-083).
- Decisión:
  1. **`scripts/nuevo_cliente.py` y `scripts/panel_admin.py`**: `configure(..., tabla_modulos="medlibra_modulos")` y fuera `base_core_separada=True`, **en los dos** (`configure()` pisa un `_cfg` global: el que corre último gana). El alta nace con una base (`bases_postgres == ("medlibra",)`, sin `postgres-init`) y espera/escribe los módulos en `medlibra_modulos`, no en la `modulos` del motor (sin eso, el alta terminaba en `AltaIncompleta`, o peor, prendía los adicionales en una tabla que la app no lee). Cierra el punto «abierto para el motor» del ADR-043. Lo ata `tests/test_migraciones_en_el_deploy.py`.
  2. **🔴 `libraauth-migrar` se queda con `--base core`, y NO pasa a `--base dominio` como decía el plan.** *(Superado por el ADR-046: con dev y demo ya unidas pasó a `--base dominio`; lo que sigue es lo medido entonces.)* Medido el 2026-10-25 con una instancia de dos bases corrida con las cadenas del deploy (dominio con `libragenda`+`alembic`, core con `libraauth`+`libracore`, `MEDLIBRA_LIBRACORE_DATABASE_URL` puesta, como la demo): `libraauth-migrar upgrade --prefijo medlibra --base dominio` **termina bien** y crea en el dominio las tablas de auth (`usuarios`, `auth_log`, `alembic_version_libraauth`, …) vacías, al lado de las reales del core; después `libracore-unir-bases verificar` pasa de «Se puede unir» a un impedimento `auth_en_los_dos` (más dos `choque_de_tablas`). O sea: el `command:` de la demo, o un `panel_admin.py actualizar`, dejaría la unión de la demo imposible sin avisar. `--base core` es correcto en las dos formas: con la variable (demo) va al core; sin ella (dev unida y todo alta nueva) cae al dominio porque `medlibra` figura en `_UNA_SOLA_BASE`. En una base única los dos valores van al mismo lugar, así que **cambiarlo a `dominio` es un PR de una línea cuando la demo esté unida**, no antes. Lo atan `test_libraauth_va_con_base_core_hasta_que_no_quede_una_instancia_de_dos_bases`, `test_a_donde_va_libraauth_con_una_base_y_con_dos` (la resolución real de `url_de_auth`) y `test_libraauth_con_base_dominio_en_una_instancia_de_dos_bases_deja_la_union_imposible` (lo medido, de punta a punta, con `libracore-unir-bases verificar`).
     - **La guarda de arranque** (`exigir_schema_al_dia(..., base=config.base_de_auth)`, ADR-043) no cambia: dice `--base dominio` cuando la instancia es de una base y `--base core` cuando son dos. Es el mismo comando que el del deploy salvo el valor de `--base`, y en una base única los dos van al mismo lugar; `tests/test_arranque_exige_cadena_libraauth.py` fija las dos cosas.
  3. **`docker-compose.yml` (servicio dev)**: sin `MEDLIBRA_LIBRACORE_DB_PATH`, sin el montaje de `docker/postgres-init` y sin ese directorio (`10-base-de-libracore.sql` borrado; también la excepción `!docker/postgres-init/*.sql` del `.gitignore`). El `command:` no cambia (sigue diciendo lo mismo que `migraciones`, lo ata el test). Con esto el override temporal del VPS se retira.
  4. **CI**: `smoke-navegador.yml` ya no define `MEDLIBRA_LIBRACORE_DATABASE_URL` ni crea `medlibra_core`; `ci.yml` sólo cambia comentarios (el job pasa `MEDLIBRA_TEST_DATABASE_URL` y el arnés deriva el resto).
  5. **La suite es de una sola base** (`tests/motor_de_test.py`, `tests/conftest.py`, `tests/bases_temporales.py`): una base por worker (`medlibra_gw0`, …) con una plantilla `armada` (auth + `create_app()`) y el estado «vacío» de siempre (sin tablas, sólo la cadena de auth); se fueron `_PG_CORE`, `medlibra_core_gwN`, `destino_libracore` y `MEDLIBRA_LIBRACORE_DB_PATH`. La fixture además **borra** las dos variables del core del entorno, así que la suite no depende de lo que tenga exportado quien la corre. `correr_cadena` corre las cuatro cadenas con los argumentos del deploy (`--base core`) y, con una base, **sin** variable del core. **La plantilla `armada` es una instancia migrada** (corre las cuatro cadenas del deploy antes de `create_app()`) y la fixture apunta `DATABASE_URL` a la base del worker: el restore de un backup vuelve a correr las cuatro cadenas en subprocesos con el entorno del proceso, y sobre una base sin tablas de versión `libragenda-migrar` muere con `relation "resources" already exists`. Antes `libragenda-migrar` y `alembic` migraban *otra* base (`DATABASE_URL` del job apunta a un SQLite) y solo `libracore-migrar`, por la variable del core, tocaba la restaurada: los tests de restore pasaban sin probar esas dos cadenas; ahora las prueban de verdad. La forma de dos bases (la demo) se sigue midiendo con bases propias y descartables (`tests/test_una_sola_base.py`).
  6. **`scripts/reset_demo.sh` no cambia de lógica** *(superado por el ADR-046: ya no lee la variable del core)*: lee `MEDLIBRA_LIBRACORE_DATABASE_URL`/`_DB_PATH` **del contenedor** (no las define) y, si no están, usa la base del dominio. Es lo que hace seguro resetear la demo mientras tenga dos bases; sacarlo la dejaría con el core (usuarios, códigos de acceso, caja) intacto y sin avisar. Se simplifica cuando no quede ninguna instancia de dos bases. `app/config.py` y `app/asgi.py` tampoco cambian, por lo mismo.
  7. **Lo que NO hace este PR: pasar las filas de `medlibra_modulos` a la `modulos` del motor** (ADR-043: «queda para después de unir»). Ni el pedido de este PR ni el ADR-083 del motor lo incluyen (el ADR-083 deja `tabla_modulos="medlibra_modulos"` como la forma vigente y dice «el día que lean la `modulos` del motor, dejar de pasarlo»). Es una decisión con datos (copiar filas en dev con el SQL que ya prueba `tests/test_una_sola_base.py`, cambiar la lectura de `ModuleRepository`, verificar y recién ahí borrar `medlibra_modulos`, con OK) y se hace aparte, con su propio despliegue.
- Consecuencias:
  - **Despliegue en `dev`** (ya unida): retirar el `docker-compose.override.yml` temporal y levantar con el compose nuevo. Quitar el montaje de `postgres-init` **recrea el contenedor `medlibra-postgres`** (cambia su configuración; el volumen de datos no se toca): unos segundos de base caída. La app arranca sin variable del core y cae a la base del dominio (`app/config.py`, ya probado con el override).
  - **Despliegue en la demo** (dos bases todavía): **nada que hacer mientras no se una**. Su compose lo genera el panel y declara la variable; el código la sigue leyendo. Cuando se una (`libracore-unir-bases`, con respaldo y OK), se quita la variable de su compose y desde ahí es igual que dev.
  - **Altas nuevas** (`nuevo_cliente.py`, `panel_admin.py`): nacen con una base y `medlibra_modulos`. Ninguna instancia existente cambia por subir esto.
- Tests: `tests/test_migraciones_en_el_deploy.py` (nuevos: cadena de auth y su destino con una y con dos bases, scripts con `tabla_modulos` y una sola base), `tests/test_una_sola_base.py` (la cadena entera sin variable del core, sin `medlibra_core`, y `--base dominio` sobre dos bases), `tests/test_arranque_exige_cadena_libraauth.py` y `tests/test_config_backup.py` (el ZIP lleva una base, una vez). Se probó que se ponen rojos sin el cambio (ver el PR).

## ADR-045 — MedLibra sin conexión: la PC del consultorio como nodo de LibraEdge (2026-10-25)

- Estado: propuesta. Es el PR 10 del plan «GestioLibra, MedLibra y LibraDesk en la versión de escritorio» (wiki del ecosistema, `libraedge-gestiolibra-medlibra-libradesk-2026-10-24`, fila 10 y «Decisiones del humano»). Parte de la rama del PR 6 (ADR-044, una sola base), todavía sin mergear. El instalador y la prueba en VM son el PR 12.
- Contexto: un consultorio sin internet tiene que seguir atendiendo. Decisiones del humano (2026-10-21 y 2026-10-25, «ok a todo»): la **historia clínica se copia completa** a la PC del consultorio (disco cifrado y clave de Windows: eso es del instalador y de la documentación, no de este código); **notas, recetas, pedidos de estudio y consentimientos se cargan sin conexión** (son altas, no se pisan); el **paciente nuevo** sin conexión tiene un **número provisorio con cartel** y, si ya existía con ese DNI, **se une a su ficha** al subir; **demanda espontánea y «no vino», sí**; **turnos nuevos, no** (la agenda es de sólo consulta, pero un turno ya dado se atiende); un turno atendido que en la web se canceló o se movió **cuenta igual y queda «a revisar»**; los **documentos adjuntos se ven sólo con internet**; y lo cobrado lo manda a ContaLibra **el central** al aplicar, no la PC.
- Qué ya existe (se miró antes de diseñar): `app/offline.py` de LibraClub (ADR-023) y de LibraCargo, y los ADR-020 a 023 de LibraClub (clientes provisorios, reservas en el nodo); `libraedge` v0.23.0 (ADR-019 la guarda del espejo, ADR-021 las altas en el nodo, ADR-026 los ids provisorios de texto); `libragenda.atencion_en_nodo` v0.15.0 (ADR-019 de libragenda: `atender_en_nodo`, `aplicar_turno_atendido`, `turnos_a_revisar`, `encolar_en_nodo`); `libra-ui` v0.181.0 (ADR-095: `EtiquetasDeTurnoDelNodo`, `EtiquetaDePersonaDelNodo`, `TurnosARevisar`); `libracore.nodo_offline` (`SinConexion`, `SoloEnElCentral`, `ConexionDelNodo`); y el envío a ContaLibra de este producto (ADR-035 y ADR-036). Lo que MedLibra **no** tiene —caja, factura, cola de ARCA, stock— no se copia.
- Decisión:
  1. **`app/offline.py`** declara lo propio: las tablas de referencia (`TABLAS_DE_REFERENCIA`, 36, más los dos mapeos que suma el aprovisionamiento), las de sólo lectura (`TABLAS_SOLO_LECTURA`), las dos altas en el nodo (`agenda_clients` y `patients`, `id_de_texto=True`), `encolar_operacion` (la costura de LibraGenda y de los altas del producto con el outbox, **en la transacción de la sesión**), la identidad (`nodo()`, `en_linea()`, `CONEXION`) y el `aprovisionamiento` (sedes = `branches`). Un test (`tests/test_nodo_aprovisionamiento.py`) exige que **toda tabla de la base migrada decida su lugar**: espejada, o excluida con su motivo.
  2. **Quién manda sobre qué.** El central manda sobre los maestros, los precios, la configuración y **los turnos**: bajan por el espejo y son de sólo lectura (la guarda de LibraEdge, LE001). El nodo escribe sólo lo que no se pisa: **pacientes** (id provisorio `"-N"`), **notas, recetas, pedidos de estudio y consentimientos** (uuid propio) y **llegadas de demanda espontánea** (uuid propio, número de llegada provisorio negativo). Los usuarios son los del central (libraauth ADR-027); `medlibra_modulos` no se siembra en un nodo.
  3. **Pacientes** (`app/services/pacientes_nodo.py`). `POST /patients` en un nodo da un id `"-N"` y encola `paciente.alta` en la misma transacción que las dos filas (`agenda_clients` y `patients`: la segunda tiene clave primaria que es a la vez foránea a la primera, y las dos tienen alta y mapeo propios). El central aplica con SQL propio sobre la conexión del receptor (así la ficha y su mapeo son atómicos): **busca por DNI** (sin puntos ni espacios; también un paciente dado de baja) y lo une a esa ficha sin tocarla, o le da el siguiente `p-NNN` del mismo contador que usa la web; sin DNI **no deduplica** (un duplicado se junta a mano; una nota atada a otra persona no se nota). Idempotente por mapeo; un id provisorio reusado por otra persona va a revisión manual.
  4. **🔴 Lo «a verificar» del ADR-026 de LibraEdge, medido** (`tests/test_nodo_pacientes.py`, contra el `MirrorApplier` real y la ficha real, PostgreSQL 16): cuando el nodo ya bajó la ficha definitiva, `reapuntar` **no mueve** `patients -1` —la **borra**, porque `patients` es del espejo y la definitiva ya bajó—, así que la clave primaria **no choca**. Lo que cuelga de `patients -1` desde otra tabla del espejo (una nota cargada con el paciente provisorio) se borra con ella —es la copia local—; la operación sigue entera en el outbox y la nota **vuelve por el espejo con el mismo uuid** ya en la ficha definitiva. Si `agenda_clients` se reapunta antes que `patients` y hay una nota colgando, falla por la clave foránea, LibraEdge lo deshace y lo reintenta en el barrido del final del ciclo. **Converge sin duplicar ni perder nada.** Lo único visible es que, entre el mapeo y la nota, la copia local no se ve (el mismo ciclo si el `push` subió todo; hasta el siguiente si se cortó).
  5. **Historia clínica** (`app/services/historia_en_nodo.py`). Los ids de nota, receta, pedido y consentimiento son `uuid4` de la aplicación: el nodo y el central **no pueden dar el mismo**, así que no hay mapeo ni id provisorio. La fila nace en el nodo con su id definitivo y sube como `nota.alta`, `receta.alta`, `pedido_estudio.alta` o `consentimiento.alta` (con sus ítems) en la misma transacción; el central la crea **con el mismo id** (`ON CONFLICT (id) DO NOTHING`), traduciendo el paciente. Una nota que llega antes que el alta de su paciente se rechaza (`SinMapeo`) y se reintenta al resolver el alta. **No se hace en el nodo:** borrar historia clínica (409 `solo_en_el_central`), cargar el resultado de un estudio (409) y los **documentos adjuntos** (409 `sin_conexion`; con conexión, `solo_en_el_central`: son archivos del disco del central, la lista —las filas— sí se lee).
  6. **Demanda espontánea** (`app/services/walkins_nodo.py`). `walkin.registrado` y `walkin.estado`. El número de llegada del nodo es **negativo** (`UNIQUE (block_id, day, arrival_order)` no puede chocar con lo que se anote en la web, o el espejo se trababa) y la fila lo ordena después de lo que ya tenía número; el central le da el siguiente real (`max + 1`, con candado) y la llegada baja con su número definitivo. Los pases de estado aplican las transiciones de la web: el mismo otra vez no hace nada, y uno que la web ya no admite va a revisión manual.
  7. **Atender un turno** (`app/services/atencion_nodo.py`, rutas `POST /appointments/{id}/start|complete|no-show`). En un nodo, `atender_en_nodo` deja la fila propia y encola `turno.atendido` en una sola transacción; el turno del espejo no se toca. La agenda muestra la atención encima del espejo (`atendido_en_la_pc`) y `a_revisar`/`motivo` de lo que ya subió y chocó. Dar, confirmar, cancelar y mover turnos es 409 (`sin_conexion` sin conexión, `solo_en_el_central` con ella). **«Empezar» y «No vino» son rutas nuevas también en la web** (no existían: la agenda sólo completaba); «no vino» usa `InMemoryScheduler._transition` porque LibraGenda no tiene el verbo público.
  8. **El central manda a ContaLibra, una sola vez.** El nodo calcula la consulta con las mismas funciones que la web (`precio_del_turno`, `pagos_del_turno`, la alícuota) y la lleva en `extra.consulta` (la plata, como texto). Al aplicar, `al_aplicar` (que LibraGenda llama una sola vez por atención, en su transacción, también si quedó a revisar: *lo cobrado se conserva*) anota la fila de `envios_a_contalibra` en `pendiente`, o `sin_destino` sin `CONTALIBRA_URL`; **después de confirmar**, `enviar_pendiente` la reclama con un `UPDATE ... WHERE estado = 'pendiente' AND intentos = 0` y manda. Garantías contra el doble envío: una sola vez por `atencion_id`; **una fila por turno** (si la web ya lo mandó, no sale otro y el turno queda a revisar con `ya_atendido`); el reclamo atómico entre dos entregas a la vez; y ContaLibra es idempotente por `(sistema, referencia)`. Un fallo no rechaza la atención (queda `error` en `/facturacion-externa`, con su reintento de siempre); si el proceso muere entre confirmar y mandar, la próxima entrega de la operación lo manda. La PC no guarda `CONTALIBRA_SERVICE_TOKEN`.
  9. **Turnos a revisar.** `GET /turnos-a-revisar` (staff, en las dos puntas: la tabla de LibraGenda baja al nodo) con los nombres de `AtencionAplicada` que espera `libra-ui/TurnosARevisar`, más el paciente, la prestación, la hora y el huso de la sede; `POST /turnos-a-revisar/revisadas` (sólo el central; en la PC es 409). No cambia el turno ni la atención.
  10. **Aprovisionamiento y sincronización.** `/sync/v1/push|pull` (y el 501 del ticket de ARCA, que MedLibra no presta) con el `Despachador` de `app/routers/sincronizacion_offline.py` (ocho tipos), «Sucursal sin internet» y el canje del código, como en LibraClub; migración `0024_libraedge` (las tablas de LibraEdge en toda instancia); `GET /api/nodo/conexion` para el cartel «Sin conexión»; los routers de maestros y configuración llevan `escritura_solo_en_el_central`.
  11. **Pantallas** (libra-ui v0.181.0): `EtiquetasDeTurnoDelNodo` junto al estado del turno, «Turnos a revisar» (pantalla, entrada de menú y aviso en la agenda), `EtiquetaDePersonaDelNodo` en la lista y la ficha del paciente y en la fila de demanda espontánea, el cartel «Sin conexión» con la frase de MedLibra y el aviso «Turno atendido sin conexión». **No hay bandeja de la cola** (`BandejaDeLaCola`, ADR-094): MedLibra no tiene cola de comprobantes.
- Qué no hace / queda abierto:
  - **Cifrado de la historia clínica en la PC** (disco cifrado, clave de Windows, la PC dentro del consultorio, respaldos cifrados) y **borrar los datos locales al dar de baja la PC**: son del instalador y de la documentación; acá no hay nada que lo haga cumplir. `dar-de-baja` revoca el nodo y el plan anota que **no se verificó** que borre la base local.
  - **`actividad_log` no sube**: cada punta lleva el suyo. Quién abrió una ficha en la PC queda en la PC, no en el log de la web.
  - **Editar o borrar un paciente en la PC** es 409 (también el provisorio: la operación ya encolada llevaría los datos viejos). Se corrige en la web.
  - **Dos nodos en la misma sede** no están contemplados (LibraEdge permite uno activo por sede).
  - **Si el central rechaza una operación** (queda en revisión manual) la copia local de lo que traía puede desaparecer de la PC por el reapuntado (punto 4) mientras no se resuelva; el contenido está entero en `sync_inbox`.
- Lo que falta para el instalador (PR 12 del plan, `libraedge:instalador/productos/medlibra.json` + `app_id` nuevo + íconos + prueba en VM):
  - **Variables de la base**: `MEDLIBRA_DATABASE_URL` y `DATABASE_URL` con la **misma** URL (la segunda la leen `libragenda-migrar` y `alembic`; `MEDLIBRA_LIBRACORE_DATABASE_URL` ya no existe: una sola base, ADR-044). `base_auth`: `dominio`. `asgi`: `app.asgi:app`, `salud`: `/health`, `version_esquema`: `alembic`. No lleva `LIBRAEDGE_CARGA_INICIAL` (MedLibra no tiene existencias).
  - **Cadenas de migraciones, en este orden** (las de `scripts/panel_admin.py`): `libragenda-migrar upgrade`; `libraauth-migrar upgrade --prefijo medlibra --base dominio`; `libracore-migrar upgrade --prefijo medlibra`; `alembic upgrade head` (tabla de versión `alembic_version_medlibra`, que ahora incluye `0024_libraedge`). `libragenda` va primero: las revisiones propias tienen claves foráneas a sus tablas. Con v0.15.0 de LibraGenda la cadena suma `0011_node_attendances`.
  - **Tablas espejo, de sólo lectura y altas**: las arma `offline.aprovisionamiento` y `libraedge-central nodo registrar` las manda en la carga (`LIBRAEDGE_TABLAS_ESPEJO`: 38 tablas, `LIBRAEDGE_TABLAS_SOLO_LECTURA` y `LIBRAEDGE_ALTAS_EN_NODO=agenda_clients,patients`); el instalador no las escribe a mano. (`id_de_texto` no viaja en la carga: el nodo ve el tipo de la clave en su base, libraedge ADR-026.)
  - **Variables del nodo** (las escribe el instalador, ver `Alta.entorno_del_nodo()`): `LIBRAEDGE_NODE_ID`, `LIBRAEDGE_NODE_SECRET`, `LIBRAEDGE_PREFIJO`, `LIBRAEDGE_ESTADO` (de ahí sale `en_linea`) y `LIBRAEDGE_VERSION_ESQUEMA`. La PC **no** lleva `CONTALIBRA_URL` ni `CONTALIBRA_SERVICE_TOKEN`.
  - **Del lado del central**, para aprovisionar y revisar: `LIBRAEDGE_APROVISIONAMIENTO=app.offline:aprovisionamiento` y `LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador` en el entorno de `libraedge-central` (documentarlo en el runbook).
  - **La historia clínica en una PC** (decisión del humano: se copia completa): disco cifrado (BitLocker), usuario de Windows con clave, la PC dentro del consultorio, respaldos del nodo cifrados y **borrado de la base local al dar de baja la PC** (no verificado que `dar-de-baja` lo haga). Es documentación e instalador, no código de este repo.
  - **Pendiente de pantalla**: la sección «Sucursal sin internet» de Configuración (`libra-ui/SucursalSinInternet`, ADR-077 de ese kit) no está cableada acá —tampoco en LibraClub—; el backend (`/api/nodos-offline*`) ya está montado.
- Consecuencias: **MINOR**, sin cambio para quien no es un nodo (cada guarda y cada gancho preguntan `offline.nodo()` y fuera de un nodo no hacen nada). Pines: `libragenda` v0.14.0 → v0.15.0 (**migración `0011_node_attendances` de LibraGenda**: correr `libragenda-migrar upgrade` antes de arrancar), `libraedge` v0.23.0 (nueva, pública: sin deploy key en el CI ni en el build) y `libra-ui` v0.180.0 → v0.181.0. Migración propia `0024_libraedge`, aditiva e idempotente.
- Tests: `tests/test_nodo_atencion.py` (atender en el nodo, la agenda con la atención encima, el envío a ContaLibra desde el central —una sola vez entre dos entregas, con otro `operation_id`, con dos hilos, tras morir el proceso—, a revisar, 409), `tests/test_nodo_pacientes.py` (alta provisoria, unión por DNI, idempotencia, las guardas y el reapuntado contra el `MirrorApplier` real), `tests/test_nodo_historia.py`, `tests/test_nodo_walkins.py`, `tests/test_nodo_aprovisionamiento.py` (toda tabla decide su lugar, la matriz de rutas, lo que el nodo no hace) y `frontend/src/test/nodo-sin-conexion.test.tsx`. Se comprobó que **se ponen rojos sin el arreglo** (ver el informe del PR).

## ADR-046 — `libraauth-migrar` pasa a `--base dominio` y el reset de la demo es de una sola base (2026-10-25)

- Estado: aceptada. Cierra lo que el ADR-044 dejó anotado en sus puntos 2 y 6 («se cambia cuando la demo esté unida», «se simplifica cuando no quede ninguna instancia de dos bases»). Es el pendiente chico del plan «GestioLibra, MedLibra y LibraDesk en la versión de escritorio» (wiki del ecosistema, `libraedge-gestiolibra-medlibra-libradesk-2026-10-24`, sección Estado y fila 6). Sin migración, sin cambio de pin. Es el mismo cambio que el ADR-037 de GestioLibra.
- Contexto: el 2026-10-25 dev **y demo** quedaron de **una sola base** (unidas con `libracore-unir-bases`; la variable del core salió de sus composes) y no hay clientes reales. Ya no existe ninguna instancia de dos bases, que era la única razón de `--base core` (con `--base dominio` sobre dos bases la unión quedaba imposible por `auth_en_los_dos`, medido en el ADR-044).
- Decisión:
  1. **`libraauth-migrar upgrade --prefijo medlibra --base dominio`** en `scripts/panel_admin.py`, `scripts/nuevo_cliente.py` y el `command:` del compose de dev (lo ata `tests/test_migraciones_en_el_deploy.py`, que mira los tres lugares). `dominio` resuelve `MEDLIBRA_DATABASE_URL` y, si no está, su histórico `DATABASE_URL` (que es lo único que define el compose): se probó con `url_de_auth`.
  2. **La guarda de arranque** (`exigir_schema_al_dia(..., base=config.base_de_auth)`) no cambia de código: ya decía `--base dominio` con una base y `--base core` con dos, y ahora coincide, palabra por palabra, con el comando del deploy (`tests/test_arranque_exige_cadena_libraauth.py` lo fija; antes comparaba "salvo el valor de `--base`").
  3. **`scripts/reset_demo.sh` es de una sola base**: no lee `MEDLIBRA_LIBRACORE_DATABASE_URL`/`_DB_PATH` del contenedor, recrea el schema de la base del dominio (una vez) y guarda y devuelve los códigos de acceso de esa misma base.
  4. **`app/config.py` y `app/asgi.py` quedan tolerantes**: si aparece la variable del core con otra base, `Config` y el respaldo siguen andando con las dos (lo miden `tests/test_una_sola_base.py` y `tests/test_config_backup.py`), pero el camino normal, el que prueba la suite y el único que define este repo, es una base. Sólo las leen `Config._url_del_core` y el puente de `asgi.py` (`url_de_instancia(..., core=True)` + `setdefault`), ambos inertes si la variable no está.
  5. **Tests**: se reemplazó el que medía que `--base dominio` sobre dos bases rompía la unión (el escenario ya no existe) por `test_libraauth_va_con_base_dominio` (los dos scripts y el compose), `test_a_donde_va_libraauth_con_base_dominio` (`url_de_auth` con `MEDLIBRA_DATABASE_URL` y con sólo `DATABASE_URL`) y `test_libraauth_con_base_dominio_deja_las_tablas_de_auth_en_la_unica_base` (el comando corrido de verdad sobre una base nueva). `correr_cadena` corre `--base dominio` por defecto; el test de la instancia de dos bases (tolerada) pide `base_de_auth="core"`, que es lo que dice `Config.base_de_auth` para esa forma.
- Consecuencias:
  - **Despliegue**: dev y demo ya corren la cadena con `--base core`; con la base única los dos valores van al mismo lugar, así que **desplegar esto no cambia el destino de ninguna migración** (ni hace falta migrar nada).
  - **LibraEdge** (otro repo, otro PR): `instalador/productos/medlibra.json` declara `--base core` y `base_auth: core`. Funciona igual mientras el nodo sea de una sola base; conviene alinearlo a `dominio`.
- Tests: ver el punto 5.

## ADR-047 — Adoptar libracore v1.195.0 (ADR-084 del motor): la ruta de conexión del nodo es del motor y fuera `MEDLIBRA_LIBRACORE_DB_PATH` (2026-10-25)

- Estado: aceptada. Es lo que el ADR-084 de libracore pide a MedLibra. Sin migración.
- Contexto: `app/routers/nodo.py` escribía a mano `GET /api/nodo/conexion` (ADR-045) porque el motor sólo la ofrecía con un `PuertoDeVentas`. Y el motor todavía leía `MEDLIBRA_LIBRACORE_DB_PATH` como nombre histórico de la variable del core, así que no podía sacarlo de `_HISTORICOS` mientras este repo lo nombrara (`tests/conftest.py`, `tests/test_una_sola_base.py`, `app/config.py`).
- Decisión:
  1. **Pin `libracore` v1.195.0.**
  2. **La ruta de conexión es del motor:** `build_conexion_del_nodo_router(conexion=offline.CONEXION, usuario_actual=require_staff)` reemplaza `app/routers/nodo.py` (borrado). Se usa `offline.CONEXION` y no `ConexionDelNodo(nodo=offline.nodo, en_linea=offline.en_linea)`: es la misma clase con las mismas funciones, pero atadas por nombre en cada pedido (ya la usa la barra del pie y el comentario de `offline.py` dice por qué). Ruta, guarda (cualquier usuario de la instancia) y respuesta, iguales; MedLibra no factura y `a_facturar` queda en 0.
  3. **Fuera `MEDLIBRA_LIBRACORE_DB_PATH`** de `tests/conftest.py`, `tests/test_una_sola_base.py` (se retira `test_el_nombre_historico_del_core_se_sigue_aceptando`: el nombre que medía ya no existe), `app/config.py`, el compose y el README (que todavía describía el modo SQLite). Los ADR y el CHANGELOG anteriores lo siguen nombrando: son historia.
  4. **`app/asgi.py` sin el `setdefault` del core:** existía para llevar el nombre histórico al normalizado; sin histórico no hace nada, y `Config` resuelve la base de LibraCore por su cuenta.
- Consecuencias: ninguna instancia cambia. Una variable `MEDLIBRA_LIBRACORE_DB_PATH` suelta ya no la lee este repo; el motor deja de leerla cuando saque el histórico.
- Tests: `tests/test_nodo_aprovisionamiento.py` (`test_el_cartel_de_conexion_distingue_la_pc_del_central` y `test_el_cartel_pide_sesion`) ya fijan la ruta, la respuesta y la sesión, y valen sin cambios.

## ADR-048 — La espera de los ya atendidos: se guarda cuándo se llamó a cada llegada (2026-10-28)

- Estado: aceptada. Pedido del humano: *«Demanda espontánea: la espera de los ya atendidos y el alta de paciente desde la fila»*. **Migración `0025_walkin_called_at`** (aditiva, una columna nullable).
- Qué ya existía (se miró antes de diseñar): el **alta de paciente desde la fila ya está hecha** y no se toca: la pantalla usa `SelectCliente` con `altaDePaciente` (ADR-041, desde 2026-10-16: nombre, DNI, teléfono y email; `POST /patients` sin `id`, el backend da el `p-NNN`), el paciente recién creado queda elegido y la llegada se anota con su id (`alta-de-paciente.test.tsx`, «Anotar llegada»); sin conexión el paciente nace provisorio (`-N`, con cartel «Provisorio») y la llegada que lo nombra sube y se traduce al aplicarse (ADR-045, `test_una_llegada_de_un_paciente_provisorio_se_traduce`). Lo que decía el ADR-038 («sólo anota pacientes existentes») ya no vale. **Lo que sí faltaba era la espera de los atendidos**: `walkins` tenía `created_at` y nada más, así que la pantalla sólo podía mostrar «Espera» para quien todavía esperaba y ponía «—» al resto (ADR-038, «Lo que queda abierto»).
- Decisión:
  1. **`walkins.called_at`** (`timestamptz`, nullable): el instante en que la llegada pasó a `in_progress`. `WalkinRepository.cambiar_estado` lo escribe **sólo** en ese pase; completar no lo toca y sacar de la fila sin haberla llamado lo deja vacío (si guardara el momento de la baja, el promedio del día mentiría para abajo). Sale en `WalkinOut.called_at` (UTC, como `created_at`). **La espera de un atendido es `called_at - created_at`**: lo que esperó **hasta que lo llamaron**, no hasta que terminó la consulta.
  2. **Vacío = «no lo sabemos».** Las llamadas anteriores a la migración no tienen el dato y no hay backfill posible: la pantalla muestra «—» y **no las cuenta en el promedio**, en vez de inventar una espera con «ahora».
  3. **Sin conexión (ADR-045): el mismo instante en las dos puntas.** `cambiar_estado` toma **un** `ahora` y lo usa para la fila de la PC y para el `at` de `walkin.estado` (`encolar_estado(..., en=ahora)`); `aplicar_walkin_estado` guarda ese `at` como `called_at` del central cuando el pase es a `in_progress`, y la fila vuelve a la PC por el espejo con el mismo valor. **No cambia el contrato de la operación** (`at` ya viajaba y ya se validaba; `version` 1, `schema_version` 1): un central viejo que reciba la operación la sigue aplicando, sólo ignora la hora. La espera de quien se atendió sin conexión se mide con la hora de la PC y no con la de cuándo subió. Dos relojes (PC y central) pueden desfasarse unos segundos: la cuenta nunca da negativo (el piso es 0).
  4. **La pantalla** (`DemandaEspontanea.tsx`): los atendidos salen de la fila y van a su propia lista, **«Atendidos hoy»** (o «Atendidos el dd-mm-aaaa»), con N°, paciente, prestación, hora de llegada, hora en que los llamaron (las dos en la hora de **la sede**, ADR-028) y **Esperó**. En la fila, quien ya está en atención muestra lo que esperó, fijo, en vez de «—» (antes ni siquiera eso) y quien espera sigue contando hasta ahora. El resumen suma «N atendidos» y la **espera promedio hasta que los llaman** del día, calculada sobre quienes ya pasaron a atención (en atención + atendidos) **con** dato, con la cantidad entre paréntesis para que se vea sobre cuántos es.
  5. **No se expone nada más.** La lista usa los mismos datos que la fila (nombre, prestación, horas): ni DNI, ni teléfono, ni nada clínico; el endpoint sigue siendo `staff_or_admin` y `called_at` es un instante, no un dato de salud.
- Qué no hace / queda abierto:
  - **No hay histórico por varios días ni promedios por profesional o prestación.** La espera queda guardada, así que un reporte es una consulta (`called_at - created_at`), pero no se armó.
  - **No mide la duración de la consulta** (`in_progress` → `completed`): sería otra columna (`completed_at`) y nadie la pidió.
  - **`GET /patients` sigue trayendo la lista completa** al abrir la pantalla (el selector busca en el cliente, igual que Agenda): es anterior a este cambio y no se tocó.
- Consecuencias: **MINOR**. Migración `0025_walkin_called_at`: aditiva, idempotente en los dos mundos (instancia armada por migraciones o por `create_all`) y sin la tabla; el downgrade saca la columna. Al desplegar, `alembic upgrade head` antes de arrancar, como siempre. El nodo la recibe por la cadena de migraciones y el espejo de `walkins` no cambia de forma (la tabla ya baja entera).
- Tests (verificados por mutación: sin el arreglo se ponen rojos): `tests/test_walkins.py` (llamar guarda `called_at` y completar no lo pisa; sacar sin llamar no lo inventa; un cambio rechazado no lo toca), `tests/test_nodo_walkins.py` (la PC y la operación llevan el mismo instante, el central lo guarda, completar y cancelar no lo pisan), `tests/test_migracion_walkin_called_at.py` (los dos mundos, sin tabla, downgrade) y `frontend/src/test/demanda-espontanea.test.tsx` (los atendidos van a su lista con la hora de la sede, la espera fija no crece, el promedio cuenta sólo lo que tiene dato, «—» sin dato).

## ADR-049 — Los recordatorios de turno salen de verdad por WhatsApp y por mail, sin datos de salud (2026-10-28)

- Estado: aceptada. Pedido del humano: *«Etapa 2 del WhatsApp: que los recordatorios de turno de MedLibra salgan de verdad por WhatsApp o mail»*. **Sin migración propia**: usa la tabla `avisos_envios` de libracore (`libracore-migrar`, revisión `0032`, que el deploy ya corre). Pines: libracore `v1.202.0` y libra-ui `v0.184.0` (ya estaban).
- Qué ya existía (se miró antes de diseñar): `libragenda` decide **cuándo** toca recordar (`ReminderDispatcher`, políticas `24h` y `2h`) y entrega a un puerto, `NotificationPort.send(notificacion)`, que el producto implementa; hasta hoy era `LoggingNotificationPort`, que escribía una línea al log. El motor (libracore ADR-090, `docs/avisos.md`) trae **cómo sale un mensaje y que no salga dos veces**: `NotificacionPorAvisos` (el adaptador estructural del puerto), `despachar` idempotente por clave, los proveedores SMTP, Evolution, Registro y Apagado, `reintentar_fallidos`, `build_avisos_router` y la tabla `avisos_envios`. El kit (ADR-097) trae `ConfiguracionDeAvisos` y `RegistroDeAvisos`. **No se escribió ningún proveedor, ni ningún despachador, ni ninguna pantalla de configuración**: lo único propio es el contacto del paciente, el texto y dónde viven la pantalla y el cron.
- Decisión:
  1. **`app/avisos.py`** arma `NotificacionPorAvisos(proveedores, contacto=…, redactar=…)` y reemplaza al `LoggingNotificationPort` (que se borra). `contacto(client_id)` sale del paciente (`agenda_clients`): `phone` pasa por `telefono_para_whatsapp` (lo hace el adaptador) y `email` va tal cual. `proveedores` es `lambda: configuracion.proveedores(smtp_config)`, **resuelto en cada envío**: el admin cambia el modo en la pantalla sin reiniciar, y el `smtp_config` es el mismo resolver del correo de recuperación de contraseña y de la sonda de Integraciones.
  2. **La clave del aviso es `agenda:{turno}:{política}`** (la arma el adaptador): `24h` y `2h` de un mismo turno son dos avisos, y el mismo no sale dos veces **aunque `dispatch` lo repita** (el libro `sent_reminders` de `libragenda` es un segundo seguro, no el único). La clave lleva ids, nunca el teléfono ni el mail: aparece en los logs.
  3. 🔴 **Datos de salud (Ley 25.326 de protección de datos personales y Ley 26.529 de derechos del paciente): el texto del recordatorio no lleva nada clínico.** Un WhatsApp lo puede leer cualquiera que vea la pantalla del teléfono, y un mail, quien tenga la casilla; que alguien tiene un turno *en tal consultorio* no es lo mismo que *de qué*. El recordatorio dice **sólo**: la sede, la fecha (con el día de la semana), la hora —**de la sede, no UTC**—, el profesional, el consultorio y la dirección si la hay, y el teléfono de la sede para cambiarlo. **No dice la prestación** (una «consulta oncológica» o un «control de embarazo» ya dice qué le pasa a la persona), **ni el motivo del turno, ni el nombre del paciente, ni su DNI**. Se sostiene por construcción y con tests: `texto_del_recordatorio` es una función pura cuyos parámetros no incluyen ninguno de esos datos, y `redactar` ni siquiera lee el servicio del turno. Los tests siembran una prestación «Consulta oncológica» y un paciente con nombre y DNI, y fallan si cualquiera aparece en el texto de WhatsApp, en el cuerpo o en el asunto del mail.
     - *Límite honesto:* el nombre del profesional y el del consultorio los carga el consultorio. Si los escribe con la especialidad («Dra. Vidal — Oncología»), esa palabra viaja. Es un dato del negocio y no un campo clínico, pero quien configura lo tiene que saber: conviene el nombre a secas.
     - El **registro de avisos** (`avisos_envios`) guarda el destino y el texto tal como salieron, para contestar «¿le llegó?». Como el texto no lleva nada clínico, el registro tampoco; y sólo lo lee el admin.
  4. **`/api/avisos/*`** lo monta `build_avisos_router(require_admin=require_admin, smtp_config=…)`: `GET`/`PUT /config`, `POST /probar`, `GET /envios`, **todo admin** (el guard es obligatorio en el motor y cubre las cuatro rutas). Sin sesión 401; `staff` (médicos y mostrador) 403. La `apikey` de Evolution es sólo de escritura. `PUT` y `probar` dan 409 `solo_en_el_central` en un nodo (lo resuelve el router del motor, y un test lo sostiene).
  5. **`dispatch` reintenta lo que falló.** `POST /reminders/dispatch` y el script del cron llaman a `enviar_recordatorios`: primero `dispatch`, **después** `reintentar_fallidos` en cada canal. Es *mejor esfuerzo*: una excepción del reintento se loguea y no convierte en 500 una tanda que ya salió (el libro ya dio los recordatorios por enviados). Consecuencia que conviene tener presente: un mensaje que falla se reintenta en la misma tanda, así que un Evolution caído gasta dos de los tres intentos en la primera corrida; los siguientes los reparte el cron.
  6. **Quién corre `dispatch`.** Se buscó y **en este repo nada lo corría**: `POST /reminders/dispatch` pide la sesión de un admin y no hay cron ni script versionado (el docstring decía «pensado para un cron externo»). Sin algo que lo llame, ningún recordatorio sale, con o sin motor. Se agrega **`scripts/enviar_recordatorios.py`**, el mismo lazo que `libraclub/scripts/enviar_avisos.py`: arma la app como el servidor (conecta la base y enchufa el almacén de secretos, sin el cual Evolution no tiene la `apikey`), respeta lo que respeta la ruta (el módulo `recordatorios` del plan; un nodo no manda) y deja **una línea por corrida sin ids ni pacientes**. Se corre cada 10 minutos: `*/10 * * * * docker exec medlibra-dev python /app/scripts/enviar_recordatorios.py >> /var/log/medlibra_recordatorios.log 2>&1`. **Instalar el cron en el VPS no es parte de este cambio** (es un cambio remoto, y queda para el humano o para una tanda de deploy).
  7. **Pantalla: una sección «Avisos» de Configuración** (`pages/configuracion/avisos.tsx`), con `ConfiguracionDeAvisos` arriba y `RegistroDeAvisos` abajo, y no una entrada nueva del menú: Configuración ya es sólo de admin (el menú y el backend), ya aloja el correo (Integraciones) y ya es donde se carga lo que se toca poco. Así no hay ruta nueva ni entrada de menú que tenga que cumplir `titulos-con-icono` y `iconos-del-catalogo` (el guard del catálogo de íconos y el del título): las pantallas del menú quedan exactamente como estaban. El ícono de la pestaña es `BellRing` (no es un concepto del catálogo de la familia, ADR-035). `RegistroDeAvisos` recibe `esAdmin`, o sea que **muestra el destino entero**: es verdad por construcción (la sección sólo se monta ahí) y el kit enmascara (`••••••••1234`) si alguien la monta sin la prop.
  8. **LibraEdge: `avisos_envios` no se espeja al nodo.** `EXCLUIDAS` de `tests/test_nodo_aprovisionamiento.py` ya la tenía (la agregó el bump a libracore v1.202.0, «el registro de avisos es del central»); se verificó que `app/offline.py` no la nombra, ni en `TABLAS_DE_REFERENCIA` ni en el aprovisionamiento. El nodo no manda avisos: `despachar` contesta `en_nodo` y el script se niega en un nodo; los manda el central.
- Qué no hace / queda abierto:
  - **No hay SMS** ni plantillas de Meta: Evolution no las usa. Si llega la API oficial de Meta, `Mensaje` ya trae `plantilla` y `variables`.
  - **Los recordatorios ya dados por vistos no se reenvían al prender un canal.** `libragenda` marca un recordatorio como enviado apenas `send` vuelve, haya salido por algún canal o no (con todo apagado, también). Lo que quedó `registrado` en modo Registro **no se manda** cuando después se conecta Evolution (la guía del motor lo describe para su barrido propio; acá `dispatch` no vuelve a ver ese recordatorio y `reintentar_fallidos` no reenvía `registrado` a propósito). Es lo correcto para un recordatorio —un turno que ya pasó no le sirve a nadie—, pero quien conecta Evolution en producción tiene que saber que **empieza con los turnos que venzan desde ese momento**.
  - **El paciente no puede pedir no recibir avisos**: no hay un campo de preferencia. El motor tiene el estado `omitido` para eso; falta el dato.
  - **No se confirma por WhatsApp** (responder «sí» al recordatorio): Evolution entrante es otro trabajo.
  - **El huso es el de la sede** del profesional (`Branch.timezone`); un recurso sin sede sale en UTC, igual que el resto del producto (`husos.SIN_SUCURSAL`).
  - **No hay `demo` en la pantalla**: el kit lo acepta como prop, pero el producto no tiene de dónde leerlo; sin ella, el motor igual lo dice al guardar Evolution (422) y al probar (simulado). Una demo nunca manda.
- Consecuencias: **MINOR**, sin migración propia. **Al desplegar:** nada que migrar (`avisos_envios` la crea la cadena de libracore que el deploy ya corre); los avisos nacen **apagados**: ninguna instancia manda nada hasta que un admin elija «Registro» o conecte Evolution, y hasta que el cron esté instalado. `LoggingNotificationPort` se borra (nadie más lo importaba).
- Tests (verificados por mutación: sin el cambio se ponen rojos): `tests/test_avisos_de_turnos.py` (despacho por Registro y por Evolution simulado con `httpx.MockTransport`; el texto sin prestación, paciente ni DNI; idempotencia aun borrando el libro de `libragenda`; paciente sin teléfono y con teléfono dudoso `omitido`; mail por su canal; todo apagado no escribe nada; el reintento después de `dispatch` por HTTP; un fallo del reintento no rompe la tanda; la matriz de roles de las cuatro rutas de `/api/avisos`; la `apikey` que no vuelve; el script del cron con el plan sin el módulo y en un nodo), `tests/test_nodo_aprovisionamiento.py` (`PUT /api/avisos/config` y `POST /api/avisos/probar` dan 409 en un nodo) y `frontend/src/test/avisos.test.tsx` + `configuracion-forma.test.tsx` (la sección, su lugar, el destino entero del admin y el tipo legible).

## ADR-050 — La marca blanca: la instancia puede llevar el nombre, el logo, el color y los términos de un revendedor (2026-10-30)

**Estado:** aceptada. Cableado del piloto de marca blanca (libracore ADR-092 y ADR-093, libraauth ADR-030, libra-ui ADR-098). Pines: `libracore` v1.202.1 → v1.206.0 (incluye la v1.204.0: un aviso por un solo canal y demos sin mails, ADR-090 y ADR-091), `libraauth` v0.56.0 → v0.57.0, `libra-ui` v0.184.0 → v0.185.0. **Sin migración.**

**Decisión.**
1. `app/main.py` monta `build_marca_router(dist=…)` (lectura pública, manifest e íconos) y `build_marca_admin_router()` detrás de `require_admin_o_servicio`, igual que el tema: lo cambia el admin o el backoffice (token de servicio).
2. 🔴 `TerminosRepository(contrato_propio=leer_terminos_propios, exigir_propio=es_marca_propia)`: con marca propia la instancia **exige** los términos del revendedor y, sin ellos, queda frenada; nunca cae a los de la familia. Importa más en MedLibra que en otros productos: quien acepta es personal de un consultorio que carga historias clínicas.
3. `PasswordResetService(product_name=lambda: nombre_de_marca("MedLibra"))`: el mail de recuperación sale con el nombre de la marca.
4. El manifest tiene que ganarle al catch-all de la SPA (que arma `app/asgi.py`), así que `app/frontend_dist.py` resuelve el dist una sola vez y lo usan `main.py` (el manifest de respaldo) y `asgi.py` (para servirlo).
5. `main.tsx` espera `cargarMarca()` (tope de 2 s, no falla) antes de montar la SPA.

**Qué cambia además, por el pin (no por la marca).** libracore v1.204.0 (decisión del humano del 2026-10-28, ADR-090 addendum) hace que **un aviso salga por un solo canal**: WhatsApp si está disponible y el paciente tiene un teléfono válido, y el mail de respaldo (sin teléfono, o si WhatsApp lo rechaza). El ADR-049 lo daba por los dos; `test_con_los_dos_canales_…` de `tests/test_avisos_de_turnos.py` se ajustó a esto. Quien quiera los dos canales pasa `politica="todos"` a `NotificacionPorAvisos`. **Qué no cambia:** los recordatorios (ADR-049) siguen sin datos de salud y con el texto de siempre: la marca sólo toca el nombre, el logo, el color y los términos, no lo que dicen los avisos.

**Pendiente a propósito.** `MEDLIBRA_RESET_URL_BASE` tiene por defecto `dev.medlibra.com.ar/reset-password`: una instancia de revendedor tiene que definirla o el link del mail de recuperación apunta a dev. Los textos legales públicos y el emisor del TOTP no cambian en este PR (PR 14 de la serie).

**Tests (verificados por mutación):** `tests/test_marca_blanca.py` (rutas montadas, quién escribe, mail con el nombre de la marca, manifest antes del catch-all con el `app.asgi` real) y `tests/test_marca_blanca_terminos.py` (marca `sin_aceptar_terminos`: la instancia con marca y sin términos queda frenada y no acepta los de la familia).
