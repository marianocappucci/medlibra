/** La carga de la agenda, una sola vez para las tres vistas.
 *
 *  **Una llamada por profesional, en paralelo, con el rango entero.** El
 *  endpoint es por recurso porque la validación de choques también lo es
 *  (`app/services/appointments.py`), pero acepta un rango de días: la semana
 *  es **una** llamada por profesional, no siete de un día. Con la cantidad de
 *  profesionales que tiene un consultorio —unos pocos— el fan-out por
 *  profesional sale más barato que sostener un segundo endpoint agregador que
 *  diga lo mismo; el fan-out por *día*, en cambio, multiplicaría por siete o
 *  por cuarenta y dos, y ése no se sostiene.
 *
 *  **El filtro de profesional no toca esto.** Se filtra al dibujar, no al
 *  pedir: si el fetch se recortara, el "+3 más" de la celda del mes pasaría a
 *  mentir en cuanto alguien elige un profesional.
 *
 *  🔴 **El día de un turno es el de la sede, no el del navegador.** La API
 *  devuelve instantes en UTC (`2026-07-21T00:30:00Z`); ese turno es el de las
 *  21:30 del **lunes** para quien atiende en Buenos Aires. Agrupar por el
 *  primer tramo del string lo pondría en la columna del martes, y agrupar con
 *  la zona del navegador pondría cada usuario el turno en un día distinto. Se
 *  agrupa por la hora de pared de la sede del profesional, que es la misma
 *  cuenta que hace el backend al filtrar (ver ADR-028).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { sumarDias } from 'libra-ui/agenda'
import { api, ApiError, type Appointment, type Branch, type Resource } from '../../api'

/** Un turno con el profesional que lo atiende pegado encima.
 *
 *  El endpoint es por profesional, así que la respuesta no lo repite adentro de
 *  cada fila — pero en cuanto los turnos de todos se mezclan en la celda de un
 *  día, saber de quién es cada uno deja de ser derivable. */
export type TurnoConProfesional = Appointment & {
  profesional_nombre: string
  /** Posición del profesional en la lista de activos: de acá sale su color. */
  profesional_indice: number
  /** El huso de la sede del profesional, para formatear sin volver a buscarlo. */
  zona: string
  /** `YYYY-MM-DDTHH:mm:ss` en hora de pared de la sede. Es lo que el
   *  calendario sabe leer: sus cálculos cortan el string, no construyen `Date`. */
  desde: string
  hasta: string
}

export type AgendaRango = {
  /** Los turnos de cada día, `YYYY-MM-DD` → lista ordenada por hora. */
  porDia: Record<string, TurnoConProfesional[]>
  cargando: boolean
  error: string | null
  recargar: () => void
}

/** Un instante ISO como hora de pared de `zona`, en `YYYY-MM-DDTHH:mm:ss`.
 *
 *  Se arma por partes con `formatToParts` y no con `toLocaleString`: hace falta
 *  que respete el `timeZone` **y** que salga en un formato que se pueda cortar
 *  por posición, que es como el calendario lee las horas. */
export function enHoraDePared(iso: string, zona: string): string {
  const partes = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23', timeZone: zona,
  }).formatToParts(new Date(iso))
  const p: Record<string, string> = {}
  for (const parte of partes) p[parte.type] = parte.value
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`
}

/** El huso de la sede de cada profesional. `UTC` si no cuelga de ninguna, que
 *  es lo mismo que decide el backend (`husos.SIN_SUCURSAL`). */
export function zonaPorProfesional(
  profesionales: Resource[], sedes: Branch[],
): Record<string, string> {
  const porSede = Object.fromEntries(sedes.map((s) => [s.id, s.timezone]))
  return Object.fromEntries(profesionales.map((r) => [
    r.id, (r.branch_id && porSede[r.branch_id]) || 'UTC',
  ]))
}

export function useAgendaRango(
  profesionales: Resource[], sedes: Branch[], desde: string, dias: number,
): AgendaRango {
  const [porDia, setPorDia] = useState<Record<string, TurnoConProfesional[]>>({})
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // La clave del efecto es esta cadena y no el array: `profesionales` es un
  // objeto nuevo en cada render del padre, y usarlo como dependencia dispararía
  // el fan-out entero en cada tecla que se toque en la pantalla. Se serializa
  // con JSON y no con un `join` de separadores: un profesional que se llame
  // "Pérez | Ana" partiría la cadena y el fan-out pediría uno inventado.
  const clave = JSON.stringify(profesionales.map((r, i) => ({
    id: r.id, nombre: r.name, indice: i,
  })))
  const zonas = JSON.stringify(zonaPorProfesional(profesionales, sedes))

  // Marca de la carga en curso. Cambiar de semana mientras la anterior está en
  // vuelo deja dos respuestas compitiendo, y la vieja puede llegar última: sin
  // esto, la grilla termina mostrando el rango que el usuario ya dejó atrás.
  const enVuelo = useRef(0)

  const cargar = useCallback(async () => {
    const mio = ++enVuelo.current
    const lista: { id: string; nombre: string; indice: number }[] = JSON.parse(clave)
    const porProfesional: Record<string, string> = JSON.parse(zonas)

    if (lista.length === 0) {
      setPorDia({})
      return
    }
    setCargando(true)
    setError(null)
    // `dias - 1`: el endpoint toma los dos extremos inclusive, así que una
    // semana va de `desde` a `desde + 6`. Y el día de cada extremo es el de la
    // sede en las dos puntas —acá al agrupar y allá al filtrar (ADR-028)—, que
    // es lo que hace que el rango pedido y el dibujado sean el mismo.
    const hasta = sumarDias(desde, dias - 1)
    try {
      const respuestas = await Promise.all(lista.map((r) => api.get<Appointment[]>(
        `/resources/${r.id}/agenda?date_from=${desde}&date_to=${hasta}`,
      )))
      if (mio !== enVuelo.current) return

      const agrupado: Record<string, TurnoConProfesional[]> = {}
      respuestas.forEach((turnos, i) => {
        const r = lista[i]
        const zona = porProfesional[r.id] ?? 'UTC'
        for (const t of turnos ?? []) {
          const desdeLocal = enHoraDePared(t.starts_at, zona)
          const dia = desdeLocal.slice(0, 10)
          ;(agrupado[dia] ??= []).push({
            ...t,
            profesional_nombre: r.nombre,
            profesional_indice: r.indice,
            zona,
            desde: desdeLocal,
            hasta: enHoraDePared(t.ends_at, zona),
          })
        }
      })
      // Cada respuesta viene ordenada, pero la mezcla de varios profesionales
      // no: sin este sort, la columna del día lista la agenda entera de la
      // Dra. Vidal y recién después la del Dr. Molina, que no es un día.
      for (const dia of Object.keys(agrupado)) {
        agrupado[dia].sort((a, b) => a.desde.localeCompare(b.desde))
      }
      setPorDia(agrupado)
    } catch (err) {
      if (mio !== enVuelo.current) return
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
    } finally {
      if (mio === enVuelo.current) setCargando(false)
    }
  }, [clave, zonas, desde, dias])

  useEffect(() => { void cargar() }, [cargar])

  return { porDia, cargando, error, recargar: cargar }
}
