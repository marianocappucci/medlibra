# Tasks — MedLibra

Trabajo concreto vigente. La dirección estratégica permanece en `ROADMAP.md`; este archivo no es un historial.

## En curso

Ninguna en curso registrada. Frontend: facturación (ver ADR-025)
desplegada y verificada en `dev.medlibra.com.ar` real con ambos
roles — cierra la Fase 4 completa (login, agenda/turnos, pacientes,
dominio clínico, dashboard y facturación).

## Próximas

- [ ] Frontend: `PatientCreate` sigue exigiendo un `id` explícito en el
      formulario de alta — a diferencia del `Client.id` de Gestiolibra
      (autogenerado desde su ADR-024, por ser alta frecuencia). Evaluar
      el mismo cambio (`id` opcional en el backend, generado con
      `uuid4()` si no se manda) si la carga manual del id resulta
      fricción real en el uso diario.
- [ ] `docker compose` deriva el nombre de proyecto del nombre de
      carpeta del cliente (`clientes/prueba`) — como Gestiolibra también
      tiene un cliente `prueba`, ambos comparten el mismo nombre de
      proyecto compose y cada `docker compose up`/`restore-db` sobre uno
      avisa "orphan containers" mencionando al contenedor del otro
      producto (`medlibra-prueba` ⟷ `gestiolibra-prueba`). Ambos
      contenedores están correctamente nombrados y aislados
      (`container_name` explícito) — es solo un warning cosmético hoy,
      pero **nunca correr `--remove-orphans` en ninguno de los dos** sin
      revisar antes, podría bajar el cliente del otro producto por
      error. No es específico de MedLibra (viene de
      `libracore.provisioning`), no se toca sin necesidad concreta.
- [ ] Dashboard: sumar facturación/caja (dejado fuera del primer corte
      a pedido explícito del usuario) — reutilizando
      `libracore.db.caja.get_caja_resumen()`, ya genérico.
- [ ] Upload real de certificado/clave ARCA (`PUT /config/arca` hoy acepta
      solo paths en el filesystem del servidor, el admin coloca los
      archivos a mano — ver ADR-016). Mejora futura, no bloqueante.
- [ ] Revisar el cálculo de IVA de facturación (`_split_iva`, 21% fijo
      sobre el monto final) con un contador antes de facturar contra ARCA
      real — no contempla servicios de salud exentos ni otras alícuotas
      (ver ADR-016).
- [ ] Cargar credenciales ARCA reales (CUIT, certificado, alta de
      servicio WSFE) cuando el usuario las tenga — hoy solo funciona en
      modo mock (`ENV=development`).
- [ ] `test_reminders.py::test_dispatch_sends_due_reminders_and_is_idempotent`
      sigue fallando con 409 al crear un turno (bug preexistente,
      encontrado y flagueado en la ronda de facturación del 2026-07-22,
      sin relación con esta ronda) — pendiente de investigar la causa raíz.

## Decisiones pendientes

Ninguna.

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

Resuelto (2026-07-22): facturación/caja con LibraCore (ver ADR-016).
CUIT/condición de IVA como extensión del paciente (migración
`0009_patient_billing_fields`). `POST /appointments/{id}/complete`
completa el turno (LibraGenda `v0.7.0`) y, si el servicio tiene precio
configurado en la sucursal, factura el total con
`libracore.arca_facturacion` (LibraCore `v0.16.1`) — una sola factura,
tipo A/B según condición de IVA del paciente, seña ya cobrada y saldo
restante como dos movimientos de caja separados apuntando a la misma
factura. `PUT`/`GET /config/arca` (admin-only) para la config ARCA del
consultorio (instancia única, "empresa" fija). `libragenda` a `v0.8.0`
(agrega `medio_pago` opcional a `Deposit`). Contalibra/Restolibra
migraron su `arca_helper.py` propio a un shim sobre el módulo nuevo de
LibraCore, con confirmación explícita del usuario en cada paso de
producción. 36 tests nuevos, verificado además end-to-end contra
archivos SQLite reales (no memoria — `libracore.db` abre una conexión
nueva por llamada). Bug real preexistente encontrado y flagueado aparte
(no corregido en esta ronda): `test_reminders.py::test_dispatch_
sends_due_reminders_and_is_idempotent` falla con 409 al crear un turno,
reproducible en un checkout limpio sin ningún cambio de esta sesión.

