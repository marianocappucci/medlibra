// La agenda como calendario.
//
// 🔴 **Lo que más se mide acá es en qué día cae cada turno**, y no es un
// detalle de presentación: la API devuelve instantes en UTC y el día al que
// pertenecen es el del calendario de la sede. Un turno de las 21:30 del lunes
// en Buenos Aires es `2026-07-21T00:30:00Z` — martes en UTC. Si la pantalla
// agrupa por el string crudo, ese turno aparece en la columna del martes y
// quien atiende no lo ve el lunes. Es el mismo defecto que se arregló en el
// backend (ADR-028), del otro lado del cable.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Agenda } from '../pages/Agenda'

const LUNES = '2026-07-20'
const MARTES = '2026-07-21'

const SEDE = {
  id: 'centro', name: 'Consultorio Centro', active: true,
  timezone: 'America/Argentina/Buenos_Aires', phone: null, address: null,
}
const PROFESIONAL = { id: 'dr-molina', name: 'Dr. Molina', branch_id: 'centro', active: true }
const OTRO_PROFESIONAL = { id: 'dra-vidal', name: 'Dra. Vidal', branch_id: 'centro', active: true }
const PRESTACION = { id: 'consulta', name: 'Consulta', duration_minutes: 30, active: true }
const PACIENTE = {
  id: 'ana', name: 'Ana Gómez', phone: null, email: null, active: true, dni: '30111222',
}

/** Un turno de las 21:30 del lunes en UTC-3: en UTC es el martes 00:30. */
const DE_NOCHE = {
  id: 't-noche', resource_id: 'dr-molina', service_id: 'consulta', client_id: 'ana',
  starts_at: '2026-07-21T00:30:00Z', ends_at: '2026-07-21T01:00:00Z',
  status: 'confirmed',
}

/** Uno de las 10:00 del lunes, que en UTC sigue cayendo el lunes. */
const DE_MANANA = {
  id: 't-manana', resource_id: 'dr-molina', service_id: 'consulta', client_id: 'ana',
  starts_at: '2026-07-20T13:00:00Z', ends_at: '2026-07-20T13:30:00Z',
  status: 'pending',
}

/** Lo que sirve `GET /medios-pago`, que sale de `libracore.medios_pago`.
 *
 *  🔴 **La pantalla ya no declara esta lista.** Hasta el 2026-08-24 tenía
 *  cuatro medios escritos a mano en `Agenda.tsx`, y uno —`tarjeta`— no existía
 *  en el vocabulario de la familia: llegaba igual a Contalibra y salía en el
 *  cierre de caja como un bucket suelto con el nombre crudo. */
const MEDIOS_PAGO = [
  { id: 'efectivo', label: 'Efectivo' },
  { id: 'tarjeta_debito', label: 'Tarjeta de débito' },
  { id: 'mercadopago', label: 'Mercado Pago' },
]

let fetchMock: ReturnType<typeof vi.fn>
let pedidos: { url: string; metodo: string; cuerpo: unknown }[]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

function servir(turnos: unknown[], extra: Record<string, unknown> = {}) {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url)
    pedidos.push({
      url: u,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : null,
    })
    for (const [fragmento, respuesta] of Object.entries(extra)) {
      if (u.includes(fragmento)) return Promise.resolve(json(respuesta))
    }
    if (u.includes('/agenda?')) {
      // El endpoint es por profesional: sólo el Dr. Molina tiene turnos.
      return Promise.resolve(json(u.includes('/resources/dr-molina/') ? turnos : []))
    }
    if (u.includes('/medios-pago')) return Promise.resolve(json(MEDIOS_PAGO))
    if (u.includes('/resources')) return Promise.resolve(json([PROFESIONAL, OTRO_PROFESIONAL]))
    if (u.includes('/branches')) return Promise.resolve(json([SEDE]))
    if (u.includes('/services')) return Promise.resolve(json([PRESTACION]))
    if (u.includes('/patients')) return Promise.resolve(json([PACIENTE]))
    return Promise.resolve(json([]))
  })
}

/** Como `servir`, pero el POST de completar contesta 422 pidiendo el medio.
 *
 *  Es lo que hace el backend cuando el turno tiene saldo pendiente, y lo único
 *  que abre el diálogo del medio de pago. */
