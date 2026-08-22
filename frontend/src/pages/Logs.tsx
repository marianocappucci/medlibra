// La pantalla vive en libra-ui (v0.12.0), igual que `Usuarios`.
//
// **Lo que se ve acá no incluye contenido clínico**: eso lo decide el backend
// (`app/auditoria.py`), no esta pantalla. La fila dice quién tocó qué ficha y
// cuándo, no qué dice la ficha.

import { ScrollText } from 'lucide-react'
import { Logs as Compartida } from 'libra-ui/Logs'

/** Ver el comentario de `Usuarios`: el icono es de este producto. */
export function Logs() {
  return <Compartida icono={ScrollText} />
}
