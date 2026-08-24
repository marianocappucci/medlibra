// Las cuatro secciones de Configuración que parametrizan la agenda.
//
// Hasta hoy no había ninguna pantalla para esto: los endpoints existían y sólo
// se llegaba a ellos por API o por el seed. Lo que se prueba acá es que **un
// alta se hace dando de alta** — qué se manda, a dónde, y qué queda a la vista
// después.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SedesCard } from '../pages/configuracion/sedes'
import { ConsultoriosCard } from '../pages/configuracion/consultorios'
import { PrestacionesCard } from '../pages/configuracion/prestaciones'
import { ProfesionalesCard } from '../pages/configuracion/profesionales'

const SEDE = {
  id: 'centro', name: 'Centro', active: true,
  timezone: 'America/Argentina/Buenos_Aires', phone: null, address: 'Rivadavia 100',
}
const PROFESIONAL = { id: 'dra-vidal', name: 'Dra. Vidal', branch_id: 'centro', active: true }
const CONSULTORIO = { id: 'cons-1', name: 'Consultorio 1', branch_id: 'centro', active: true }
const PRESTACION = { id: 'consulta', name: 'Consulta', duration_minutes: 20, active: true }
const OPCIONES = { duraciones: [10, 15, 20, 25, 30], modalidades: ['turnos', 'espontanea'] }

let fetchMock: ReturnType<typeof vi.fn>
let pedidos: { url: string; metodo: string; cuerpo: unknown }[]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

/** Sirve cada ruta EXACTA; cualquier otra devuelve una lista vacía.
 *
 *  🔴 Exacta y no por subcadena. Con `includes`, `/resources/dra-vidal/blocks`
 *  cae en la clave `/resources` y el componente de bloqueos recibe una lista de
 *  profesionales: revienta al leer `starts_at`, la pantalla queda vacía, y los
 *  tests fallan con un mensaje que no tiene nada que ver con lo que dicen
 *  medir. */
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

function montar(nodo: React.ReactNode) {
  return render(<MemoryRouter>{nodo}</MemoryRouter>)
}

function mandado(url: string, metodo = 'POST') {
  return pedidos.find((p) => p.url === url && p.metodo === metodo)
}

function todosLosMandados(url: string, metodo = 'POST') {
  return pedidos.filter((p) => p.url === url && p.metodo === metodo)
}

beforeEach(() => {
  fetchMock = vi.fn()
  pedidos = []
  vi.stubGlobal('fetch', fetchMock)
})

// ── Sedes ──────────────────────────────────────────────────────────────────

describe('Sedes', () => {
  it('lista lo que hay, con su huso', async () => {
    servir({ '/branches': [SEDE] })
    montar(<SedesCard />)
    expect(await screen.findByText('Centro')).toBeInTheDocument()
    // `getAllBy`: el huso sale dos veces, en la fila de la lista y en el
    // selector del formulario.
    expect(screen.getAllByText(/Argentina \(UTC-3\)/).length).toBeGreaterThan(0)
  })

  it('🔴 el alta manda el huso de Argentina, no UTC', async () => {
    // Es el default de la lista y el del backend. Con UTC la agenda muestra los
    // turnos tres horas corridos — y peor, con offset cero un error de
    // conversión da el mismo resultado que la conversión correcta (ADR-028).
    servir({ '/branches': [] })
    montar(<SedesCard />)
    await userEvent.type(await screen.findByLabelText('Nombre'), 'Consultorio Norte')
    await userEvent.click(screen.getByRole('button', { name: 'Crear' }))
    await waitFor(() => expect(mandado('/branches')).toBeTruthy())
    expect(mandado('/branches')!.cuerpo).toMatchObject({
      // El identificador sale del nombre, sin acentos ni espacios.
      id: 'consultorio-norte',
      name: 'Consultorio Norte',
      timezone: 'America/Argentina/Buenos_Aires',
      active: true,
    })
  })

  it('al elegir una sede aparece su horario de atención', async () => {
    servir({ '/branches/centro/hours': [], '/branches': [SEDE] })
    montar(<SedesCard />)
    await userEvent.click(await screen.findByText('Centro'))
    expect(await screen.findByText('Horario de atención')).toBeInTheDocument()
  })

  it('🔴 "Lunes a viernes" carga los cinco días de una', async () => {
    servir({ '/branches/centro/hours': [], '/branches': [SEDE] })
    montar(<SedesCard />)
    await userEvent.click(await screen.findByText('Centro'))
    await screen.findByText('Horario de atención')
    await userEvent.click(screen.getByRole('button', { name: 'Lunes a viernes' }))

    await waitFor(() => {
      const altas = todosLosMandados('/branches/centro/hours')
      expect(altas.map((a) => (a.cuerpo as { weekday: number }).weekday)).toEqual([0, 1, 2, 3, 4])
    })
  })

  it('🔴 el control — no pisa un día que ya estaba cargado', async () => {
    // Cargar el lunes de 14 a 20 y después apretar el atajo no puede duplicar
    // el lunes: la sede quedaría con dos horarios contradictorios el mismo día
    // y el motor aceptaría los dos.
    servir({
      '/branches/centro/hours': [
        { id: 1, weekday: 0, starts_at: '14:00:00', ends_at: '20:00:00' },
      ],
      '/branches': [SEDE],
    })
    montar(<SedesCard />)
    await userEvent.click(await screen.findByText('Centro'))
    await screen.findByText('Horario de atención')
    await userEvent.click(screen.getByRole('button', { name: 'Lunes a viernes' }))

    await waitFor(() => {
      const altas = todosLosMandados('/branches/centro/hours')
      expect(altas.map((a) => (a.cuerpo as { weekday: number }).weekday)).toEqual([1, 2, 3, 4])
    })
  })
})

