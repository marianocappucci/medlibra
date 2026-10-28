/** Avisos: por dónde le escribe el consultorio al paciente, y qué salió (ADR-049 de MedLibra, ADR-090 de libracore, ADR-097 del kit).
 *
 *  Las dos piezas vienen de `libra-ui` y hablan con `/api/avisos`, que monta el backend detrás del guard de admin. Lo único que es de
 *  este producto es **dónde viven**: una sección de Configuración, que ya es sólo de admin.
 *
 *  🔴 **El registro muestra el destino entero porque quien mira es admin.** `esAdmin` es verdad *por construcción*: esta sección sólo
 *  se monta en Configuración, que el menú y el backend limitan al administrador. Si un día se monta en otra pantalla, esa prop se
 *  decide con el rol de quien mira, y sin ella el kit enmascara el teléfono y el mail (`••••••••1234`).
 *
 *  🔴 **Los avisos no llevan datos de salud**: ni la prestación ni nada clínico (Ley 25.326 y 26.529). Lo que el registro muestra
 *  como texto es lo mismo que le llegó al paciente: sede, profesional, consultorio, fecha, hora y dirección.
 */
import { ConfiguracionDeAvisos } from 'libra-ui/ConfiguracionDeAvisos'
import { RegistroDeAvisos } from 'libra-ui/RegistroDeAvisos'

export function AvisosCard() {
  return (
    <div className="space-y-6">
      <ConfiguracionDeAvisos />
      {/* El `tipo` que manda el backend (`recordatorio`) el kit ya lo muestra legible («Recordatorio»): no hace falta un diccionario. */}
      <RegistroDeAvisos esAdmin />
    </div>
  )
}
