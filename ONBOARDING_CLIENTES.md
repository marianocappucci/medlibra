# Guía de onboarding — Cliente nuevo en MedLibra

Esta guía es para vos, Mariano. Describe el proceso completo para dar de alta a un cliente
nuevo de MedLibra —consultorios y centros médicos— desde la contratación hasta que está
operando.

> **Qué es MedLibra y qué no.** Es el vertical de **turnos para salud**: agenda, pacientes,
> sedes, profesionales y el dominio clínico (historia clínica, recetas, órdenes de estudio,
> documentos y consentimientos). Si el negocio es de servicios no clínicos —barbería,
> estética, taller— el producto es Gestiolibra, que es el mismo motor sin nada de lo clínico.

> 🔴 **Acá se manejan datos de salud de terceros.** No copiar bases entre instancias, no sacar
> exports a la máquina local "para probar", y no usar datos de un paciente real en una demo.
> Cada cliente vive en su propio contenedor y su propia base justamente por esto.

---

## Resumen del proceso

1. Recopilar datos del cliente
2. Levantar la instancia
3. Primer acceso
4. Configurar el centro, las sedes y los horarios
5. Cargar profesionales, servicios y precios
6. Aplicar el plan contratado
7. Configurar integraciones (recordatorios, ARCA) según el plan
8. Crear los usuarios
9. Handoff: primer ingreso con el cliente

---

## 1. Datos a recopilar antes de empezar

| Dato | Para qué sirve |
|------|----------------|
| Nombre del consultorio o centro | Aparece en la app y en los recordatorios |
| Slug | Nombre corto sin espacios: define `clientes/<slug>/` y el subdominio |
| Plan contratado | Define qué módulos quedan habilitados |
| Sedes | Nombre y dirección de cada una |
| Horarios de atención | Por sede y por día; sin esto no hay grilla de turnos |
| Profesionales | Quiénes atienden y en qué sede |
| Prestaciones / servicios | Nombre y duración — la duración define el largo del turno |
| Precios e IVA por prestación | MedLibra permite IVA distinto por servicio |
| ¿Cobra seña? | Módulo `senas`, desde el plan Estándar |
| ¿Quiere recordatorios? | Módulo `recordatorios`, desde el plan Estándar |
| ¿Necesita facturar? | Módulo `facturacion` + ARCA, sólo en Premium |
| Usuario y contraseña del admin | Para el primer acceso — comunicar por WhatsApp, no por email |

---

## 2. Levantar la instancia

Cada cliente corre en su propio contenedor, aislado en `clientes/<slug>/`, todos compartiendo
la imagen `medlibra:latest`. El puerto base de este producto es **8078** (los asigna el
provisioning mirando los puertos realmente ocupados del host).

### Setup único del servidor

`nuevo_cliente.py` y `panel_admin.py` son wrappers finos sobre `libracore.provisioning`, y el
Python del sistema del VPS no tiene `pip` por política de Debian (PEP 668). Por eso corren con
un venv dedicado en `/root/medlibra/.venv-scripts`, **gitignored — no se versiona y no llega
por `git pull`**. Si hay que recrearlo:

```bash
apt-get install -y python3-venv
python3 -m venv /root/medlibra/.venv-scripts
/root/medlibra/.venv-scripts/bin/pip install \
  "libracore @ git+ssh://git@github-libracore/marianocappucci/libracore.git@<TAG>"
```

Dos cosas que no son obvias:

- **`<TAG>` es el pin que declara el `pyproject.toml` de *este* repo**, no un número común a
  la familia. Cada producto pinea su propia versión de LibraCore, y el venv del host tiene que
  espejar la suya: si queda atrás, el CLI opera con un motor distinto del que corre la
  instancia. Ya frenó un deploy de Contalibra por eso.
- **La URL va por SSH (`git+ssh://git@github-libracore/…`), no por HTTPS.** En este VPS el
  `https://` del `pyproject.toml` falla: la autenticación es por deploy key con alias en
  `~/.ssh/config`. `httpx` y el resto de las dependencias entran solas con LibraCore.

### Alta de un cliente nuevo

En el servidor, desde `/root/medlibra`:

```bash
./.venv-scripts/bin/python3 scripts/nuevo_cliente.py
```

El wizard pide nombre, slug, puerto, dominio, plan y credenciales de admin; crea
`clientes/<slug>/` (compose + `data/` con base, config y adjuntos aislados), buildea la imagen
si falta, levanta el contenedor y —si hay dominio— crea el proxy y el certificado en Nginx
Proxy Manager.

### Gestión del día a día

```bash
./.venv-scripts/bin/python3 scripts/panel_admin.py            # menú interactivo
./.venv-scripts/bin/python3 scripts/panel_admin.py listar     # instancias, puerto y estado
./.venv-scripts/bin/python3 scripts/panel_admin.py info <slug>
./.venv-scripts/bin/python3 scripts/panel_admin.py backup <slug>
./.venv-scripts/bin/python3 scripts/panel_admin.py actualizar [slug...]   # sin args = todas
./.venv-scripts/bin/python3 scripts/panel_admin.py pausar <slug>          # banner, sin cortar acceso
./.venv-scripts/bin/python3 scripts/panel_admin.py suspender <slug>       # corta el acceso
```

Lo mismo por navegador desde el backoffice, en **https://admin.medlibra.com.ar**.

### DNS y dominio

- El wildcard `*.medlibra.com.ar` ya apunta al VPS: **no hay que tocar DNS** por cliente.
- El subdominio es `<slug>.medlibra.com.ar`, y el proxy + SSL los crea el alta.
- Para gestionarlos a mano: `panel_admin.py npm-crear | npm-eliminar | npm-listar`.

