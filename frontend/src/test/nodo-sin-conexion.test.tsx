// MedLibra en la PC del consultorio sin conexión (LibraEdge, ADR-045 de este producto; libra-ui ADR-095).
//
// Lo que se prueba es lo que vería —o no vería— el mostrador:
//
// - el turno atendido sin conexión lleva SU etiqueta («Atendido sin conexión») y, si ya subió y en la web cambió, «A revisar»: nunca
//   las dos; sin nodo no se dibuja ninguna;
// - completar un turno sin conexión dice que se manda solo (y NO «no se facturó», que sería falso);
// - «Empezar» y «No vino» llaman a sus rutas;
// - «Turnos a revisar» dice de quién es cada turno, y «Ya lo revisé» existe en la web y NO en la PC (la tabla es del espejo);
// - el paciente dado de alta sin conexión lleva «Provisorio» (id `-N`), y la llegada anotada sin conexión no enseña su número negativo.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Agenda } from '../pages/Agenda'
import { DemandaEspontanea } from '../pages/DemandaEspontanea'
import { Pacientes } from '../pages/Pacientes'
import { TurnosARevisar } from '../pages/TurnosARevisar'

// La lista de pacientes sólo le pregunta al contexto si el usuario es admin (para el botón de eliminar): se mockea el shim en vez de
// montar el `AuthProvider` entero, que trae el gate de Términos y pide su propio endpoint.
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', username: 'ana', name: 'Ana', role: 'admin', active: true }, loading: false, login: vi.fn(), logout: vi.fn(),
  }),
}))

const LUNES = '2026-07-20'
const PROFESIONAL = { id: 'dr-molina', name: 'Dr. Molina', branch_id: 'centro', active: true }
const CATALOGO = {
  profesionales: [PROFESIONAL],
  sedes: [{ id: 'centro', name: 'Consultorio Centro', timezone: 'America/Argentina/Buenos_Aires' }],
  prestaciones: [{ id: 'consulta', name: 'Consulta', duration_minutes: 30, active: true }],
}
const ANA = {
  id: 'p-001', name: 'Ana Gómez', phone: null, email: null, active: true, dni: '30111222',
  birth_date: null, cuit: null, condicion_iva: null,
}
const NUEVA = { ...ANA, id: '-1', name: 'Nuria Provisoria', dni: '40111222' }

/** Un turno del lunes 10:00 de la sede. */
function turno(extra: Record<string, unknown> = {}) {
  return {
    id: 't-1', resource_id: 'dr-molina', service_id: 'consulta', client_id: 'p-001',
    starts_at: '2026-07-20T13:00:00Z', ends_at: '2026-07-20T13:30:00Z', status: 'confirmed', ...extra,
  }
}

let fetchMock: ReturnType<typeof vi.fn>
let pedidos: { url: string; metodo: string; cuerpo: unknown }[]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

type Respuestas = {
  turnos?: unknown[]
  aRevisar?: unknown[]
  pacientes?: unknown[]
  completar?: Response
  nodo?: Record<string, unknown>
  llegadas?: unknown[]
}

