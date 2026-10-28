/**
 * Cuánto hace que alguien espera en la fila de demanda espontánea.
 *
 * Es la única cuenta de fechas de esa pantalla que se hace con `Date`, y es a
 * propósito: la llegada es un **instante** (viene en UTC, `...Z`) y "ahora"
 * también, así que la diferencia no depende de ningún huso. El formato de la
 * hora de llegada, en cambio, sí depende —de la sede— y ése va por
 * `lib/fechas`.
 */

/** Minutos enteros entre la llegada y `ahora` (ms desde epoch). Nunca negativo:
 *  un reloj del navegador atrasado respecto del servidor no puede mostrar que
 *  alguien espera "-2 min". */
export function minutosDeEspera(llegada: string, ahora: number): number {
  const desde = Date.parse(llegada)
  if (Number.isNaN(desde)) return 0
  return Math.max(0, Math.floor((ahora - desde) / 60_000))
}

/** Minutos enteros entre dos instantes ISO (`desde` → `hasta`). Nunca negativo: dos relojes (la PC del consultorio
 *  y el servidor) pueden no coincidir al segundo y una espera de «-1 min» no existe. */
export function minutosEntre(desde: string, hasta: string): number {
  const a = Date.parse(desde)
  const b = Date.parse(hasta)
  if (Number.isNaN(a) || Number.isNaN(b)) return 0
  return Math.max(0, Math.floor((b - a) / 60_000))
}

/** Lo que esperó alguien **hasta que lo llamaron** (ADR-048): `called_at - created_at`. `null` si no se sabe —todavía
 *  espera, se sacó de la fila sin llamarlo, o se lo llamó antes de que se guardara ese dato—: nunca se inventa con
 *  «ahora», que crece sola y no mide nada. */
export function esperaHastaLlamada(l: { created_at: string; called_at?: string | null }): number | null {
  return l.called_at ? minutosEntre(l.created_at, l.called_at) : null
}

/** El promedio de varias esperas, en minutos enteros; `null` si no hay ninguna que promediar. */
export function promedioDeEspera(minutos: number[]): number | null {
  if (minutos.length === 0) return null
  return Math.round(minutos.reduce((a, b) => a + b, 0) / minutos.length)
}

/** `12 min` o `1 h 05 min`. Pasada la hora se parte, porque "95 min" obliga a
 *  hacer la cuenta a quien está mirando el mostrador. */
export function describirEspera(minutos: number): string {
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  const resto = minutos % 60
  return `${horas} h ${String(resto).padStart(2, '0')} min`
}
