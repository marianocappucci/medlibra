// Lo puro de la costura con LibraView (ADR-050), aparte del componente para poder probarlo sin montar nada.
import type { PracticaLibraView } from '../api'

/** Sin mayúsculas, sin acentos y sin espacios de más: «Radiografía de Tórax » = «radiografia de torax». */
export function normalizar(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim()
}

/** La práctica del catálogo que corresponde al texto libre del ítem, o `''` si ninguna coincide exactamente (por nombre o por código). */
export function practicaSugerida(studyType: string, catalogo: PracticaLibraView[]): string {
  const buscado = normalizar(studyType)
  if (!buscado) return ''
  const hallada = catalogo.find((p) => normalizar(p.nombre) === buscado || normalizar(p.codigo) === buscado)
  return hallada?.codigo ?? ''
}

/** «Ficticia, Ana María» → apellido y nombres. Sin coma no se adivina (no se sabe dónde termina el apellido): quedan vacíos para completar. */
export function partirNombre(nombre: string): { apellido: string; nombres: string; partido: boolean } {
  const coma = nombre.indexOf(',')
  if (coma < 0) return { apellido: '', nombres: '', partido: false }
  return { apellido: nombre.slice(0, coma).trim(), nombres: nombre.slice(coma + 1).trim(), partido: true }
}
