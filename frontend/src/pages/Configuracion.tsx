/** Configuración de MedLibra (ítem 5, 2026-08-05).
 *
 *  Hasta hoy este producto **no tenía ninguna pantalla de configuración**: los
 *  datos del consultorio no se podían cargar, el logo no se podía subir, el
 *  SMTP sólo entraba por el backoffice de la suite y el backup era
 *  exclusivamente por CLI.
 *
 *  El armado y las secciones vienen de `libra-ui/Configuracion`; acá se declara
 *  **lo que corresponde a este producto**. MedLibra factura (ARCA) pero no
 *  imprime tickets de comanda ni usa balanza.
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
 *
 *  Los endpoints existían; lo que faltaba era la pantalla. Sin ella un
 *  consultorio nuevo no podía parametrizar nada: ni sus salas, ni sus
 *  prestaciones, ni la jornada de quien atiende.
 */
import {
  SECCIONES_BASE, SECCION_ARCA, createConfiguracion,
} from 'libra-ui/Configuracion'
import { CalendarClock, DoorClosed, MapPin, Settings, Stethoscope } from 'lucide-react'
import { SedesCard } from './configuracion/sedes'
import { ConsultoriosCard } from './configuracion/consultorios'
import { PrestacionesCard } from './configuracion/prestaciones'
import { ProfesionalesCard } from './configuracion/profesionales'

export const Configuracion = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: Settings,
  // empresa (+logo), correo (SMTP) y Datos / Backup, más la agenda y ARCA.
  //
  // 🔴 El ORDEN es el del arranque de un consultorio nuevo: dónde se atiende,
  // en qué sala, qué se hace y quién lo hace. Al revés, un consultorio se carga
  // sin sede a la cual pertenecer, una prestación sin poder ponerle precio (el
  // precio es por sede) y un bloque de agenda sin consultorio donde ubicarlo —
  // que es el único campo que no se puede dejar vacío.
  secciones: [
    ...SECCIONES_BASE,
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
    SECCION_ARCA,
  ],
})