// ── Consultorios ───────────────────────────────────────────────────────────

describe('Consultorios', () => {
  it('el alta manda la sede elegida', async () => {
    servir({ '/consultorios': [], '/branches': [SEDE] })
    montar(<ConsultoriosCard />)
    await userEvent.type(await screen.findByLabelText('Nombre'), 'Consultorio 2')
    await userEvent.click(screen.getByLabelText('Sede'))
    await userEvent.click(await screen.findByRole('option', { name: 'Centro' }))
    await userEvent.click(screen.getByRole('button', { name: 'Crear' }))
    await waitFor(() => expect(mandado('/consultorios')).toBeTruthy())
    expect(mandado('/consultorios')!.cuerpo).toEqual({
      id: 'consultorio-2', name: 'Consultorio 2', branch_id: 'centro', active: true,
    })
  })

  it('🔴 sin consultorios lo dice, porque un bloque de agenda necesita uno', async () => {
    servir({ '/consultorios': [], '/branches': [SEDE] })
    montar(<ConsultoriosCard />)
    expect(await screen.findByText(/necesita uno para poder existir/)).toBeInTheDocument()
  })
})

// ── Prestaciones ───────────────────────────────────────────────────────────

describe('Prestaciones', () => {
  it('el alta manda la duración sugerida', async () => {
    servir({ '/services': [], '/branches': [SEDE] })
    montar(<PrestacionesCard />)
    await userEvent.type(await screen.findByLabelText('Nombre'), 'Electro')
    const duracion = screen.getByLabelText('Duración sugerida (min)')
    await userEvent.clear(duracion)
    await userEvent.type(duracion, '15')
    await userEvent.click(screen.getByRole('button', { name: 'Crear' }))
    await waitFor(() => expect(mandado('/services')).toBeTruthy())
    expect(mandado('/services')!.cuerpo).toEqual({
      id: 'electro', name: 'Electro', duration_minutes: 15, active: true,
    })
  })

  it('el precio se carga por sede', async () => {
    servir({
      '/services/consulta/prices': [],
      '/services': [PRESTACION],
      '/branches': [SEDE],
    })
    montar(<PrestacionesCard />)
    await userEvent.click(await screen.findByText('Consulta'))
    await userEvent.type(await screen.findByLabelText('Centro'), '25000')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    await waitFor(() => expect(mandado('/services/consulta/prices', 'PUT')).toBeTruthy())
    expect(mandado('/services/consulta/prices', 'PUT')!.cuerpo).toEqual({
      branch_id: 'centro', price: '25000',
    })
  })

  it('🔴 una sede sin precio se ve, no se esconde', async () => {
    // Una prestación sin precio en una sede se completa SIN facturar. Si la
    // sede no apareciera en la lista, esa ausencia sería invisible.
    servir({
      '/services/consulta/prices': [],
      '/services': [PRESTACION],
      '/branches': [SEDE],
    })
    montar(<PrestacionesCard />)
    await userEvent.click(await screen.findByText('Consulta'))
    expect(await screen.findByText('Sin precio')).toBeInTheDocument()
  })
})

// ── Profesionales y sus bloques de agenda ──────────────────────────────────

const RUTAS_DEL_PROFESIONAL = {
  '/resources': [PROFESIONAL],
  '/branches': [SEDE],
  '/consultorios': [CONSULTORIO],
  '/agenda-blocks?resource_id=dra-vidal': [],
  '/agenda-blocks/opciones': OPCIONES,
  '/resources/dra-vidal/blocks': [],
  '/resources/dra-vidal/exceptions': [],
}

