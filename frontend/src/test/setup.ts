import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// 🔴 `waitFor`/`findBy*` esperan **1 segundo** por defecto, y eso alcanza sólo
// mientras la máquina no esté cargada. Medido el 2026-08-24: en la corrida
// inmediatamente posterior a un `npm ci` —con el transform tardando 9 s en vez
// de 2,6— se cayeron dos tests del calendario que en las tres corridas
// siguientes pasaron sin tocar una línea. El primer render de esas pantallas
// pide cuatro endpoints y monta una grilla; con jsdom y el CI compartido, un
// segundo es un margen que a veces no está.
//
// Se sube el margen en vez de convivir con el flake: un rojo intermitente
// enseña a re-correr el CI hasta que salga verde, que es exactamente el hábito
// que vuelve inútil al CI. Cinco segundos no hacen más lenta ninguna corrida
// sana — el `waitFor` corta apenas la condición se cumple.
configure({ asyncUtilTimeout: 5000 })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom no implementa estas tres APIs y los componentes de shadcn (que
// usan Radix por debajo) las tocan al montar. Sin los polyfills, cualquier
// pantalla con un Select o un Dialog revienta con un TypeError que no
// tiene nada que ver con lo que se esta probando.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }),
  })
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}

// jsdom NO tiene motor de layout: implementa `document.createRange()` pero
// el Range que devuelve no trae `getBoundingClientRect`. El `data-table`
// de libra-ui mide ahi el ancho de la columna de acciones y revienta con
// un TypeError en un layout effect.
//
// Se pone un polyfill en vez de tocar libra-ui: en jsdom cualquier medicion
// da cero igual, asi que saltearla en el componente daria exactamente el
// mismo resultado, pero cambiando codigo compartido por seis productos para
// acomodar al entorno de tests.
if (typeof Range !== 'undefined' && !Range.prototype.getBoundingClientRect) {
  const cero = () => ({
    x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0,
    toJSON: () => ({}),
  }) as DOMRect
  Range.prototype.getBoundingClientRect = cero
  Range.prototype.getClientRects = () => Object.assign([], { item: () => null }) as unknown as DOMRectList
}

// El `Select` de Radix usa las APIs de captura de puntero, que jsdom no
// implementa: sin esto, abrirlo desde un test tira `hasPointerCapture is not a
// function` y no despliega ninguna opción, así que el `getByRole('option')`
// falla — y se lee como un defecto de la pantalla, que no lo es. Mismo criterio
// que `scrollIntoView` de acá arriba: en un navegador de verdad existen.
//
// Hasta hoy este producto no lo tenía —lo agregó Gestiolibra al escribir sus
// propias pantallas de configuración— y no se notaba porque ningún test de acá
// abría un `Select`.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.setPointerCapture = () => {}
  Element.prototype.releasePointerCapture = () => {}
}
