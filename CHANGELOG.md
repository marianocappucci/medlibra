# Changelog — MedLibra

## [Unreleased]

- **Demanda espontánea: la fila por orden de llegada** (ver ADR-031). ADR-030
  dejó la modalidad `espontanea` a medias — el bloque se podía crear pero no se
  le podía anotar a nadie. Ahora un bloque de demanda espontánea tiene su
  **fila**: se registra la llegada (`POST /agenda-blocks/{id}/walkins`), se ve la
  cola del día, y se llama / completa / cancela.
  - 🔴 **No es un turno sin hora.** Un `Appointment` de LibraGenda *es* un
    horario, y darle uno inventado haría que ese horario falso choque contra los
    turnos de verdad, ocupe el consultorio y aparezca en la grilla como si
    alguien tuviera esa media hora reservada.
  - **El número de llegada es histórico y no se renumera**: cancelar al segundo
    no convierte al tercero en segundo. Quién sigue se calcula filtrando por
    estado, no por el número.
  - Registrar una llegada **valida el bloque**: tiene que ser de demanda
    espontánea, y el día tiene que caer en su día de la semana y su vigencia.
  - Va con los turnos y no con la configuración: **la secretaria** anota a quien
    entra por la puerta, no hace falta ser admin.
  - 14 tests nuevos (372 en la suite), verificados por mutación. Migración
    `0016_walkins` probada contra `postgres:16` real, ida y vuelta; el único por
    `(bloque, día, orden)` verificado **en la base**, no sólo en el modelo.
  > Todavía **sin pantalla**: como el resto de la parametrización de agenda, hoy
  > se opera por API.

- **Consultorios y bloques de agenda** (ver ADR-030): el consultorio pasa a ser
  una **entidad propia** (`/consultorios`) y la agenda de un profesional se arma
  con **bloques** (`/agenda-blocks`): *"la Dra. Vidal atiende los lunes de 9 a 13
  en el Consultorio 2, turnos de 20 minutos, hasta el 31 de diciembre"*. Sobre la
  `Availability` de LibraGenda, el bloque agrega las tres cosas que le faltaban —
  **dónde** se atiende, **hasta cuándo** (vigencia por rango de fechas) y
  **cuánto dura** un turno (10/15/20/25/30 min, lista cerrada que sirve
  `GET /agenda-blocks/opciones`) — más la modalidad **por turnos o por demanda
  espontánea**.
  - 🔴 **Dos profesionales ya no entran en el mismo consultorio a la misma
    hora.** Es un choque que el motor no puede ver: LibraGenda asocia el turno a
    un solo recurso —el profesional— así que dos agendas impecables por separado
    se pisaban en la puerta de la sala sin que nada protestara.
  - **La duración la manda el bloque**, no la prestación: la prestación dice qué
    se hace, el bloque cuánto dura un turno de esa agenda.
  - Un bloque **por demanda espontánea no genera horarios**: si los generara, se
    le podrían dar turnos con hora encima de una franja que no trabaja con
    horarios. La cola por orden de llegada llega en el cambio siguiente.
  - **Nada de lo que ya andaba cambia.** Los bloques se **suman** a la
    disponibilidad semanal cargada por `/resources/{id}/availability`; sin bloque
    que cubra el horario, la duración sigue siendo la de la prestación y no hay
    sala que declarar. La migración `0015` sólo crea tablas vacías.
  - El log de actividad **llamaba "consultorio" al profesional** — con
    consultorios de verdad al lado eso pasó de confuso a incorrecto. La etiqueta
    ahora dice `profesional`.
  - 23 tests nuevos (348 en la suite), verificados por mutación. Migración
    probada contra `postgres:16` real con datos, ida y vuelta.

- **La agenda, como calendario** (ver ADR-029): `/agenda` deja de ser un
  formulario arriba y una tabla abajo con dos `<input type="date">` de rango, y
  pasa a ser el calendario compartido de la familia — **día / semana / mes**,
  con rejilla horaria, color por profesional, referencia y filtro. Decía *qué*
  turnos hay; ahora dice **cuánto ocupa cada uno y dónde está el hueco**, que es
  la pregunta de quien atiende el teléfono. Todo el estado va en la URL
  (`?vista=&dia=&profesional=&turno=`): se puede mandar "mirá el jueves" por
  mensaje y el botón atrás vuelve del turno al día y del día a la semana.
  `libra-ui` sube de `v0.37.0` a **`v0.38.0`** — bump puramente aditivo, sólo
  agrega `src/agenda/*`. El alta, el diálogo de medio de pago y el de factura
  emitida no se tocaron. 11 tests nuevos (20 en la suite del frontend).
  > 🔴 **El día de un turno es el de la sede, no el del navegador.** Un turno de
  > las 21:30 del lunes en Buenos Aires viaja como `2026-07-21T00:30:00Z`;
  > agrupado por el string crudo aparecería el martes. Es ADR-028 del otro lado
  > del cable, y hay dos tests que se ponen en rojo si esa conversión se saca.

