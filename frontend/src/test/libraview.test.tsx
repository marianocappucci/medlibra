// La costura con LibraView (ADR-051) en la pestaña «Estudios» de la ficha del paciente.
//
// Lo que se prueba es lo que vería —o no vería— quien atiende:
//
// - sin LibraView configurado la pestaña es la de siempre: ni botón, ni badge, ni se piden los envíos;
// - «Enviar a LibraView» abre un diálogo ya cargado con lo que se puede deducir (la práctica por coincidencia de nombre, apellido y
//   nombres si la ficha dice «Apellido, Nombres», el DNI y la fecha de la ficha, el médico del pedido, los motivos) y el POST lleva
//   exactamente lo que el backend espera;
// - sin DNI o sin fecha no se manda nada;
// - un pedido enviado dice «En LibraView» y el N.º de acceso de cada ítem; uno con error dice el error y se reintenta.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PacienteFicha } from '../pages/PacienteFicha'
import { normalizar, partirNombre, practicaSugerida } from '../lib/libraview'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', username: 'ana', name: 'Dra. Ficticia', role: 'admin', active: true }, loading: false, login: vi.fn(), logout: vi.fn(),
  }),
}))

const PACIENTE: { [campo: string]: string | boolean | null } = {
  id: 'p-1', name: 'Ficticia, Ana María', phone: '1155550100', email: null, active: true, dni: '99100001',
  birth_date: '1975-03-02', cuit: null, condicion_iva: null,
}
const PEDIDO = {
  id: 'o-1', patient_id: 'p-1', created_at: '2026-10-28T15:00:00Z', author: 'Dr. Ficticio Gómez',
  items: [
    { id: 'i-1', study_type: 'Radiografía de tórax', reason: 'Tos persistente', results: [] },
    { id: 'i-2', study_type: 'Eco abdominal', reason: null, results: [] },
  ],
}
const CATALOGO = [
  { codigo: 'RX-TORAX', nombre: 'Radiografía de tórax', modalidad: 'DX', codigo_nomenclador: null, preparacion: null },
  { codigo: 'ECO-ABD', nombre: 'Ecografía abdominal', modalidad: 'US', codigo_nomenclador: null, preparacion: 'Ayuno de 6 horas' },
]
const ENVIADO = {
  order_id: 'o-1', estado: 'enviado', error: '', intentos: 1, actualizado: '2026-10-28T15:05:00Z',
  items: [
    { item_id: 'i-1', codigo_practica: 'RX-TORAX', numero_acceso: '202600000051' },
    { item_id: 'i-2', codigo_practica: 'ECO-ABD', numero_acceso: '202600000052' },
  ],
}
const CON_ERROR = {
  ...ENVIADO, estado: 'error', error: '503: en mantenimiento', intentos: 2,
  items: ENVIADO.items.map((i) => ({ ...i, numero_acceso: null })),
}

type Escenario = {
  paciente?: typeof PACIENTE
  configurado?: boolean
  envios?: unknown[]
  alEnviar?: () => Response
}

let pedidos: { url: string; metodo: string; cuerpo: Record<string, unknown> | null }[]

function json(cuerpo: unknown, status = 200) {
  return new Response(JSON.stringify(cuerpo), { status, headers: { 'content-type': 'application/json' } })
}

function servir({ paciente = PACIENTE, configurado = true, envios = [], alEnviar }: Escenario = {}) {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    pedidos.push({ url: u, metodo, cuerpo: init?.body ? JSON.parse(String(init.body)) : null })
    if (u === '/patients/p-1') return Promise.resolve(json(paciente))
    if (u === '/patients/p-1/study-orders') return Promise.resolve(json([PEDIDO]))
    if (u === '/integraciones/libraview/estado') return Promise.resolve(json({ configurado, recibe_resultados: true }))
    if (u === '/integraciones/libraview/envios?patient_id=p-1') return Promise.resolve(json(envios))
    if (u === '/integraciones/libraview/practicas') return Promise.resolve(json(CATALOGO))
    if (u === '/patients/p-1/study-orders/o-1/libraview' && metodo === 'POST') {
      return Promise.resolve(alEnviar ? alEnviar() : json(ENVIADO, 201))
    }
    if (u === '/patients/p-1/study-orders/o-1/libraview/reintentar' && metodo === 'POST') return Promise.resolve(json(ENVIADO))
    return Promise.resolve(json([]))
  }))
}

beforeEach(() => {
  pedidos = []
})

async function abrirEstudios() {
  render(
    <MemoryRouter initialEntries={['/pacientes/p-1']}>
      <Routes><Route path="/pacientes/:id" element={<PacienteFicha />} /></Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('tab', { name: 'Estudios' }))
  await screen.findByText('Dr. Ficticio Gómez')
}

const mandado = (url: string, metodo = 'POST') => pedidos.find((p) => p.url === url && p.metodo === metodo)