function conCompletarQuePideMedio(turnos: unknown[]) {
  return (url: string, init?: RequestInit) => {
    const u = String(url)
    pedidos.push({
      url: u,
      metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : null,
    })
    if (u.includes('/complete')) {
      return Promise.resolve(json({ detail: 'medio_pago requerido' }, 422))
    }
    if (u.includes('/medios-pago')) return Promise.resolve(json(MEDIOS_PAGO))
    if (u.includes('/agenda?')) {
      return Promise.resolve(json(u.includes('/resources/dr-molina/') ? turnos : []))
    }
    if (u.includes('/resources')) return Promise.resolve(json([PROFESIONAL, OTRO_PROFESIONAL]))
    if (u.includes('/branches')) return Promise.resolve(json([SEDE]))
    if (u.includes('/services')) return Promise.resolve(json([PRESTACION]))
    if (u.includes('/patients')) return Promise.resolve(json([PACIENTE]))
    return Promise.resolve(json([]))
  }
}

/** Espía de la URL, para afirmar sobre la navegación sin leer el DOM. */
let urlActual = ''
function EspiaDeUrl() {
  const location = useLocation()
  urlActual = `${location.pathname}${location.search}`
  return null
}

function montar(ruta = `/agenda?dia=${LUNES}`) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <EspiaDeUrl />
      <Routes>
        <Route path="/agenda" element={<Agenda />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  fetchMock = vi.fn()
  pedidos = []
  urlActual = ''
  vi.stubGlobal('fetch', fetchMock)
})

/** La columna de un día de la vista de semana. */
function columna(dia: string): HTMLElement {
  return document.querySelector(`[data-columna="${dia}"]`) as HTMLElement
}