describe('Profesionales', () => {
  it('el alta manda la sede elegida', async () => {
    servir({ '/resources': [], '/branches': [SEDE], '/consultorios': [CONSULTORIO] })
    montar(<ProfesionalesCard />)
    await userEvent.type(await screen.findByLabelText('Nombre'), 'Dr. Arce')
    await userEvent.click(screen.getByLabelText('Sede'))
    await userEvent.click(await screen.findByRole('option', { name: 'Centro' }))
    await userEvent.click(screen.getByRole('button', { name: 'Crear' }))
    await waitFor(() => expect(mandado('/resources')).toBeTruthy())
    expect(mandado('/resources')!.cuerpo).toEqual({
      id: 'dr-arce', name: 'Dr. Arce', branch_id: 'centro', active: true,
    })
  })

  it('🔴 avisa que sin ningún bloque el profesional no recibe turnos', async () => {
    // Es la asimetría que deja la agenda muerta: el horario de la sede es
    // opt-in, la agenda del profesional NO. Cargar sólo el primero —que es lo
    // intuitivo— hace que toda alta se rechace, sin ninguna pista.
    servir(RUTAS_DEL_PROFESIONAL)
    montar(<ProfesionalesCard />)
    await userEvent.click(await screen.findByText('Dra. Vidal'))
    expect(await screen.findByText(/no recibe turnos/)).toBeInTheDocument()
  })

  it('🔴 un bloque por día: "lunes a viernes" son cinco altas', async () => {
    // El backend modela un bloque por día de la semana a propósito —así el
    // miércoles puede estar en otra sala—, pero cargarlos a mano de a uno, por
    // cada profesional, es el gesto que más se repite en esta pantalla.
    servir(RUTAS_DEL_PROFESIONAL)
    montar(<ProfesionalesCard />)
    await userEvent.click(await screen.findByText('Dra. Vidal'))
    await screen.findByText('Agenda')
    await userEvent.click(screen.getByRole('button', { name: /Agregar 5 días/ }))

    await waitFor(() => {
      const altas = todosLosMandados('/agenda-blocks')
      expect(altas.map((a) => (a.cuerpo as { weekday: number }).weekday)).toEqual([0, 1, 2, 3, 4])
    })
    expect(todosLosMandados('/agenda-blocks')[0].cuerpo).toMatchObject({
      resource_id: 'dra-vidal',
      consultorio_id: 'cons-1',
      starts_at: '09:00:00',
      ends_at: '13:00:00',
      slot_minutes: 20,
      modality: 'turnos',
      // Sin fecha de fin: el caso normal de una agenda estable.
      valid_to: null,
    })
  })

  it('🔴 el control — deseleccionar días cambia cuántos bloques se crean', async () => {
    // Sin esto, "mandar siempre los cinco hábiles" pasaría el test de arriba.
    servir(RUTAS_DEL_PROFESIONAL)
    montar(<ProfesionalesCard />)
    await userEvent.click(await screen.findByText('Dra. Vidal'))
    await screen.findByText('Agenda')
    await userEvent.click(screen.getByRole('button', { name: 'Mar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Jue' }))
    await userEvent.click(screen.getByRole('button', { name: /Agregar 3 días/ }))

    await waitFor(() => {
      const altas = todosLosMandados('/agenda-blocks')
      expect(altas.map((a) => (a.cuerpo as { weekday: number }).weekday)).toEqual([0, 2, 4])
    })
  })

  it('🔴 en demanda espontánea no se ofrece duración', async () => {
    // No hay turnos que durar: se atiende por orden de llegada. Ofrecer el
    // campo igual haría creer que hace algo.
    servir(RUTAS_DEL_PROFESIONAL)
    montar(<ProfesionalesCard />)
    await userEvent.click(await screen.findByText('Dra. Vidal'))
    await screen.findByText('Agenda')
    expect(screen.getByLabelText('Duración')).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Modalidad'))
    await userEvent.click(await screen.findByRole('option', { name: 'Demanda espontánea' }))
    await waitFor(() => expect(screen.queryByLabelText('Duración')).not.toBeInTheDocument())
  })

  it('una excepción se puede cargar como cierre o como apertura', async () => {
    servir(RUTAS_DEL_PROFESIONAL)
    montar(<ProfesionalesCard />)
    await userEvent.click(await screen.findByText('Dra. Vidal'))
    await screen.findByText('Excepciones por fecha')

    await userEvent.type(screen.getByLabelText('Fecha'), '2026-12-25')
    await userEvent.click(screen.getByLabelText('Qué hace'))
    await userEvent.click(await screen.findByRole('option', { name: 'Abre' }))
    await userEvent.click(screen.getByRole('button', { name: 'Agregar excepción' }))

    await waitFor(() => expect(mandado('/resources/dra-vidal/exceptions')).toBeTruthy())
    expect(mandado('/resources/dra-vidal/exceptions')!.cuerpo).toEqual({
      day: '2026-12-25', starts_at: '09:00:00', ends_at: '19:00:00', available: true,
    })
  })
})
