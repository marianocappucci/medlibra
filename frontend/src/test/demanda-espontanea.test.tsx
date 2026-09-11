// La pantalla que opera la fila de demanda espontánea (ADR-038).
//
// Lo barato sería probar que la lista se dibuja. Lo que se prueba es lo que la
// haría mentir: la hora de llegada en el huso equivocado, "quién sigue" leído
// del número en vez del estado, un botón que el backend rechaza siempre, o una
// llegada anotada en el día del reloj en vez del de la pantalla.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DemandaEspontanea } from '../pages/DemandaEspontanea'
import { describirEspera, minutosDeEspera } from '../lib/espera'

const DIA = '2026-07-20'
const BLOQUE = {
  id: 'b1', resource_id: 'dr-molina', profesional: 'Dr. Molina',
  consultorio_id: 'cons-1', consultorio: 'Consultorio 1',
  starts_at: '09:00:00', ends_at: '13:00:00',
  timezone: 'America/Argentina/Buenos_Aires',
}
const PACIENTES = ['Ana Prueba', 'Beto Prueba', 'Carla Prueba'].map((name, i) => ({
  id: `p-${i + 1}`, name, phone: null, email: null, active: true,
  dni: null, birth_date: null, cuit: null, condicion_iva: null,
}))
const PRESTACIONES = [{ id: 'consulta', name: 'Consulta' }]

/** Llegó a las 12:05 UTC = 09:05 en Buenos Aires. */
function llegada(n: number, cambios: Record<string, unknown> = {}) {
  return {
    id: `w${n}`, block_id: 'b1', day: DIA, client_id: `p-${n}`,
    service_id: 'consulta', arrival_order: n, status: 'waiting',
    created_at: '2026-07-20T12:05:00Z', ...cambios,
  }
}

const FILA = `/agenda-blocks/b1/walkins?day=${DIA}`

let fetchMock: ReturnType<typeof vi.fn>
let pedidos: { url: string; metodo: string; cuerpo: unknown }[]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

/** Rutas EXACTAS, como en `configuracion-agenda.test.tsx`: con `includes`, la
 *  fila caería en la clave de los bloques y el test mediría otra cosa. */
function servir(rutas: Record<string, unknown>) {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url)
    pedidos.push({
      url: u,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : null,
    })
    return Promise.resolve(json(rutas[u] ?? []))
  })
}

function rutas(fila: unknown[], bloque: object = BLOQUE) {
  return {
    '/patients': PACIENTES,
    '/walkins/prestaciones': PRESTACIONES,
    [`/walkins/bloques?day=${DIA}`]: [bloque],
    [FILA]: fila,
  }
}

function montar() {
  return render(
    <MemoryRouter initialEntries={[`/demanda-espontanea?dia=${DIA}`]}>
      <DemandaEspontanea />
    </MemoryRouter>,
  )
}

function mandado(url: string, metodo = 'POST') {
  return pedidos.find((p) => p.url === url && p.metodo === metodo)
}

async function filaDe(nombre: string) {
  return (await screen.findByText(nombre)).closest('tr') as HTMLElement
}