Resuelto (2026-07-22): dashboard — turnos (total y por estado en un
rango, turnos de hoy), pacientes (total activos, altas nuevas en el
rango) y recordatorios enviados/señas pendientes (ver ADR-017).
Facturación/caja quedó fuera de este primer corte a pedido del usuario.
`GET /dashboard?date_from=&date_to=` (admin-only). `patients.created_at`
(migración `0010_patient_created_at`, nullable, sin backfill).
`libragenda` a `v0.9.0` (agrega `list_sent()`/`list_by_status()`). 7
tests nuevos (167 en total) — uno de ellos encontró y corrigió un bug
real en el propio test (no en el producto): comparar un turno a "+2
horas" contra el rango de "hoy" calculado por separado falla cerca de
medianoche UTC, cuando el turno cae en el día siguiente.

Resuelto (2026-07-25): planes con enforcement real + infraestructura de
deploy + primer deploy real al VPS (ver ADR-018). `plans.py`
(Básico/Estándar/Premium, $25k/$40k/$60k — todo el dominio clínico
siempre libre, solo recordatorios/señas/facturación/dashboard son
gateables), tabla `modulos` (migración `0011_modulos`),
`require_module()`. `Dockerfile`/`docker-compose.yml`/`app/asgi.py`/
`scripts/` — mismo patrón que Gestiolibra, sin stage de frontend
(MedLibra no tiene todavía). 19 tests nuevos (188 en total). Deploy key
dedicada de solo lectura generada para el propio repo
(`id_ed25519_medlibra`, alias `github-medlibra`), repo clonado al VPS,
imagen `medlibra:latest` construida reutilizando las deploy keys de
LibraCore/LibraGenda ya cargadas en el ssh-agent multi-key
(`agent-multi-libra.sock`, sin generar nuevas para esas dos
dependencias). Cliente de prueba `prueba` (puerto 8078, plan Premium)
dado de alta con `nuevo_cliente.py`: contenedor healthy, login
verificado, endpoint clínico (`/patients`) respondiendo sin gating y
dashboard funcionando (plan Premium incluye el módulo). Queda corriendo
en el VPS como evidencia del pipeline completo.

Resuelto (2026-07-25, continuación): dominio propio con SSL real (ver
ADR-020). `medlibra-dev` levantado por primera vez contra el VPS
(puerto 8077, `.env` generado, bug menor de `dev-data/` inexistente
corregido). `dev.medlibra.com.ar` (DNS ya apuntaba al VPS, sin tocar)
con proxy NPM + certificado Let's Encrypt real, reutilizando la misma
instancia y credenciales de NPM que ya usan Contalibra/Restolibra/
Gestiolibra — `forward_host` corregido a `172.18.0.1:8077` desde el
principio (sin repetir el hallazgo que le costó un proxy mal apuntado a
Gestiolibra). Verificado con `curl -v` (TLS 1.3, 200 en `/health`)
desde el VPS y desde la máquina de desarrollo.

Resuelto (2026-07-25, continuación): backups verificados de punta a
punta contra el cliente real `prueba` (`panel_admin.py backup`/
`restore-db`, heredado de LibraCore sin cambios). Paciente marcador
creado → `backup prueba` (tar.gz + copia WAL-safe de la DB vía
`sqlite3.Connection.backup()`) → marcador borrado y paciente nuevo
creado (mutación deliberada) → `restore-db prueba <archivo>` (detiene
el contenedor, guarda un backup automático previo, restaura, reinicia)
→ confirmado que el marcador vuelve y la mutación posterior desaparece.
Contenedor healthy tras el restore. Hallazgo de proceso (no un bug):
`docker compose` deriva el nombre de proyecto del nombre de carpeta del
cliente — como Gestiolibra también tiene un cliente `prueba`, ambos
comparten nombre de proyecto y cada operación sobre uno avisa "orphan
containers" mencionando al del otro producto; ambos contenedores están
correctamente aislados por `container_name` explícito, es solo un
warning cosmético — documentado como precaución en "Próximas" (nunca
correr `--remove-orphans` sin revisar).

