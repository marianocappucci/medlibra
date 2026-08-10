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
 */
import {
  SECCIONES_BASE, SECCION_ARCA, createConfiguracion,
} from 'libra-ui/Configuracion'

export const Configuracion = createConfiguracion({
  // empresa (+logo), correo (SMTP) y Datos / Backup, más ARCA.
  secciones: [...SECCIONES_BASE, SECCION_ARCA],
})