function servir({ turnos = [], aRevisar = [], pacientes = [ANA], completar, nodo, llegadas = [] }: Respuestas = {}) {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    pedidos.push({ url: u, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : null })
    if (u === '/api/nodo/conexion') return Promise.resolve(json(nodo ?? { es_nodo: false, en_linea: true, node_id: null, a_facturar: 0 }))
    if (u === '/turnos-a-revisar') return Promise.resolve(json(aRevisar))
    if (u.startsWith('/turnos-a-revisar/revisadas')) return Promise.resolve(json({ revisadas: 1 }))
    if (u.includes('/complete')) return Promise.resolve(completar ?? json({ id: 't-1', status: 'completed', contalibra: null }))
    if (u.includes('/start')) return Promise.resolve(json({ id: 't-1', status: 'in_progress' }))
    if (u.includes('/no-show')) return Promise.resolve(json({ id: 't-1', status: 'no_show' }))
    if (u.includes('/agenda?')) return Promise.resolve(json(u.includes('/resources/dr-molina/') ? turnos : []))
    if (u === '/agenda/catalogo') return Promise.resolve(json(CATALOGO))
    if (u.includes('/medios-pago')) return Promise.resolve(json([{ id: 'efectivo', label: 'Efectivo' }]))
    if (u === '/patients') return Promise.resolve(json(pacientes))
    if (u === '/walkins/prestaciones') return Promise.resolve(json([{ id: 'consulta', name: 'Consulta' }]))
    if (u.startsWith('/walkins/bloques')) {
      return Promise.resolve(json([{
        id: 'b1', resource_id: 'dr-molina', profesional: 'Dr. Molina', consultorio_id: 'c1', consultorio: 'Consultorio 1',
        starts_at: '09:00:00', ends_at: '13:00:00', timezone: 'America/Argentina/Buenos_Aires',
      }]))
    }
    if (u.startsWith('/agenda-blocks/b1/walkins')) return Promise.resolve(json(llegadas))
    return Promise.resolve(json([]))
  })
}