Resuelto (2026-07-25, sesión siguiente): primer frontend de MedLibra,
MVP de login + agenda/turnos (ver ADR-021). React 19 + TypeScript +
Vite, mismo stack y patrón exacto que Gestiolibra (Tailwind CSS +
shadcn/ui + TanStack Table + React Hook Form + Zod). Selector de
paciente lee `/patients` de solo lectura; sin CRUD de pacientes,
dashboard ni facturación en el frontend todavía. `Dockerfile` con stage
`node:20-slim` nuevo, `app/asgi.py` sirve los estáticos + catch-all.
`npm run build` sin errores (bundle ~540 KB gzip ~166 KB). 187 tests de
backend sin cambios. Desplegado y verificado en `dev.medlibra.com.ar`
real: login, página de Agenda con "Paciente" en toda la UI, ciclo
completo de un turno (alta → confirmar → completar) confirmado contra
la API real. Sin errores de consola.

Resuelto (2026-07-25, continuación): página de Pacientes (CRUD, ver
ADR-022). Mismo patrón que `Clientes.tsx` de Gestiolibra, con `dni`/
`birth_date` propios de `Patient` y gating por rol distinto: alta/
edición para `staff`+`admin` (coincide con el backend, personal médico
necesita cargar pacientes), borrado solo `admin`. Sin auto-generar
`id` todavía (a diferencia del `Client.id` de Gestiolibra). `npm run
build` sin errores. Verificado en `dev.medlibra.com.ar` real con ambos
roles: alta/edición/borrado confirmados contra la API real como admin;
como staff, "Eliminar" no aparece. Sin errores de consola.

Resuelto (2026-07-25, continuación): ficha del paciente con el dominio
clínico completo (ver ADR-023). Página `/pacientes/:id` con pestañas
(historia clínica, recetas, estudios, documentos, consentimientos),
componentes shadcn `Tabs`/`Textarea` nuevos, formularios dinámicos
(`useFieldArray`) para ítems de receta/estudio, mini-formulario propio
para resultados de estudio, `api.postForm` nuevo para la carga
multipart de documentos. `npm run build` sin errores. Verificado en
`dev.medlibra.com.ar` real como admin: alta y listado en las 5
pestañas contra la API real (incluida la carga y descarga de un
documento con el contenido exacto), y como staff que el botón
"Eliminar" no aparece en historia clínica (mismo gating que ADR-022,
reutilizado sin cambios). Sin errores de consola.

Resuelto (2026-07-25, continuación): dashboard (ver ADR-024). Mismo
componente que `Dashboard.tsx` de Gestiolibra sin la card de
facturación (turnos por estado, pacientes activos/nuevos, recordatorios/
señas). Ruta `/reportes` (no `/dashboard`, mismo motivo que Gestiolibra —
evita que el catch-all del SPA colisione con el endpoint real de la
API), ítem de menú oculto para `staff`. `npm run build` sin errores.
Verificado en `dev.medlibra.com.ar` real: como admin, datos reales
(`GET /dashboard` → `200`); como staff, ítem de menú ausente y mensaje
de acceso denegado dedicado al navegar directo a `/reportes` (`GET
/dashboard` → `403` confirmado en red). Sin errores de consola.

Resuelto (2026-07-25, continuación): facturación (ver ADR-025) — cierra
la Fase 4 completa. Página `/facturacion` (config ARCA), mismo
componente que Gestiolibra sin cambios de campos. Diálogo de medio de
pago en `Agenda.tsx` al completar un turno con saldo pendiente (backend
responde 422, se pide el medio de pago en vez de mostrar el error
crudo) y diálogo de factura emitida tras completar. Componente `Dialog`
(shadcn) recreado. `npm run build` sin errores. Verificado en
`dev.medlibra.com.ar` real: config ARCA guardada, precio de servicio
configurado, turno completado con saldo pendiente → diálogo → factura
real emitida (Factura B, CAE, total correcto). Como staff, ni Dashboard
ni Facturación aparecen en el menú, y el mensaje de acceso denegado se
ve al navegar directo a la ruta. Sin errores de consola.

## Notas de testing

- Igual que Gestiolibra: la suite usa cookies de sesión firmadas con
  timestamp (`itsdangerous`, vía `libracore.auth.SessionAuth`). En entorno
  WSL2 el reloj puede saltar hacia atrás ~20s en medio de una corrida
  (desincronización WSL2↔host Windows), invalidando un cookie válido
  (`SignatureExpired: age <0`) — 401 intermitente y no reproducible (~1
  cada 10-15 corridas). No es un bug de la app ni ocurre en el servidor
  real. Si un test de auth falla aislado sin cambios de código, reintentar
  antes de investigar.