describe('la agenda como calendario', () => {
  it('arranca en la semana y dibuja los siete días', async () => {
    servir([])
    montar()
    await waitFor(() => expect(document.querySelectorAll('[data-columna]')).toHaveLength(7))
    // La semana del lunes 20 de julio de 2026.
    expect(document.querySelectorAll('[data-columna]')[0].getAttribute('data-columna'))
      .toBe(LUNES)
  })

  it('🔴 un turno de la noche cae en el día de la SEDE, no en el de UTC', async () => {
    servir([DE_NOCHE])
    montar()
    await waitFor(() => expect(screen.getByText('Ana Gómez')).toBeInTheDocument())
    expect(within(columna(LUNES)).getByText('Ana Gómez')).toBeInTheDocument()
    expect(within(columna(MARTES)).queryByText('Ana Gómez')).not.toBeInTheDocument()
  })

  it('🔴 el control — la conversión no corre todos los turnos un día', async () => {
    // Sin este control, "restarle un día a todo" haría pasar al de arriba.
    servir([DE_MANANA])
    montar()
    await waitFor(() => expect(screen.getByText('Ana Gómez')).toBeInTheDocument())
    expect(within(columna(LUNES)).getByText('Ana Gómez')).toBeInTheDocument()
  })

  it('pide el rango entero de la semana, una llamada por profesional', async () => {
    servir([])
    montar()
    await waitFor(() => expect(document.querySelectorAll('[data-columna]')).toHaveLength(7))
    const deAgenda = pedidos.filter((p) => p.url.includes('/agenda?')).map((p) => p.url)
    expect(deAgenda).toEqual([
      `/resources/dr-molina/agenda?date_from=${LUNES}&date_to=2026-07-26`,
      `/resources/dra-vidal/agenda?date_from=${LUNES}&date_to=2026-07-26`,
    ])
  })

  it('la flecha de siguiente se mueve una semana', async () => {
    servir([])
    montar()
    await waitFor(() => expect(document.querySelectorAll('[data-columna]')).toHaveLength(7))
    await userEvent.click(screen.getByLabelText('Siguiente'))
    expect(urlActual).toContain('dia=2026-07-27')
  })

  it('🔴 abrir un turno lo pone en la URL y muestra su detalle', async () => {
    servir([DE_MANANA])
    montar()
    await waitFor(() => expect(screen.getByText('Ana Gómez')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Ana Gómez'))
    expect(urlActual).toContain('turno=t-manana')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('Consulta')).toBeInTheDocument()
    expect(within(dialogo).getByText('Dr. Molina')).toBeInTheDocument()
    // 10:00 de la sede, no 13:00 de UTC.
    expect(within(dialogo).getByText(/20-07 10:00/)).toBeInTheDocument()
  })

  it('un turno pendiente se puede confirmar desde su detalle', async () => {
    servir([DE_MANANA])
    montar(`/agenda?dia=${LUNES}&turno=t-manana`)
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(
      pedidos.some((p) => p.url === '/appointments/t-manana/confirm' && p.metodo === 'POST'),
    ).toBe(true))
  })

  it('🔴 un turno cancelado no lleva el color de su profesional', async () => {
    // Con el color del profesional se lee como un turno vivo y la columna diría
    // que está ocupado a esa hora cuando está libre.
    servir([{ ...DE_MANANA, status: 'cancelled' }])
    montar()
    const bloque = await screen.findByText('Ana Gómez')
    const enlace = bloque.closest('a') as HTMLElement
    expect(enlace.className).toContain('line-through')
    expect(enlace.className).not.toContain('bg-sky-100')
  })

  it('🔴 el control — un turno vivo SÍ lleva el color de su profesional', async () => {
    servir([DE_MANANA])
    montar()
    const bloque = await screen.findByText('Ana Gómez')
    expect((bloque.closest('a') as HTMLElement).className).toContain('bg-sky-100')
  })

  it('el alta manda el turno con la hora tal como se escribió', async () => {
    servir([])
    montar()
    await waitFor(() => expect(document.querySelectorAll('[data-columna]')).toHaveLength(7))
    await userEvent.click(screen.getByRole('button', { name: /Nuevo turno/ }))
    const dialogo = await screen.findByRole('dialog')

    // El horario viene prellenado con el día que se está mirando: quien abre el
    // alta parado en el lunes quiere un turno el lunes, no hoy.
    const horario = within(dialogo).getByLabelText(/^Horario/) as HTMLInputElement
    expect(horario.value).toBe(`${LUNES}T09:00`)

    await userEvent.click(within(dialogo).getByLabelText('Prestación'))
    await userEvent.click(await screen.findByText('Consulta'))
    await userEvent.click(within(dialogo).getByLabelText('Paciente'))
    await userEvent.click(await screen.findByText(/Ana Gómez/))
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Crear turno' }))

    await waitFor(() => {
      const alta = pedidos.find((p) => p.url === '/appointments' && p.metodo === 'POST')
      expect(alta?.cuerpo).toEqual({
        resource_id: 'dr-molina', service_id: 'consulta', client_id: 'ana',
        // Naive, sin huso: el backend lo interpreta como hora de pared de la
        // sede. Mandarlo con offset sería decidir acá algo que decide allá.
        starts_at: `${LUNES}T09:00`,
      })
    })
  })

  it('sin profesionales activos lo dice y manda a Configuración', async () => {
    fetchMock.mockImplementation((url: string) => {
      const u = String(url)
      if (u.includes('/resources')) return Promise.resolve(json([]))
      return Promise.resolve(json([]))
    })
    montar()
    expect(await screen.findByText(/Cargá uno en Configuración/)).toBeInTheDocument()
  })

  describe('el medio de pago al completar', () => {
    it('🔴 los medios salen del backend, no de una lista de esta pantalla', async () => {
      // Hasta el 2026-08-24 `Agenda.tsx` declaraba cuatro a mano, y uno
      // —`tarjeta`— no existía en el vocabulario de la familia: llegaba igual a
      // Contalibra, creaba su movimiento de caja y salía en el cierre como un
      // bucket suelto con el nombre crudo. La plata bien contada y el reparto
      // mal.
      // `DE_NOCHE` está `confirmed`, que es el único estado desde el que la
      // ficha ofrece "Completar". Y el POST contesta 422 —el turno tiene saldo—,
      // que es lo que abre el diálogo del medio de pago.
      fetchMock.mockImplementation(conCompletarQuePideMedio([DE_NOCHE]))
      montar(`/agenda?dia=${LUNES}`)
      await waitFor(() => expect(screen.getByText('Ana Gómez')).toBeInTheDocument())
      await userEvent.click(screen.getByText('Ana Gómez'))
      await userEvent.click(await screen.findByRole('button', { name: /^Completar$/ }))

      // El `Select` de Radix no rendea sus opciones hasta que se abre: hay que
      // clickear el trigger. Sin esto, un `queryByRole('option')` pasaría por no
      // encontrar nada y no por el filtro.
      await userEvent.click(await screen.findByRole('combobox'))

      // Primero que hay opciones: si esto falla, lo de abajo no prueba nada.
      expect(await screen.findByRole('option', { name: 'Tarjeta de débito' }))
        .toBeInTheDocument()
      expect(screen.getByRole('option', { name: 'Mercado Pago' })).toBeInTheDocument()
      // 🔴 Y **no** los que declaraba la pantalla: `Tarjeta` a secas era el
      // medio inventado, y el backend de este stub no lo ofrece.
      expect(screen.queryByRole('option', { name: 'Tarjeta' })).not.toBeInTheDocument()
    })

    it('🔴 se le pide la lista al backend al cargar el catálogo', async () => {
      // El control por el otro lado: si la pantalla nunca pidiera `/medios-pago`
      // y las opciones vinieran de una constante, el test de arriba podría pasar
      // igual con una lista hardcodeada que coincida con este stub.
      servir([DE_MANANA])
      montar()
      await waitFor(() => expect(screen.getByText('Ana Gómez')).toBeInTheDocument())
      expect(pedidos.some((p) => p.url.includes('/medios-pago'))).toBe(true)
    })
  })
})