- **La agenda corre en hora de pared, no en UTC** (ver ADR-028): la
  disponibilidad del profesional, el horario de atención y las excepciones se
  cargan en hora del reloj del consultorio, pero el turno se guardaba
  interpretando ese mismo número como UTC. Un turno dado para las **17:00**
  quedaba guardado como `17:00Z`, o sea las **14:00** del consultorio — tres
  horas de corrimiento, que es lo que leen después los recordatorios. Y un
  `starts_at` con offset explícito (una integración, no la pantalla) se
  rechazaba con *"fuera del horario de atención"* aunque cayera adentro.
  Ahora la validación entera —ventanas, excepciones, bloqueos y choques— corre
  en hora de pared y la conversión a instante ocurre en el repositorio
  (`app/services/husos.py`, `_TurnosEnHoraLocal`). Los bloqueos también se
  convierten: uno cargado de 10 a 11 tapaba de 7 a 8.
  **El huso por defecto de una sede nueva pasa de `UTC` a
  `America/Argentina/Buenos_Aires`** — con offset cero el defecto es invisible,
  porque validar en el terreno equivocado da el mismo resultado que validar en
  el correcto. 6 tests nuevos (325 en la suite); 5 existentes cambiaron su valor
  esperado. Sin migración: no cambia el schema.
  > ⚠️ **Los turnos ya guardados no se tocan.** Una instancia que venía
  > operando con la sede en UTC tiene sus instantes escritos con el criterio
  > viejo; el arreglo cambia cómo se interpreta lo que entra de acá en más, no
  > reescribe el pasado.

- **Alícuota de IVA configurable por servicio** (ver ADR-027): hasta ahora
  `billing._split_iva` asumía **21% fijo** para todo, que en un producto de
  salud es el caso equivocado — la mayoría de las prestaciones médicas están
  **exentas**. Ahora la alícuota se configura por servicio
  (`PUT/GET/DELETE /services/{id}/iva`) con un default por instancia
  (`business.default_iva_rate`), y sólo se aceptan las cuatro que ARCA sabe
  mapear (0%, 10,5%, 21%, 27%). Migración `0012_service_iva_rates`, que deja
  el default en **21% — el valor que ya estaba hardcodeado**, así que no le
  cambia la facturación a ninguna instancia existente. 23 tests nuevos
  (232 en la suite), verificados por mutación; migración probada contra
  PostgreSQL real, incluido el downgrade.
  > ⚠️ Esto **no decide qué alícuota le corresponde a cada prestación** —
  > eso lo carga el usuario con su contador. Lo que cierra es que antes no
  > había forma de expresarlo.

- **`DOCS_AUTH_SECRET` expuesto en `docker-compose.yml`**: conecta el
  endpoint `POST /auth/verify` (ver abajo) con el valor real cargado en
  `.env`, necesario para que `/docs/` de `medlibra_web` autentique
  contra esta instancia. Sin cambios de código.
- **Endpoint `POST /auth/verify`** (ver ADR-026): chequeo de credenciales
  sin sesión, protegido por `X-Internal-Auth`/`DOCS_AUTH_SECRET`, para que
  el login de `/docs/` de `medlibra_web` valide contra la instancia real
  del cliente. 5 tests nuevos.

- **Frontend: facturación** (ver ADR-025, cierra la Fase 4 del
  frontend): página `/facturacion` (config ARCA), mismo componente que
  Gestiolibra sin cambios de campos. Diálogo de medio de pago en
  `Agenda.tsx` al completar un turno con saldo pendiente (en vez de un
  422 crudo) y diálogo de factura emitida (tipo, número, CAE, total)
  tras completar. Componente `Dialog` (shadcn) recreado. Ítem de menú
  oculto para `staff`. `npm run build` sin errores. Verificado en
  `dev.medlibra.com.ar` real: config ARCA guardada, turno completado
  con saldo pendiente → diálogo → factura real emitida (Factura B,
  CAE, total correcto) como admin; como staff, ni el menú ni la ruta
  directa muestran contenido.
- **Frontend: dashboard** (ver ADR-024): mismo componente que
  `Dashboard.tsx` de Gestiolibra, sin la card de facturación (turnos
  por estado en el rango, pacientes activos/nuevos en el rango,
  recordatorios enviados/señas pendientes). Ruta `/reportes` (no
  `/dashboard`, evita colisionar con el endpoint real de la API — mismo
  motivo que Gestiolibra), ítem de menú oculto para `staff`. `npm run
  build` sin errores. Verificado en `dev.medlibra.com.ar` real: admin ve
  datos reales, staff no ve el ítem de menú y recibe un mensaje de
  acceso denegado dedicado al navegar directo a la ruta (`GET
  /dashboard` → `403` confirmado).