async function abrirElDialogo() {
  await userEvent.click(await screen.findByRole('button', { name: 'Enviar a LibraView' }))
  const dialogo = await screen.findByRole('dialog')
  // El formulario aparece cuando llegó el catálogo.
  await within(dialogo).findByLabelText('Apellido')
  return dialogo
}

describe('sin LibraView configurado', () => {
  it('la pestaña es la de siempre y no se piden los envíos', async () => {
    servir({ configurado: false })
    await abrirEstudios()
    expect(screen.queryByRole('button', { name: /LibraView/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/LibraView/)).not.toBeInTheDocument()
    expect(pedidos.some((p) => p.url.startsWith('/integraciones/libraview/envios'))).toBe(false)
  })
})

describe('Enviar a LibraView', () => {
  it('🔴 abre el diálogo ya cargado con lo que se puede deducir y manda lo que el backend espera', async () => {
    servir()
    await abrirEstudios()
    const dialogo = await abrirElDialogo()

    // Precargado: «Apellido, Nombres» de la ficha, DNI y fecha de la ficha, médico del pedido, motivos.
    expect(within(dialogo).getByLabelText('Apellido')).toHaveValue('Ficticia')
    expect(within(dialogo).getByLabelText('Nombres')).toHaveValue('Ana María')
    expect(within(dialogo).getByLabelText('DNI')).toHaveValue('99100001')
    expect(within(dialogo).getByLabelText('Fecha de nacimiento')).toHaveValue('1975-03-02')
    expect(within(dialogo).getByLabelText('Médico solicitante')).toHaveValue('Dr. Ficticio Gómez')
    expect(within(dialogo).getByLabelText('Diagnóstico presuntivo')).toHaveValue('Tos persistente')
    // La práctica del primer ítem coincide con el catálogo sin importar acentos; la del segundo («Eco abdominal») no coincide y queda sin elegir.
    expect(within(dialogo).getByRole('combobox', { name: 'Práctica para «Radiografía de tórax»' })).toHaveValue('Radiografía de tórax')
    expect(within(dialogo).getByRole('combobox', { name: 'Práctica para «Eco abdominal»' })).toHaveValue('')
    // El nombre se pudo partir: no hace falta la ayuda.
    expect(within(dialogo).queryByText(/está en un solo campo/)).not.toBeInTheDocument()

    // Falta la práctica del segundo ítem y el sexo: no se manda.
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Enviar a LibraView' }))
    expect(await within(dialogo).findByText('Elegí la práctica')).toBeInTheDocument()
    expect(within(dialogo).getByText('Elegí el sexo')).toBeInTheDocument()
    expect(mandado('/patients/p-1/study-orders/o-1/libraview')).toBeUndefined()

    // Se elige la práctica (buscando por el nombre) y el sexo.
    await userEvent.click(within(dialogo).getByRole('combobox', { name: 'Práctica para «Eco abdominal»' }))
    await userEvent.type(within(dialogo).getByRole('combobox', { name: 'Práctica para «Eco abdominal»' }), 'ecograf')
    await userEvent.click(await screen.findByRole('option', { name: /Ecografía abdominal/ }))
    await userEvent.click(within(dialogo).getByRole('combobox', { name: 'Sexo' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Femenino' }))
    await userEvent.type(within(dialogo).getByLabelText('Matrícula'), 'MP 99999')

    await userEvent.click(within(dialogo).getByRole('button', { name: 'Enviar a LibraView' }))
    await waitFor(() => expect(mandado('/patients/p-1/study-orders/o-1/libraview')).toBeDefined())
    expect(mandado('/patients/p-1/study-orders/o-1/libraview')?.cuerpo).toEqual({
      items: [
        { item_id: 'i-1', codigo_practica: 'RX-TORAX' },
        { item_id: 'i-2', codigo_practica: 'ECO-ABD' },
      ],
      paciente: {
        apellido: 'Ficticia', nombres: 'Ana María', sexo: 'F', numero_documento: '99100001', fecha_nacimiento: '1975-03-02',
      },
      medico_solicitante: 'Dr. Ficticio Gómez',
      matricula_solicitante: 'MP 99999',
      diagnostico_presuntivo: 'Tos persistente',
      prioridad: 'rutina',
    })
    // Se cierra y se vuelven a pedir los envíos.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(pedidos.filter((p) => p.url === '/integraciones/libraview/envios?patient_id=p-1').length).toBeGreaterThan(1))
  })

  it('si la ficha tiene el nombre en un solo campo, apellido y nombres quedan vacíos y se muestra el nombre completo como ayuda', async () => {
    servir({ paciente: { ...PACIENTE, name: 'Ana María Ficticia' } })
    await abrirEstudios()
    const dialogo = await abrirElDialogo()
    expect(within(dialogo).getByLabelText('Apellido')).toHaveValue('')
    expect(within(dialogo).getByLabelText('Nombres')).toHaveValue('')
    expect(within(dialogo).getByText(/«Ana María Ficticia»/)).toBeInTheDocument()
  })

  it('🔴 sin DNI o sin fecha de nacimiento en la ficha el diálogo los pide y no manda hasta tenerlos', async () => {
    servir({ paciente: { ...PACIENTE, dni: null, birth_date: null } })
    await abrirEstudios()
    const dialogo = await abrirElDialogo()
    expect(within(dialogo).getByLabelText('DNI')).toHaveValue('')
    expect(within(dialogo).getByLabelText('Fecha de nacimiento')).toHaveValue('')

    await userEvent.click(within(dialogo).getByRole('button', { name: 'Enviar a LibraView' }))
    expect(await within(dialogo).findByText('El documento es obligatorio')).toBeInTheDocument()
    expect(within(dialogo).getByText('La fecha de nacimiento es obligatoria')).toBeInTheDocument()
    expect(mandado('/patients/p-1/study-orders/o-1/libraview')).toBeUndefined()

    await userEvent.type(within(dialogo).getByLabelText('DNI'), '12')
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Enviar a LibraView' }))
    expect(await within(dialogo).findByText('El DNI tiene entre 6 y 9 dígitos')).toBeInTheDocument()
  })

  it('un rechazo del servidor se dice dentro del diálogo y no pierde lo cargado', async () => {
    servir({ alEnviar: () => json({ detail: 'Hay que elegir una práctica por cada ítem del pedido.' }, 422) })
    await abrirEstudios()
    const dialogo = await abrirElDialogo()
    await userEvent.click(within(dialogo).getByRole('combobox', { name: 'Práctica para «Eco abdominal»' }))
    await userEvent.type(within(dialogo).getByRole('combobox', { name: 'Práctica para «Eco abdominal»' }), 'ecograf')
    await userEvent.click(await screen.findByRole('option', { name: /Ecografía abdominal/ }))
    await userEvent.click(within(dialogo).getByRole('combobox', { name: 'Sexo' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Otro' }))
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Enviar a LibraView' }))

    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('Hay que elegir una práctica por cada ítem del pedido.')
    expect(within(dialogo).getByLabelText('Apellido')).toHaveValue('Ficticia')
  })
})

describe('cómo se ve un pedido ya mandado', () => {
  it('enviado: «En LibraView» y el N.º de acceso de cada ítem, sin botón de enviar', async () => {
    servir({ envios: [ENVIADO] })
    await abrirEstudios()
    expect(await screen.findByText('En LibraView')).toBeInTheDocument()
    expect(screen.getByText(/N\.º de acceso 202600000051/)).toBeInTheDocument()
    expect(screen.getByText(/N\.º de acceso 202600000052/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Enviar a LibraView' })).not.toBeInTheDocument()
  })

  it('con error: el badge, el mensaje y «Reintentar», que reenvía sin pedir los datos de nuevo', async () => {
    servir({ envios: [CON_ERROR] })
    await abrirEstudios()
    expect(await screen.findByText('Error en LibraView')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('503: en mantenimiento')
    expect(screen.getByRole('alert')).toHaveTextContent('2 intentos')
    expect(screen.queryByText(/N\.º de acceso/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(mandado('/patients/p-1/study-orders/o-1/libraview/reintentar')).toBeDefined())
    // El reintento no manda datos: el servidor reenvía el cuerpo que guardó.
    expect(mandado('/patients/p-1/study-orders/o-1/libraview/reintentar')?.cuerpo ?? {}).toEqual({})
  })

  it('con error también se puede corregir y reenviar desde el diálogo', async () => {
    servir({ envios: [CON_ERROR] })
    await abrirEstudios()
    await userEvent.click(await screen.findByRole('button', { name: 'Corregir y reenviar' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})

describe('lo puro', () => {
  it('normalizar saca mayúsculas, acentos y espacios de más', () => {
    expect(normalizar('  Radiografía   de TÓRAX ')).toBe('radiografia de torax')
  })

  it('la práctica sugerida coincide por nombre o por código y nunca por parecido', () => {
    expect(practicaSugerida('radiografia de torax', CATALOGO)).toBe('RX-TORAX')
    expect(practicaSugerida('eco-abd', CATALOGO)).toBe('ECO-ABD')
    expect(practicaSugerida('Radiografía', CATALOGO)).toBe('')
    expect(practicaSugerida('', CATALOGO)).toBe('')
  })

  it('el nombre se parte sólo si trae coma', () => {
    expect(partirNombre('Ficticia, Ana María')).toEqual({ apellido: 'Ficticia', nombres: 'Ana María', partido: true })
    expect(partirNombre('Ficticia,Ana')).toEqual({ apellido: 'Ficticia', nombres: 'Ana', partido: true })
    expect(partirNombre('Ana María Ficticia')).toEqual({ apellido: '', nombres: '', partido: false })
  })
})
