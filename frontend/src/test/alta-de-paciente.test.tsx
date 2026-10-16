// Dar de alta al paciente ahí mismo, donde se lo elige (ADR-071, libra-ui v0.158.0).
//
// Lo que se prueba es lo que haría fallar el mostrador: que el alta mande el POST que el backend espera
// (SIN `id`: el número lo genera el backend), que el recién creado quede ELEGIDO en el campo —y no en blanco
// con un id adentro— y que el turno / la llegada se anoten con ese id. El guard de fuentes
// (`campos-de-paciente.test.ts`) dice que los campos son `SelectCliente`; esto dice que funcionan.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Agenda } from '../pages/Agenda'
import { DemandaEspontanea } from '../pages/DemandaEspontanea'

const DIA = '2026-07-20'
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
/** Lo que contesta `POST /patients`: el backend le puso el número. */
const BETO = {
  id: 'p-002', name: 'Beto Nuevo', phone: '1155667788', email: 'beto@ejemplo.com.ar', active: true,
  dni: '30222333', birth_date: null, cuit: null, condicion_iva: null,
}
const BLOQUE = {
  id: 'b1', resource_id: 'dr-molina', profesional: 'Dr. Molina',
  consultorio_id: 'cons-1', consultorio: 'Consultorio 1',
  starts_at: '09:00:00', ends_at: '13:00:00', timezone: 'America/Argentina/Buenos_Aires',
}

let fetchMock: ReturnType<typeof vi.fn>
let pedidos: { url: string; metodo: string; cuerpo: unknown }[]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

/** `altaDePaciente` es lo que contesta el POST /patients (o un error). */
function servir(altaDePaciente: Response | (() => Response) = json(BETO, 201)) {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    pedidos.push({ url: u, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : null })
    if (u === '/patients' && metodo === 'POST') {
      return Promise.resolve(typeof altaDePaciente === 'function' ? altaDePaciente() : altaDePaciente)
    }
    if (u === '/patients') return Promise.resolve(json([ANA]))
    if (u === '/agenda/catalogo') return Promise.resolve(json(CATALOGO))
    if (u === '/walkins/prestaciones') return Promise.resolve(json([{ id: 'consulta', name: 'Consulta' }]))
    if (u === `/walkins/bloques?day=${DIA}`) return Promise.resolve(json([BLOQUE]))
    if (u === '/appointments' && metodo === 'POST') return Promise.resolve(json({ id: 't1' }, 201))
    return Promise.resolve(json([]))
  })
}

const mandado = (url: string, metodo = 'POST') => pedidos.find((p) => p.url === url && p.metodo === metodo)

beforeEach(() => {
  fetchMock = vi.fn()
  pedidos = []
  vi.stubGlobal('fetch', fetchMock)
})

/** Abre «Agregar nuevo paciente» dentro de `donde` y carga el formulario de alta. */
async function cargarAlta(donde: HTMLElement) {
  await userEvent.click(within(donde).getByRole('button', { name: 'Agregar nuevo paciente' }))
  const panel = within(donde).getByRole('group', { name: 'Nuevo paciente' })
  await userEvent.type(within(panel).getByLabelText('Nombre *'), 'Beto Nuevo')
  await userEvent.type(within(panel).getByLabelText('DNI'), '30.222.333')
  await userEvent.type(within(panel).getByLabelText('Teléfono'), '1155667788')
  await userEvent.type(within(panel).getByLabelText('Email'), 'beto@ejemplo.com.ar')
  return panel
}

