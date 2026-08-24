/** El día: la rejilla horaria con **una columna por profesional**.
 *
 *  Es el patrón de Google Calendar cuando se miran varios calendarios a la vez,
 *  y acá es además lo que la pantalla tiene que contestar: al entrar a un día ya
 *  se sabe *cuándo* —lo dijeron la semana y el mes—, y lo que falta es **quién
 *  atiende a quién y en qué hueco entra el próximo**. Mezclados en una sola
 *  columna, buscar el hueco de la Dra. Vidal obligaría a pescar sus turnos
 *  entre los de los demás.
 *
 *  Vive en el producto y no en `libra-ui/agenda` por el encabezado: qué se dice
 *  de un carril es lo más específico de cada agenda (en LibraDesk, la patente
 *  del vehículo y el botón de la hoja de ruta; acá, la sede del profesional).
 *  La rejilla, el reparto de ancho y los colores sí vienen del paquete.
 */
import { RejillaHoraria, type ColumnaRejilla } from 'libra-ui/agenda'
import { Card, CardContent } from '@/components/ui/card'
import type { Resource } from '../../api'
import type { ArmarEvento } from './eventos'
import type { TurnoConProfesional } from './datos'

export function VistaDia({ profesionales, turnos, esHoy, comoEvento, nombreSede }: {
  profesionales: Resource[]
  turnos: TurnoConProfesional[]
  /** Si el día que se muestra es hoy: la rejilla dibuja la línea de la hora
   *  actual sólo entonces. */
  esHoy: boolean
  comoEvento: ArmarEvento
  nombreSede: (branchId: string | null) => string | null
}) {
  if (profesionales.length === 0) {
    return (
      <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
        No hay profesionales activos para agendar.
      </CardContent></Card>
    )
  }

  const columnas: ColumnaRejilla[] = profesionales.map((r) => {
    const sede = nombreSede(r.branch_id)
    return {
      clave: r.id,
      // Todas las columnas llevan la línea de "ahora" cuando el día es hoy: son
      // profesionales del mismo día, no días distintos.
      esHoy,
      encabezado: (
        <div className="grid gap-0.5">
          <span className="truncate text-sm font-medium">{r.name}</span>
          {sede && (
            <span className="truncate text-[11px] text-muted-foreground">{sede}</span>
          )}
        </div>
      ),
      eventos: turnos.filter((t) => t.resource_id === r.id).map(comoEvento),
    }
  })

  return <RejillaHoraria columnas={columnas} />
}