beforeEach(() => {
  fetchMock = vi.fn()
  pedidos = []
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function montarAgenda(ruta = `/agenda?dia=${LUNES}&turno=t-1`) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <Routes>
        <Route path="/agenda" element={<Agenda />} />
        <Route path="/turnos-a-revisar" element={<p>pantalla de turnos a revisar</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('el turno atendido sin conexión, en la agenda', () => {
  it('lleva «Atendido sin conexión» junto a su estado', async () => {
    servir({ turnos: [turno({ status: 'in_progress', atendido_en_la_pc: true })] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('En curso')).toBeInTheDocument()
    expect(within(dialogo).getByText('Atendido sin conexión')).toBeInTheDocument()
    expect(within(dialogo).queryByText('A revisar')).not.toBeInTheDocument()
  })

  it('lleva «A revisar» cuando subió y en la web cambió, y nunca las dos', async () => {
    servir({ turnos: [turno({ status: 'cancelled', a_revisar: true, motivo: 'cancelado', atendido_en_la_pc: true })] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('A revisar')).toBeInTheDocument()
    expect(within(dialogo).queryByText('Atendido sin conexión')).not.toBeInTheDocument()
  })

  it('🔴 el control — un turno de siempre no lleva ninguna etiqueta del nodo', async () => {
    servir({ turnos: [turno()] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByText('Confirmado')).toBeInTheDocument()
    expect(within(dialogo).queryByText('Atendido sin conexión')).not.toBeInTheDocument()
    expect(within(dialogo).queryByText('A revisar')).not.toBeInTheDocument()
  })

  it('avisa cuántos turnos esperan revisión, con el camino a la lista', async () => {
    const fila = (id: string, turnoId: string) => ({
      atencion_id: id, appointment_id: turnoId, estado: 'completed', at: '2026-07-20T14:00:00+00:00', actor: 'admin',
      motivo: 'cancelado', resultado: 'a_revisar', paciente: 'Ana Gómez', servicio: 'Consulta',
    })
    // dos atenciones del mismo turno y una de otro: son dos turnos
    servir({ aRevisar: [fila('a1', 't-1'), fila('a2', 't-1'), fila('a3', 't-2')] })
    montarAgenda(`/agenda?dia=${LUNES}`)
    expect(await screen.findByText(/Hay 2 turnos para revisar/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Ver turnos a revisar' }))
    expect(await screen.findByText('pantalla de turnos a revisar')).toBeInTheDocument()
  })

  it('sin turnos a revisar no hay aviso', async () => {
    servir({ aRevisar: [] })
    montarAgenda(`/agenda?dia=${LUNES}`)
    await waitFor(() => expect(pedidos.some((p) => p.url === '/turnos-a-revisar')).toBe(true))
    expect(screen.queryByText(/para revisar/)).not.toBeInTheDocument()
  })
})

describe('atender un turno desde su detalle', () => {
  it('«Empezar» y «No vino» llaman a sus rutas', async () => {
    servir({ turnos: [turno()] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Empezar' }))
    await waitFor(() => expect(pedidos.some((p) => p.url === '/appointments/t-1/start' && p.metodo === 'POST')).toBe(true))
  })

  it('«No vino»', async () => {
    servir({ turnos: [turno()] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'No vino' }))
    await waitFor(() => expect(pedidos.some((p) => p.url === '/appointments/t-1/no-show' && p.metodo === 'POST')).toBe(true))
  })

  it('un turno en curso se puede completar, y uno que ya no está confirmado no ofrece «Empezar» ni «No vino»', async () => {
    servir({ turnos: [turno({ status: 'in_progress' })] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('button', { name: 'Completar' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'Empezar' })).not.toBeInTheDocument()
    expect(within(dialogo).queryByRole('button', { name: 'No vino' })).not.toBeInTheDocument()
  })

  it('completar sin conexión dice que se manda solo, y no que «no se facturó»', async () => {
    servir({
      turnos: [turno()],
      completar: json({ id: 't-1', status: 'completed', contalibra: null, atendido_sin_conexion: true }),
    })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Completar' }))
    const aviso = await screen.findByRole('dialog', { name: 'Turno atendido sin conexión' })
    expect(within(aviso).getByText(/Se suben solos cuando vuelva la conexión/)).toBeInTheDocument()
    expect(screen.queryByText(/no se facturó/)).not.toBeInTheDocument()
  })

  it('🔴 el control — completar en la web no muestra ese aviso', async () => {
    servir({ turnos: [turno()] })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Completar' }))
    await waitFor(() => expect(pedidos.some((p) => p.url === '/appointments/t-1/complete')).toBe(true))
    expect(screen.queryByText('Turno atendido sin conexión')).not.toBeInTheDocument()
  })

  it('un 409 de la PC se muestra con su texto, no como error de conexión', async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      const u = String(url)
      pedidos.push({ url: u, metodo: init?.method ?? 'GET', cuerpo: null })
      if (u.includes('/confirm')) {
        return Promise.resolve(json({ detail: { codigo: 'sin_conexion', mensaje: 'Sin conexión: los turnos se dan, se mueven y se cancelan desde la web, cuando vuelva la conexión.' } }, 409))
      }
      if (u.includes('/agenda?')) return Promise.resolve(json(u.includes('/resources/dr-molina/') ? [turno({ status: 'pending' })] : []))
      if (u === '/agenda/catalogo') return Promise.resolve(json(CATALOGO))
      if (u === '/patients') return Promise.resolve(json([ANA]))
      return Promise.resolve(json([]))
    })
    montarAgenda()
    const dialogo = await screen.findByRole('dialog')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Confirmar' }))
    expect(await within(dialogo).findByText(/se dan, se mueven y se cancelan desde la web/)).toBeInTheDocument()
  })
})

const FILA_A_REVISAR = (extra: Record<string, unknown> = {}) => ({
  atencion_id: 'a1', appointment_id: 't-1', estado: 'completed', at: '2026-07-20T14:00:00+00:00', actor: 'admin',
  motivo: 'cancelado', estado_despues: 'cancelled', resultado: 'a_revisar', revisada_at: null,
  paciente: 'Ana Gómez', servicio: 'Consulta', starts_at: '2026-07-20T13:00:00Z', zona: 'America/Argentina/Buenos_Aires', ...extra,
})

describe('Turnos a revisar', () => {
  it('dice de quién es el turno, qué pasó y a qué hora era en la sede', async () => {
    servir({ aRevisar: [FILA_A_REVISAR()] })
    render(<MemoryRouter><TurnosARevisar /></MemoryRouter>)
    expect(await screen.findByText(/Ana Gómez · Consulta · 20-07 10:00/)).toBeInTheDocument()
    expect(screen.getByText('Se canceló en la web.')).toBeInTheDocument()
  })

  it('en la web, «Ya lo revisé» entrega las atenciones del turno entero y recarga la lista', async () => {
    servir({ aRevisar: [FILA_A_REVISAR(), FILA_A_REVISAR({ atencion_id: 'a2', estado: 'in_progress' })] })
    render(<MemoryRouter><TurnosARevisar /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: /Ya lo revisé/ }))
    await waitFor(() => {
      const revisada = pedidos.find((p) => p.url === '/turnos-a-revisar/revisadas')
      expect(revisada?.metodo).toBe('POST')
      expect((revisada?.cuerpo as { atenciones: string[] }).atenciones.sort()).toEqual(['a1', 'a2'])
    })
    await waitFor(() => expect(pedidos.filter((p) => p.url === '/turnos-a-revisar' && p.metodo === 'GET').length).toBeGreaterThan(1))
  })

  it('un turno que ya no existe en la web igual se puede leer', async () => {
    servir({ aRevisar: [FILA_A_REVISAR({ motivo: 'turno_inexistente', paciente: null, servicio: null, starts_at: null, zona: null })] })
    render(<MemoryRouter><TurnosARevisar /></MemoryRouter>)
    expect(await screen.findByText('Turno que ya no existe')).toBeInTheDocument()
    expect(screen.getByText('El turno ya no existe en la web.')).toBeInTheDocument()
  })

  it('si la lista no carga lo dice', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'Error interno' }, 500)))
    render(<MemoryRouter><TurnosARevisar /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toHaveTextContent('Error interno')
  })

  it('en la PC del consultorio la lista se ve pero «Ya lo revisé» no se ofrece: la revisión es de la web', async () => {
    const { consultarConexionDelNodo } = await import('libra-ui/nodo-offline')
    servir({ aRevisar: [FILA_A_REVISAR()], nodo: { es_nodo: true, en_linea: false, node_id: 'consultorio-1', a_facturar: 0 } })
    const parar = consultarConexionDelNodo()
    try {
      await waitFor(() => expect(pedidos.some((p) => p.url === '/api/nodo/conexion')).toBe(true))
      render(<MemoryRouter><TurnosARevisar /></MemoryRouter>)
      expect(await screen.findByText(/Ana Gómez · Consulta/)).toBeInTheDocument()
      await waitFor(() => expect(screen.queryByRole('button', { name: /Ya lo revisé/ })).not.toBeInTheDocument())
    } finally {
      parar()
    }
  })
})

describe('lo dado de alta sin conexión', () => {
  it('el paciente con id `-N` lleva «Provisorio» en la lista y el de siempre no', async () => {
    servir({ pacientes: [ANA, NUEVA] })
    render(<MemoryRouter><Pacientes /></MemoryRouter>)
    const nueva = await screen.findByText('Nuria Provisoria')
    expect(within(nueva.closest('tr') as HTMLElement).getByText('Provisorio')).toBeInTheDocument()
    expect(within(screen.getByText('Ana Gómez').closest('tr') as HTMLElement).queryByText('Provisorio')).not.toBeInTheDocument()
  })

  it('la llegada anotada sin conexión no enseña su número negativo y su paciente lleva «Provisorio»', async () => {
    const llegada = (id: string, orden: number, cliente: string) => ({
      id, block_id: 'b1', day: LUNES, client_id: cliente, service_id: 'consulta', arrival_order: orden, status: 'waiting',
      created_at: '2026-07-20T12:00:00Z',
    })
    servir({
      pacientes: [ANA, NUEVA],
      llegadas: [llegada('w1', 1, 'p-001'), llegada('w2', -1, '-1')],
    })
    render(
      <MemoryRouter initialEntries={[`/demanda-espontanea?dia=${LUNES}&bloque=b1`]}>
        <Routes><Route path="/demanda-espontanea" element={<DemandaEspontanea />} /></Routes>
      </MemoryRouter>,
    )
    const filaNueva = (await screen.findByText('Nuria Provisoria')).closest('tr') as HTMLElement
    expect(within(filaNueva).getByText('Provisorio')).toBeInTheDocument()
    expect(filaNueva.textContent).not.toContain('-1')
    expect(within(filaNueva).getByText('—')).toBeInTheDocument()
    const filaAna = screen.getByText('Ana Gómez').closest('tr') as HTMLElement
    expect(within(filaAna).getByText('1')).toBeInTheDocument()
  })
})
