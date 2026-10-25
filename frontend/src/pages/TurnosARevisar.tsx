/** Los turnos que se atendieron sin conexión y en la web cambiaron mientras tanto (libra-ui ADR-095, ADR-045 de este producto).
 *
 *  Decisión del humano (2026-10-25): lo que pasó en el mostrador no se borra. La atención y lo cobrado **valen**, y el turno queda
 *  acá para que alguien lo acomode (moverlo, cancelarlo, ver si se cobró dos veces). La lista es de LibraGenda (`turnos_a_revisar`);
 *  el panel y los textos son del kit. Esta pantalla sólo la pide, le pone el nombre del paciente y la prestación a cada tarjeta, y
 *  ofrece «Ya lo revisé» **en la web**: en la PC del consultorio la lista se ve pero la revisión es de la web (la tabla es del espejo).
 *
 *  «Ya lo revisé» **no cambia el turno ni la atención**: sólo lo saca de la lista. Acomodarlo se hace en la agenda, a mano.
 */
import { useEffect, useState } from 'react'
import { ClipboardCheck } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { TurnosARevisar as PanelDeTurnosARevisar } from 'libra-ui/TurnosARevisar'
import { useConexionDelNodo } from 'libra-ui/nodo-offline'
import type { TurnoARevisar } from 'libra-ui/turnos-del-nodo'
import { ApiError, api, type AtencionARevisarDelTurno } from '../api'
import { enHoraDePared } from '@/components/agenda/datos'
import { diaMesYHora } from '@/lib/fechas'

export function TurnosARevisar() {
  const [filas, setFilas] = useState<AtencionARevisarDelTurno[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Cada vez que cambia, se vuelve a pedir la lista (después de marcar un turno como revisado).
  const [carga, setCarga] = useState(0)
  // Revisar es del central: en la PC del consultorio la tabla es del espejo y la API contesta 409. Sin el botón, la lista es de consulta.
  const { esNodo } = useConexionDelNodo()

  useEffect(() => {
    let vigente = true
    api.get<AtencionARevisarDelTurno[]>('/turnos-a-revisar')
      .then((datos) => {
        if (!vigente) return
        setFilas(Array.isArray(datos) ? datos : [])
        setError(null)
      })
      .catch((err) => {
        if (vigente) setError(err instanceof ApiError ? err.detail : 'No se pudo cargar la lista. Probá de nuevo.')
      })
    return () => { vigente = false }
  }, [carga])

  async function marcarRevisado(turno: TurnoARevisar) {
    // El turno entero: una fila por atención (en curso, y después atendido), todas se marcan.
    await api.post('/turnos-a-revisar/revisadas', { atenciones: turno.atenciones.map((a) => a.atencion_id) })
    setCarga((n) => n + 1)
  }

  /** «Ana Gómez · Consulta · 20-07 10:00»: de quién es el turno, con lo que la API sabe de él (las atenciones traen los mismos datos). */
  function describir(turno: TurnoARevisar): string {
    const fila = turno.ultima as AtencionARevisarDelTurno
    const cuando = fila.starts_at ? diaMesYHora(enHoraDePared(fila.starts_at, fila.zona ?? 'UTC')) : null
    const partes = [fila.paciente, fila.servicio, cuando].filter(Boolean)
    return partes.length > 0 ? partes.join(' · ') : 'Turno que ya no existe'
  }

  return (
    <div className="grid gap-4">
      <TituloPantalla icono={ClipboardCheck}>Turnos a revisar</TituloPantalla>
      <PanelDeTurnosARevisar
        atenciones={filas}
        cargando={filas === null && error === null}
        error={error}
        describirTurno={describir}
        onMarcarRevisado={esNodo ? undefined : marcarRevisado}
        titulo={null}
      />
    </div>
  )
}