- **Frontend: ficha del paciente (dominio clínico completo)** (ver
  ADR-023): página `/pacientes/:id` con pestañas — historia clínica,
  recetas, estudios (con resultados anidados por ítem), documentos
  clínicos (carga multipart) y consentimientos —, enlazada desde un
  link "Ver ficha" nuevo en la tabla de Pacientes. Todo append-only
  (crear/listar/borrar admin-only), sin edición. Componentes shadcn
  `Tabs`/`Textarea` nuevos, `api.postForm` nuevo para multipart.
  `npm run build` sin errores. Verificado en `dev.medlibra.com.ar`
  real: las 5 pestañas contra la API real como admin (incluida subida
  y descarga de un documento con el contenido exacto), y como staff
  que "Eliminar" no aparece en historia clínica.
- **Frontend: página de Pacientes (CRUD)** (ver ADR-022): mismo patrón
  que `Clientes.tsx` de Gestiolibra, con `dni`/`birth_date` propios de
  `Patient`. Alta/edición visibles para staff+admin, borrado solo
  admin (coincide con el gating real del backend). `npm run build` sin
  errores. Verificado en `dev.medlibra.com.ar` real con ambos roles.
- **Primer frontend de MedLibra: MVP de login + agenda/turnos** (ver
  ADR-021): SPA en React 19 + TypeScript + Vite (`frontend/`), mismo
  stack y patrón exacto que Gestiolibra (Tailwind CSS + shadcn/ui +
  TanStack Table + React Hook Form + Zod). Selector de paciente lee
  `/patients` de solo lectura; CRUD de pacientes, historia clínica,
  recetas, estudios, documentos, consentimientos, dashboard y
  facturación en el frontend quedan para rondas siguientes. `Dockerfile`
  con stage `node:20-slim` nuevo, `app/asgi.py` sirve los estáticos.
  `npm run build` sin errores. 187 tests de backend sin cambios.
  Desplegado y verificado en `dev.medlibra.com.ar` real: login, ciclo
  completo de un turno confirmado contra la API real.
- **Onboarding multi-consultorio: planes con enforcement real +
  infraestructura de deploy**: `plans.py` (Básico/Estándar/Premium,
  $25k/$40k/$60k) — todo el dominio clínico siempre libre, solo
  recordatorios/señas/facturación/dashboard son gateables por plan.
  Tabla `modulos` (migración `0011_modulos`), `require_module()`
  (`app/modules_gate.py`). `Dockerfile`/`docker-compose.yml`/
  `app/asgi.py`/`scripts/{nuevo_cliente,panel_admin,npm_api,npm_setup}.py`
  — primera infraestructura de deploy de MedLibra, mismo patrón que
  Gestiolibra sin stage de frontend. Primer deploy real al VPS: deploy
  key propia (`id_ed25519_medlibra`), imagen `medlibra:latest`
  construida, cliente de prueba `prueba` (puerto 8078, plan Premium)
  dado de alta y verificado (healthy, login, endpoint clínico sin
  gating, dashboard). `medlibra-dev` levantado por primera vez (puerto
  8077) y `dev.medlibra.com.ar` con proxy NPM + certificado Let's
  Encrypt real. Backups (`panel_admin.py backup`/`restore-db`)
  verificados de punta a punta contra el cliente `prueba`. Ver
  `DECISIONS.md` ADR-018/ADR-019/ADR-020.
- **Dashboard**: `GET /dashboard?date_from=&date_to=` (admin-only) —
  turnos (total y por estado en el rango, turnos de hoy), pacientes
  (total activos, altas nuevas en el rango vía `patients.created_at`
  nuevo, migración `0010_patient_created_at`) y recordatorios enviados/
  señas pendientes. Facturación/caja queda para una entrega futura
  (decisión del usuario). `libragenda` a `v0.9.0` (agrega
  `list_sent()`/`list_by_status()`). Ver `DECISIONS.md` ADR-017.
- **Facturación/caja con LibraCore**: CUIT/condición de IVA como
  extensión del paciente (migración `0009_patient_billing_fields`),
  `PUT`/`GET /config/arca` (config ARCA de instancia única, admin-only),
  `POST /appointments/{id}/complete` — una factura por turno completado
  cuando el servicio tiene precio configurado (tipo A/B según condición
  de IVA), seña ya cobrada y saldo restante como movimientos de caja
  separados sobre la misma factura. `libragenda` a `v0.8.0`, `libracore`
  a `v0.16.1`. Ver `DECISIONS.md` ADR-016.
