// El icono del título es el que el sidebar le da a esa misma pantalla.
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una
// pantalla se rompa —ninguna se rompe con el icono equivocado— sino que
// **vuelvan a divergir**: eso se ve cruzando el mapa de navegación contra cada
// pantalla, y sólo si alguien se acuerda de cruzar. El motor vive en
// `libra-ui/auditoria-de-titulos` y tiene sus propios tests allá.
//
// ⚠️ **Lo que este guard NO cubre**: las pantallas que `libra-ui` rinde enteras
// —`/usuarios`, `/logs` y `/configuracion`—, porque no viven en `pages/` de
// este producto. A ésas las cubre el TIPO: desde la v0.34.0 el `icono` es una
// prop requerida, así que el compilador no deja montarlas sin pasarlo.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarTitulos, describirDesajustes } from 'libra-ui/auditoria-de-titulos'

const SRC = join(process.cwd(), 'src')

describe('el icono del título sale del sidebar', () => {
  it('🔴 ninguna pantalla usa un icono distinto al de su entrada del menú', () => {
    expect(describirDesajustes(auditarTitulos(SRC).distinto)).toEqual([])
  })

  it('🔴 ninguna pantalla del menú tiene el título sin icono', () => {
    expect(describirDesajustes(auditarTitulos(SRC).sinIcono)).toEqual([])
  })

  it('🔴 el control — el guard midió algo', () => {
    // Sin esto, los dos casos de arriba pasarían en verde si el parser dejara
    // de encontrar el Layout, el router o las pantallas: dos listas vacías
    // contra dos listas vacías. Es la forma en que este guard falló mientras se
    // escribía.
    //
    // ⚠️ **Es un piso de "midió algo", no una meta de cobertura.** Estaba en 7
    // —los ítems que había el día que se escribió— y al sacar Facturación del
    // menú (2026-08-22, ADR-034) se puso en rojo con 6: el guard no encontró
    // nada raro, encontró un ítem menos. Un número calcado de la foto del día
    // convierte cada baja legítima en un rojo que no dice nada. Baja a 5, que
    // sigue siendo mucho más que cero y deja margen para una baja más sin que
    // el control pierda sentido.
    const { rutasDelNav, pantallas, conIcono } = auditarTitulos(SRC)
    expect(rutasDelNav).toBeGreaterThanOrEqual(5)
    expect(pantallas).toBeGreaterThanOrEqual(5)
    expect(conIcono).toBeGreaterThan(0)
  })
})
