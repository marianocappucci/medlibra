// Shim sobre libra-ui/Usuarios (extraído 2026-07-26, era byte-idéntico en
// Gestiolibra/MedLibra/VentaLibra -- ver
// wiki/analyses/auditoria-duplicacion-familia-libra.md).
//
// `permitirEliminar` pasa a `true` (libra-ui v0.71.0) porque el backend ya
// no es el router propio: es `build_users_router()` de libraauth v0.43.0
// (ADR-018), que trae el `DELETE /users/{id}` con las guardas del único
// admin y de uno mismo -- ver `app/routers/users.py`. Subir el pin de
// libra-ui sin esto no hubiera cambiado nada (el default es `false`), pero
// dejar el botón apagado con un backend que ya lo atiende sería no adoptar
// la mitad de la migración.
//
// `usuarioActualId` sale del contexto de auth: oculta el botón en la fila
// propia, que el backend rechaza igual pero mejor no ofrecer.

import { UserCog } from 'lucide-react'
import { Usuarios as Compartida } from 'libra-ui/Usuarios'
import { useAuth } from '../context/AuthContext'

/** El icono se pasa acá y no en el router: es un dato de ESTE producto —el que
 *  su propio sidebar le da a `/usuarios`— y el paquete no puede saberlo. */
export function Usuarios() {
  const { user } = useAuth()
  return <Compartida icono={UserCog} permitirEliminar usuarioActualId={user?.id} />
}