describe('Nuevo turno: el paciente se da de alta ahí mismo', () => {
  async function abrirNuevoTurno() {
    render(
      <MemoryRouter initialEntries={[`/agenda?dia=${DIA}`]}>
        <Routes><Route path="/agenda" element={<Agenda />} /></Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(document.querySelectorAll('[data-columna]')).toHaveLength(7))
    await userEvent.click(screen.getByRole('button', { name: /Nuevo turno/ }))
    return screen.findByRole('dialog')
  }

  it('🔴 crea el paciente con POST /patients SIN id, queda elegido y el turno se manda con su id', async () => {
    servir()
    const dialogo = await abrirNuevoTurno()

    const panel = await cargarAlta(dialogo)
    await userEvent.click(within(panel).getByRole('button', { name: 'Crear paciente' }))

    await waitFor(() => expect(mandado('/patients')).toBeDefined())
    // Sin `id` (lo genera el backend), con el DNI normalizado y lo demás tal cual se escribió.
    expect(mandado('/patients')?.cuerpo).toEqual({
      name: 'Beto Nuevo', dni: '30222333', phone: '1155667788', email: 'beto@ejemplo.com.ar',
    })
    expect(mandado('/patients')?.cuerpo).not.toHaveProperty('id')

    // Queda elegido en el campo (con su nombre, no con el id) y el panel se cierra.
    await waitFor(() => expect(within(dialogo).getByRole('combobox', { name: 'Paciente' })).toHaveValue('Beto Nuevo'))
    expect(within(dialogo).queryByRole('group', { name: 'Nuevo paciente' })).not.toBeInTheDocument()

    await userEvent.click(within(dialogo).getByLabelText('Prestación'))
    await userEvent.click(await screen.findByText('Consulta'))
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Crear turno' }))
    await waitFor(() => {
      expect(mandado('/appointments')?.cuerpo).toMatchObject({ client_id: 'p-002', service_id: 'consulta' })
    })
  })

  it('un campo vacío del alta viaja como null, no como cadena vacía', async () => {
    servir()
    const dialogo = await abrirNuevoTurno()
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo paciente' }))
    const panel = within(dialogo).getByRole('group', { name: 'Nuevo paciente' })
    await userEvent.type(within(panel).getByLabelText('Nombre *'), 'Beto Nuevo')
    await userEvent.click(within(panel).getByRole('button', { name: 'Crear paciente' }))

    await waitFor(() => expect(mandado('/patients')?.cuerpo).toEqual({
      name: 'Beto Nuevo', dni: null, phone: null, email: null,
    }))
  })

  it('si el backend rechaza el alta, lo dice dentro del panel y no pierde lo cargado', async () => {
    servir(json({ detail: 'patient already exists' }, 409))
    const dialogo = await abrirNuevoTurno()

    const panel = await cargarAlta(dialogo)
    await userEvent.click(within(panel).getByRole('button', { name: 'Crear paciente' }))

    expect(await within(panel).findByRole('alert')).toHaveTextContent('patient already exists')
    expect(within(panel).getByLabelText('Nombre *')).toHaveValue('Beto Nuevo')
    expect(within(dialogo).getByRole('combobox', { name: 'Paciente' })).toHaveValue('')
  })

  it('Escape cierra el panel de alta y no el diálogo del turno', async () => {
    servir()
    const dialogo = await abrirNuevoTurno()
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Agregar nuevo paciente' }))
    const nombre = within(dialogo).getByLabelText('Nombre *')

    await userEvent.type(nombre, 'Beto{Escape}')

    expect(within(dialogo).queryByRole('group', { name: 'Nuevo paciente' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('Anotar llegada: el paciente se da de alta ahí mismo', () => {
  it('🔴 crea el paciente sin id, queda elegido y la llegada se anota con su id', async () => {
    servir()
    render(
      <MemoryRouter initialEntries={[`/demanda-espontanea?dia=${DIA}`]}>
        <DemandaEspontanea />
      </MemoryRouter>,
    )
    const campo = (await screen.findByRole('combobox', { name: 'Paciente' })).closest('form') as HTMLElement

    const panel = await cargarAlta(campo)
    await userEvent.click(within(panel).getByRole('button', { name: 'Crear paciente' }))

    await waitFor(() => expect(mandado('/patients')?.cuerpo).toEqual({
      name: 'Beto Nuevo', dni: '30222333', phone: '1155667788', email: 'beto@ejemplo.com.ar',
    }))
    expect(mandado('/patients')?.cuerpo).not.toHaveProperty('id')
    await waitFor(() => expect(within(campo).getByRole('combobox', { name: 'Paciente' })).toHaveValue('Beto Nuevo'))

    await userEvent.click(within(campo).getByRole('combobox', { name: 'Prestación' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Consulta' }))
    await userEvent.click(within(campo).getByRole('button', { name: 'Anotar llegada' }))
    await waitFor(() => {
      expect(pedidos.find((p) => p.url.includes('/walkins') && p.metodo === 'POST')?.cuerpo)
        .toMatchObject({ client_id: 'p-002', service_id: 'consulta' })
    })
  })

  it('ya no manda a Pacientes para dar de alta: el link se reemplazó por el alta en el lugar', async () => {
    servir()
    render(
      <MemoryRouter initialEntries={[`/demanda-espontanea?dia=${DIA}`]}>
        <DemandaEspontanea />
      </MemoryRouter>,
    )
    await screen.findByRole('combobox', { name: 'Paciente' })
    expect(screen.queryByRole('link', { name: 'Pacientes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agregar nuevo paciente' })).toBeInTheDocument()
  })
})