beforeEach(() => {
  fetchMock = vi.fn()
  pedidos = []
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('la fila', () => {
  it('sale en orden de llegada, con la hora en dd-mm-aaaa HH:MM', async () => {
    servir(rutas([llegada(1), llegada(2), llegada(3)]))
    montar()
    await screen.findByText('Carla Prueba')
    const nombres = screen.getAllByRole('row').slice(1)
      .map((r) => within(r).getAllByRole('cell')[1].textContent)
    expect(nombres.map((n) => n?.replace('Sigue', ''))).toEqual([
      'Ana Prueba', 'Beto Prueba', 'Carla Prueba',
    ])
    expect(within(await filaDe('Ana Prueba')).getByText('20-07-2026 09:05')).toBeInTheDocument()
  })

  it('🔴 la hora de llegada es la de la SEDE, no la de Argentina', async () => {
    // Con una sede en Buenos Aires las dos cuentas dan lo mismo, y un
    // formateo que ignore la sede pasaría. En Ciudad de México (UTC-6) las
    // 12:05 UTC son las 06:05.
    servir(rutas([llegada(1)], { ...BLOQUE, timezone: 'America/Mexico_City' }))
    montar()
    const fila = await filaDe('Ana Prueba')
    expect(within(fila).getByText('20-07-2026 06:05')).toBeInTheDocument()
    expect(within(fila).queryByText('20-07-2026 09:05')).not.toBeInTheDocument()
  })

  it('🔴 "Sigue" es el primero que espera, no el N° 1', async () => {
    // El número es histórico (ADR-031): con el 1 fuera de la fila y el 2 en
    // atención, el que sigue es el 3.
    servir(rutas([
      llegada(1, { status: 'cancelled' }),
      llegada(2, { status: 'in_progress' }),
      llegada(3),
    ]))
    montar()
    expect(within(await filaDe('Carla Prueba')).getByText('Sigue')).toBeInTheDocument()
    expect(screen.getAllByText('Sigue')).toHaveLength(1)
  })

  it('sin bloques ese día lo dice, con la fecha en dd-mm-aaaa', async () => {
    servir({ ...rutas([]), [`/walkins/bloques?day=${DIA}`]: [] })
    montar()
    expect(await screen.findByText(/no hay ningún bloque de demanda espontánea/))
      .toHaveTextContent('20-07-2026')
  })

  it('cambiar el día pide los bloques de ESE día', async () => {
    servir(rutas([]))
    montar()
    await screen.findByText('Todavía no llegó nadie.')
    fireEvent.change(screen.getByLabelText('Día'), { target: { value: '2026-07-27' } })
    await waitFor(() => expect(mandado('/walkins/bloques?day=2026-07-27', 'GET')).toBeTruthy())
  })

  it('los selectores tienen nombre accesible', async () => {
    servir(rutas([]))
    montar()
    expect(await screen.findByRole('combobox', { name: 'Paciente' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Prestación' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Bloque' })).toBeInTheDocument()
  })
})

describe('anotar una llegada', () => {
  it('🔴 manda paciente, prestación y el día de la PANTALLA', async () => {
    // El día que se está mirando es 2026-07-20; el reloj de la máquina que
    // corre esto, no. Si el alta usara "hoy", la llegada caería en otra fila.
    servir(rutas([]))
    montar()
    await userEvent.click(await screen.findByRole('combobox', { name: 'Paciente' }))
    await userEvent.click(await screen.findByRole('option', { name: /Beto Prueba/ }))
    await userEvent.click(screen.getByRole('combobox', { name: 'Prestación' }))
    await userEvent.click(await screen.findByRole('option', { name: /Consulta/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Anotar llegada' }))

    await waitFor(() => expect(mandado('/agenda-blocks/b1/walkins')).toBeTruthy())
    expect(mandado('/agenda-blocks/b1/walkins')!.cuerpo).toEqual({
      client_id: 'p-2', service_id: 'consulta', day: DIA,
    })
  })

  it('el control — sin paciente no manda nada', async () => {
    servir(rutas([]))
    montar()
    await userEvent.click(await screen.findByRole('button', { name: 'Anotar llegada' }))
    expect(await screen.findByText('Elegí un paciente')).toBeInTheDocument()
    expect(mandado('/agenda-blocks/b1/walkins')).toBeUndefined()
  })
})

describe('hacer avanzar la fila', () => {
  it('🔴 cada estado ofrece sólo lo que el backend acepta', async () => {
    servir(rutas([
      llegada(1, { status: 'completed' }),
      llegada(2, { status: 'in_progress' }),
      llegada(3),
    ]))
    montar()
    const esperando = within(await filaDe('Carla Prueba'))
    expect(esperando.getByRole('button', { name: 'Llamar' })).toBeInTheDocument()
    expect(esperando.queryByRole('button', { name: 'Atendido' })).not.toBeInTheDocument()

    const enAtencion = within(await filaDe('Beto Prueba'))
    expect(enAtencion.getByRole('button', { name: 'Atendido' })).toBeInTheDocument()
    expect(enAtencion.queryByRole('button', { name: 'Llamar' })).not.toBeInTheDocument()

    // Un atendido no vuelve a la fila: ningún botón.
    expect(within(await filaDe('Ana Prueba')).queryAllByRole('button')).toHaveLength(0)
  })

  it('llamar manda la acción de ESA llegada', async () => {
    servir(rutas([llegada(1), llegada(2)]))
    montar()
    await userEvent.click(
      within(await filaDe('Beto Prueba')).getByRole('button', { name: 'Llamar' }),
    )
    await waitFor(() => expect(mandado('/walkins/w2/llamar')).toBeTruthy())
    expect(mandado('/walkins/w1/llamar')).toBeUndefined()
  })

  it('sacar de la fila usa cancelar, que conserva el número', async () => {
    servir(rutas([llegada(1)]))
    montar()
    await userEvent.click(
      within(await filaDe('Ana Prueba')).getByRole('button', { name: 'Sacar de la fila' }),
    )
    await waitFor(() => expect(mandado('/walkins/w1/cancelar')).toBeTruthy())
  })
})

describe('la espera', () => {
  it('se cuenta en minutos entre dos instantes, y pasada la hora se parte', () => {
    const ahora = Date.parse('2026-07-20T12:17:30Z')
    expect(minutosDeEspera('2026-07-20T12:05:00Z', ahora)).toBe(12)
    expect(describirEspera(12)).toBe('12 min')
    expect(describirEspera(65)).toBe('1 h 05 min')
    // Un reloj del navegador atrasado no muestra una espera negativa.
    expect(minutosDeEspera('2026-07-20T12:20:00Z', ahora)).toBe(0)
  })

  it('🔴 se ve sólo para quien espera', async () => {
    // Sin la hora en que lo llamaron, "cuánto esperó" el ya atendido sería la
    // cuenta hasta ahora, que crece sola y no mide nada.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-07-20T12:17:00Z'))
    servir(rutas([llegada(1, { status: 'completed' }), llegada(2)]))
    montar()
    expect(within(await filaDe('Beto Prueba')).getByText('12 min')).toBeInTheDocument()
    expect(within(await filaDe('Ana Prueba')).queryByText(/min$/)).not.toBeInTheDocument()
  })
})
