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

/** `12 min` o `1 h 05 min`. Pasada la hora se parte, porque "95 min" obliga a
 *  hacer la cuenta a quien está mirando el mostrador. */
export function describirEspera(minutos: number): string {
  if (minutos < 60) return `${minutos} min`
  const horas = Math.floor(minutos / 60)
  const resto = minutos % 60
  return `${horas} h ${String(resto).padStart(2, '0')} min`
}
