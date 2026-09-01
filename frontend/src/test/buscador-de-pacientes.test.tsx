// El módulo de pacientes no tenía con qué buscar.
//
// La tabla no pagina —`DataTable` no arma row model de paginación—, así que
// con cientos de pacientes la única forma de llegar a uno era scrollear. El
// buscador existe en `libra-ui/data-table` desde su v0.8.0: lo que faltaba
// acá era pasarle la prop, y eso es lo que fija este archivo.
//
// Se prueba por lo que hace quien atiende el mostrador: teclea el nombre o el
// DNI que le están dictando y las filas que no coinciden dejan de estar. El
// CUIT vale doble como control: **no es columna de esta tabla**, así que si
// alguien recorta `campos` a lo que se ve, esto se pone rojo.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { Pacientes } from '../pages/Pacientes'

// La pantalla sólo le pregunta al contexto si el usuario es admin (para el
// botón de eliminar). Se mockea el shim en vez de montar el `AuthProvider`
// entero: ese trae además el gate de Términos, que pediría su propio endpoint
// y no tiene nada que ver con lo que se está probando.
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', username: 'ana', name: 'Ana', role: 'admin', active: true },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

const PACIENTES = [
  {
    id: 'p1', name: 'María Fernández', phone: '2324441122',
    email: 'maria@ejemplo.com.ar', active: true, dni: '30999999',
    birth_date: '1985-04-12', cuit: '27309999995', condicion_iva: 'Consumidor Final',
  },
  {
    id: 'p2', name: 'Julián Gómez', phone: '1155667788',
    email: 'julian@ejemplo.com.ar', active: true, dni: '20111111',
    birth_date: '1990-11-03', cuit: '20201111112', condicion_iva: 'Monotributista',
  },
  {
    id: 'p3', name: 'Ana Ruiz', phone: null,
    email: null, active: true, dni: null,
    birth_date: null, cuit: null, condicion_iva: null,
  },
]

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const cuerpo = String(url).includes('/patients') ? PACIENTES : []
    return Promise.resolve(new Response(JSON.stringify(cuerpo), {
      status: 200, headers: { 'content-type': 'application/json' },
    }))
  }))
})

/** Monta y espera a que la carga inicial termine: antes de eso la tarjeta dice
 *  "Cargando…" y no hay tabla que mirar. */
async function montar() {
  const usuario = userEvent.setup()
  render(<MemoryRouter><Pacientes /></MemoryRouter>)
  await screen.findByText('María Fernández')
  return usuario
}

const buscador = () => screen.getByRole('searchbox', { name: 'Buscar paciente' })

it('filtra la lista por nombre', async () => {
  const usuario = await montar()
  await usuario.type(buscador(), 'ruiz')

  expect(screen.getByText('Ana Ruiz')).toBeInTheDocument()
  expect(screen.queryByText('María Fernández')).not.toBeInTheDocument()
  expect(screen.queryByText('Julián Gómez')).not.toBeInTheDocument()
})

it('filtra por DNI, que es lo que se dicta en el mostrador', async () => {
  const usuario = await montar()
  await usuario.type(buscador(), '20111111')

  expect(screen.getByText('Julián Gómez')).toBeInTheDocument()
  expect(screen.queryByText('María Fernández')).not.toBeInTheDocument()
})

// El CUIT NO es columna de esta tabla: si sólo se buscara lo que se ve, esta
// consulta no encontraría nada.
it('filtra por CUIT aunque no sea columna', async () => {
  const usuario = await montar()
  await usuario.type(buscador(), '27309999995')

  expect(screen.getByText('María Fernández')).toBeInTheDocument()
  expect(screen.queryByText('Julián Gómez')).not.toBeInTheDocument()
})

// Los nombres se cargan a mano y con acentos; nadie los teclea al buscar.
it('encuentra sin acentos', async () => {
  const usuario = await montar()
  await usuario.type(buscador(), 'julian gomez')

  expect(screen.getByText('Julián Gómez')).toBeInTheDocument()
  expect(screen.queryByText('Ana Ruiz')).not.toBeInTheDocument()
})

// Buscar y no encontrar no es lo mismo que no tener pacientes: el mensaje de
// vacío de la página haría pensar que se perdieron.
it('avisa que no hay resultados, no que no hay pacientes', async () => {
  const usuario = await montar()
  await usuario.type(buscador(), 'zzz')

  expect(screen.getByText(/Sin resultados para/)).toBeInTheDocument()
  expect(screen.queryByText('Sin pacientes todavía.')).not.toBeInTheDocument()
})