- **SQLite pasa a ser el destino de producción por defecto** (arquitectura
  silo, mismo estándar que toda la familia Libra) — Postgres sigue
  soportado, ver `DECISIONS.md` ADR-015. LibraGenda actualizado a
  `v0.6.0` (activa `PRAGMA foreign_keys=ON` en toda conexión SQLite). CI
  ya no levanta un servicio Postgres, corre contra un archivo SQLite.
  Bug real corregido de paso: `BranchRepository.delete()` borraba el
  `Branch` antes que `BranchContactRow` (FK invertida) — mismo patrón que
  `PatientRepository`, portado verbatim desde Gestiolibra. `DELETE` de
  sucursales, recursos y servicios ahora devuelve 409 (antes 500) cuando
  todavía tienen registros dependientes.
- Consentimientos: `POST`/`GET /patients/{id}/consents` y
  `GET`/`DELETE /patients/{id}/consents/{consent_id}` — admin+staff,
  DELETE admin-only. Registro de consentimiento informado (procedimiento,
  quién autoriza — paciente o tutor/responsable —, texto libre), sin
  archivo firmado embebido (se sube aparte como documento clínico si hace
  falta), append-only sin revocación editable — retirar un consentimiento
  se registra como uno nuevo, nunca editando el original — ver ADR-014.
  Migración `0008_consents`. Cierra la Fase 2 clínica completa (recetas,
  estudios, documentos, consentimientos); resta solo facturación/caja y
  dashboard, ninguno clínico.
- Documentos clínicos: `POST /patients/{id}/documents` (multipart:
  archivo + título + descripción opcional + autor), `GET`/`DELETE
  /patients/{id}/documents/{document_id}`, descarga vía
  `GET .../{document_id}/file` — admin+staff, DELETE admin-only. Solo
  metadata en la base; archivo en filesystem local bajo
  `MEDLIBRA_DOCUMENTS_DIR` (mismo patrón que Contalibra/Restolibra, sin
  S3/MinIO), nombre en disco normalizado (UUID) — ver ADR-013. Formatos
  aceptados: PDF/PNG/JPG/JPEG, hasta 20MB. Vinculado solo al paciente.
  Migración `0007_clinical_documents`. Suma `python-multipart` como
  dependencia nueva.
- Estudios: `POST`/`GET /patients/{id}/study-orders`,
  `GET`/`DELETE /patients/{id}/study-orders/{order_id}` y
  `POST /patients/{id}/study-orders/{order_id}/items/{item_id}/results`
  (+ `DELETE` de resultado) — admin+staff, DELETE admin-only. Un pedido
  tiene uno o más items (tipo de estudio, motivo); cada item puede tener
  uno o más resultados propios como registros separados, append-only en
  las tres capas — ver ADR-012. Migración `0006_study_orders`. Borrar un
  paciente con pedidos existentes queda bloqueado (409), mismo mecanismo
  ya usado para notas/recetas.
- Recetas: `POST`/`GET /patients/{id}/prescriptions` y
  `GET`/`DELETE /patients/{id}/prescriptions/{prescription_id}`
  (admin+staff, DELETE admin-only). Una receta tiene uno o más items
  (medicamento, dosis, indicaciones), append-only, sin ciclo de vida
  propio (mismo criterio que `clinical_notes`) — ver ADR-011. Migración
  `0005_prescriptions`. Bug de fondo corregido de paso:
  `PatientRepository.delete()` borraba el `Client` antes que la extensión
  `PatientRow` (FK invertida), invisible en SQLite pero rompía contra
  PostgreSQL real.
- Recordatorios y señas: mismo alcance y código que Gestiolibra, portado
  verbatim. `POST /reminders/dispatch` (admin-only, dispara avisos vencidos
  — 24h y 2h antes, fijo) y `POST`/`GET /appointments/{id}/deposit`
  (admin+staff) + `POST /deposits/{id}/mark-paid`/`mark-failed`/`refund`
  (admin-only). Notificaciones y pago sin proveedor real todavía: puertos
  placeholder (`LoggingNotificationPort`, `ManualPaymentPort`) — ver
  ADR-010. Sin migración nueva (`deposits`/`sent_reminders` son tablas de
  LibraGenda).
- Configuración comercial del consultorio: `/branches/{id}/hours` (horario
  comercial semanal por sucursal, opt-in), `/services/{id}/prices` (precio
  por servicio y sucursal), `/branches` ahora acepta `phone`/`address`,
  `/business` (nombre comercial y moneda, singleton). Mismo feature y
  mismo código que Gestiolibra, portado verbatim. Migración
  `0004_business_config`.
- CI (GitHub Actions): `pytest` + smoke check de las dos cadenas de Alembic
  (LibraGenda + propia) contra Postgres de servicio, en cada push/PR a
  `main`. Requiere el secret `LIBRA_PAT` (ver `README.md`).
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