> ⚠️ **Al dar de baja una instancia, el proxy no se va solo.** `eliminar` baja el contenedor y
> borra el directorio, nada más. Correr **`npm-eliminar <slug>` antes**, porque después no
> queda `cliente.json` de donde leer el dominio — y ese comando depende de que el campo
> `domain` esté cargado ahí.

---

## 3. Primer acceso

```
URL: https://<slug>.medlibra.com.ar
Usuario: el que definiste en el alta
Contraseña: la que definiste — comunicarla por WhatsApp
```

---

## 4. Configurar el centro, sedes y horarios

**Sin horarios cargados no hay grilla de turnos**, y la agenda se ve vacía aunque todo lo demás
esté bien. Es el error más común del onboarding.

- [ ] **Centro**: nombre, contacto, zona horaria
- [ ] **Sedes**: crear cada una con nombre y dirección
- [ ] **Horarios por sede**: días y franjas de atención
- [ ] **Recursos**: consultorios o boxes de cada sede

---

## 5. Profesionales, prestaciones y precios

- [ ] Cargar los **profesionales** y en qué sede atiende cada uno
- [ ] Cargar cada **prestación** con su duración real — de ahí sale el largo del turno
- [ ] Cargar **precios** (pueden diferir por sede) y la **condición de IVA por prestación**
- [ ] Verificar en la agenda que un turno de prueba tome la duración correcta

---

## 6. Plan y módulos

| Plan | Precio | Qué habilita |
|------|--------|--------------|
| Básico | $25.000 | Agenda, turnos, pacientes y **todo el dominio clínico** |
| Estándar | $40.000 | Todo lo anterior + **recordatorios** y **señas** |
| Premium | $60.000 | Todo lo anterior + **facturación** y **dashboard** |

> **Lo clínico nunca se gatea.** Turnos, pacientes, historia clínica, recetas, órdenes de
> estudio, documentos y consentimientos están en **todos** los planes, incluido el Básico: es
> la necesidad profesional mínima de un consultorio, no un extra vendible (decisión del
> 2026-07-25, `DECISIONS.md` ADR-018). Lo que se vende por nivel es recordatorios/señas y
> facturación/dashboard. La fuente de verdad es `plans.py` de este repo.

---

## 7. Integraciones

### Recordatorios (plan Estándar en adelante)

Acordar canal y anticipación con el cliente, y **probar con un turno real** antes del handoff:
en salud, un recordatorio que no sale es un paciente que no viene.

### Correo saliente (SMTP)

Se configura por instancia desde el backoffice (**Configuración → SMTP** en
`admin.medlibra.com.ar`), no dentro de la app. Para Gmail hay que usar una contraseña de
aplicación.

### ARCA / facturación electrónica (sólo Premium)

La configuración vive en `/config/arca` de la instancia: certificado `.crt`, clave `.key`, CUIT
y punto de venta. Probar en **homologación** antes de pasar a producción.

---

## 8. Usuarios

Los roles de MedLibra son dos (`Role` en `app/routers/users.py`):

| Rol | Puede hacer |
|-----|-------------|
| `admin` | Todo: configuración, usuarios, sedes, prestaciones, facturación |
| `staff` | El día a día: agenda, turnos, pacientes y lo clínico |

- [ ] Crear un `admin` para el titular o el administrativo a cargo
- [ ] Crear un `staff` por cada profesional y por recepción
- [ ] Comunicar las credenciales de forma segura, una por persona
- [ ] **No compartir un solo usuario entre varios profesionales**: la historia clínica queda
      firmada por quien la escribió, y con usuarios compartidos esa trazabilidad se pierde

---

## 9. Handoff con el cliente

1. **Ingresar** — URL, usuario, contraseña
2. **Cargar un turno** desde la agenda
3. **Dar de alta un paciente** y abrir su ficha
4. **Escribir una evolución** en la historia clínica
5. **Emitir una receta** y una **orden de estudio**
6. **Registrar un consentimiento**
7. **Cobrar una seña** (si tiene el módulo)
8. **Dashboard** del día (si es Premium)

Al terminar:

- [ ] Cambiar la contraseña del admin por una que defina el cliente
- [ ] Confirmar que puede cargar un turno y una evolución sin ayuda
- [ ] Dejar el número de soporte

---

## 10. Post-onboarding (primera semana)

- [ ] Contactarlo a los 2-3 días
- [ ] Verificar que los recordatorios estén saliendo
- [ ] Revisar que los horarios cargados coincidan con los reales
- [ ] Confirmar que cada profesional entra con **su** usuario

---

## Checklist resumen

```
DATOS
[ ] Nombre, slug, plan, sedes y horarios recopilados
[ ] Profesionales, prestaciones, duraciones, precios e IVA definidos

INSTANCIA
[ ] Levantada y accesible por HTTPS
[ ] Login funciona

CONFIGURACIÓN
[ ] Centro, sedes y horarios cargados
[ ] Recursos cargados
[ ] Profesionales, prestaciones y precios cargados
[ ] Plan aplicado y módulos correctos
[ ] Recordatorios probados con un turno real (si aplica)
[ ] SMTP configurado y probado (si aplica)
[ ] ARCA en homologación probada (si aplica)

USUARIOS
[ ] admin creado
[ ] Un staff por profesional, sin usuarios compartidos

CAPACITACIÓN
[ ] Handoff hecho
[ ] El cliente carga un turno y una evolución solo

POST-ONBOARDING
[ ] Seguimiento a los 3 días
[ ] Horarios y recordatorios verificados en uso real
```

---

## Contacto de soporte

- WhatsApp: +54 9 11 2775-2983
- Email: soporte@medlibra.com.ar
