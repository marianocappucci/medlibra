// La sección «Avisos» de Configuración (ADR-049 de MedLibra; las piezas son de libra-ui ADR-097, y tienen sus propios tests allá).
//
// Lo que se prueba acá es lo único que es de este producto: que la sección **está** (y dónde), que habla con `/api/avisos`, que el
// administrador ve el destino entero y que el `tipo` que manda el backend se ve legible.
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Configuracion } from '../pages/Configuracion'

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
}

const ENVIO = {
  id: 1, canal: 'whatsapp', clave: 'agenda:t-1:24h', tipo: 'recordatorio', destino: '5491155551234', asunto: 'Recordatorio de turno',
  cuerpo: '*Recordatorio de turno*', plantilla: '', variables: {}, proveedor: 'registro', estado: 'registrado', intentos: 1,
  detalle: '', id_externo: '', enviado_at: '', created_at: '2026-10-28 10:00:00', updated_at: '2026-10-28 10:00:00',
}

let pedidos: string[]

beforeEach(() => {
  pedidos = []
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    pedidos.push(u)
    if (u.includes('/logo')) return Promise.resolve(new Response('', { status: 404 }))
    if (u.includes('/api/avisos/config')) {
      return Promise.resolve(json({
        whatsapp: {
          modo: 'registro', modos: ['apagado', 'registro', 'evolution'], url: '', instancia: '', apikey_cargada: false,
          disponible: true, motivo: '',
        },
        email: { disponible: false },
      }))
    }
    if (u.includes('/api/avisos/envios')) return Promise.resolve(json([ENVIO]))
    return Promise.resolve(json([]))
  }))
})

const montar = (ruta = '/configuracion?seccion=avisos') =>
  render(<MemoryRouter initialEntries={[ruta]}><Configuracion /></MemoryRouter>)

describe('la sección Avisos de Configuración', () => {
  it('🔴 está entre las pestañas, después de Profesionales y antes de Datos / Backup', async () => {
    montar()

    const pestanias = (await screen.findAllByRole('tab')).map((t) => t.textContent)
    expect(pestanias).toContain('Avisos')
    expect(pestanias.indexOf('Avisos')).toBe(pestanias.indexOf('Profesionales') + 1)
    expect(pestanias.at(-1)).toBe('Datos / Backup')
  })

  it('muestra la configuración y el registro, y los pide a /api/avisos', async () => {
    montar()

    expect(await screen.findByText('Avisos por WhatsApp y por mail')).toBeInTheDocument()
    expect(await screen.findByText('Registro de avisos')).toBeInTheDocument()
    expect(pedidos.some((u) => u.endsWith('/api/avisos/config'))).toBe(true)
    expect(pedidos.some((u) => u.includes('/api/avisos/envios'))).toBe(true)
  })

  it('🔴 el administrador ve el destino entero, no enmascarado', async () => {
    montar()

    const registro = (await screen.findByText('Registro de avisos')).closest('[data-slot="card"], div') as HTMLElement
    // El kit enmascara (`••••••••1234`) cuando no recibe `esAdmin`: acá la sección sólo la ve un admin y se lo pasa.
    expect((await screen.findAllByText('5491155551234')).length).toBeGreaterThan(0)
    expect(within(document.body).queryByText(/••••/)).toBeNull()
    expect(registro).toBeTruthy()
  })

  it('el tipo de aviso se ve legible: «Recordatorio», no `recordatorio`', async () => {
    montar()

    expect((await screen.findAllByText('Recordatorio')).length).toBeGreaterThan(0)
    expect(screen.queryByText('recordatorio')).toBeNull()
  })
})
