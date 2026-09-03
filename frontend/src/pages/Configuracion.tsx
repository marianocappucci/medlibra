/** Configuración de MedLibra.
 *
 *  El armado y las secciones comunes vienen de `libra-ui/Configuracion`, que
 *  desde la v0.47.0 es **la pantalla de Configuración de la familia entera** —
 *  la de Contalibra, con su barra de pestañas, la sub-navegación de
 *  Integraciones, el botón de *Backup rápido* y los tutoriales. Acá se declara
 *  sólo lo que corresponde a este producto.
 *
 *  🔴 **La copia única vive en el kit, no acá.** Es el punto del pedido del
 *  humano del 2026-08-29: *"si hago una modificación en la configuración o una
 *  actualización se actualice en todas"*. Cualquier arreglo de esta pantalla se
 *  hace en `libra-ui` y llega a los ocho productos; lo que se escriba en este
 *  archivo llega sólo a MedLibra.
 *
 *  ## Qué integraciones tiene este producto, y cuáles no
 *
 *  Sólo **correo (SMTP)**. Ni ARCA ni MercadoPago, y las dos ausencias son
 *  deliberadas:
 *
 *  - **ARCA no está porque el backend no lo tiene.** El 2026-08-24 se fue el
 *    motor de facturación local (ADR-036): este producto no emite comprobantes,
 *    los emite Contalibra, que es donde vive la contabilidad. `/config/arca`
 *    devuelve 404, no 403.
 *  - **MercadoPago tampoco**: no hay cobro con QR de mostrador acá, así que no
 *    hay endpoints del otro lado. Una pestaña que guarde credenciales que nadie
 *    lee es peor que no tenerla.
 *
 *  Con una sola integración el kit no dibuja la sub-navegación lateral y
 *  muestra el correo directo — ver `libra-ui` v0.49.0.
 *
 *  > 🔴 **El backup de este producto se lleva también los documentos
 *  > clínicos**, que son archivos en disco. Un backup "de la base" los dejaría
 *  > afuera enteros y el usuario se llevaría un ZIP creyendo que tiene los
 *  > estudios de sus pacientes. Ver `app/main.py` y `libracore/respaldo.py`.
 *
 *  ## Las cuatro secciones de la agenda (2026-08-24)
 *
 *  Sedes, Consultorios, Prestaciones y Profesionales entran acá y no como ítems
 *  propios del sidebar: **lo que se configura vive en un solo lugar**, y estas
 *  cuatro son exactamente eso — se cargan al arrancar y se tocan poco, a
 *  diferencia de la agenda y los pacientes, que se usan todos los días.
 */
import { createConfiguracion } from 'libra-ui/Configuracion'
import { CalendarClock, DoorClosed, MapPin, Settings, Stethoscope } from 'lucide-react'
import { SedesCard } from './configuracion/sedes'
import { ConsultoriosCard } from './configuracion/consultorios'
import { PrestacionesCard } from './configuracion/prestaciones'
import { ProfesionalesCard } from './configuracion/profesionales'

export const Configuracion = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: Settings,
  // Sale en el tutorial de Gmail: es el nombre que hay que ponerle a la
  // contraseña de aplicación que se crea en la cuenta de Google.
  producto: 'MedLibra',
  integraciones: { email: true },
  // 🔴 El ORDEN es el del arranque de un consultorio nuevo: dónde se atiende,
  // en qué sala, qué se hace y quién lo hace. Al revés, un consultorio se carga
  // sin sede a la cual pertenecer, una prestación sin poder ponerle precio (el
  // precio es por sede) y un bloque de agenda sin consultorio donde ubicarlo —
  // que es el único campo que no se puede dejar vacío.
  propias: [
    { clave: 'sedes', label: 'Sedes', icono: MapPin, contenido: <SedesCard /> },
    {
      clave: 'consultorios', label: 'Consultorios', icono: DoorClosed,
      contenido: <ConsultoriosCard />,
    },
    {
      clave: 'prestaciones', label: 'Prestaciones', icono: Stethoscope,
      contenido: <PrestacionesCard />,
    },
    {
      clave: 'profesionales', label: 'Profesionales', icono: CalendarClock,
      contenido: <ProfesionalesCard />,
    },
  ],
})
