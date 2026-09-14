// Adopción del router de usuarios de libraauth (ADR-018, v0.43.0/v0.71.0):
// el backend ya trae `DELETE /users/{id}` con las guardas del único admin y
// de uno mismo, así que el shim de este producto (`pages/Usuarios.tsx`) pasa
// `permitirEliminar` y `usuarioActualId` a la pantalla compartida.
//
// Lo que fija este archivo es que esas dos props llegan bien conectadas
// desde ESTE producto -- la lógica del botón (por qué se oculta, el diálogo
// de confirmación, el DELETE real) ya la prueba `libra-ui` en su propia
// suite, y repetirla acá sería medir lo mismo dos veces.
import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { Usuarios } from '../pages/Usuarios'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', name: 'Admin', role: 'admin', active: true },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

const USUARIOS = [
  { id: 'u1', username: 'admin', name: 'Admin', role: 'admin', active: true, email: '' },
  { id: 'u2', username: 'staff-1', name: 'Dr. Perez', role: 'staff', active: true, email: '' },
]

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const cuerpo = String(url).includes('/users') ? USUARIOS : []
    return Promise.resolve(new Response(JSON.stringify(cuerpo), {
      status: 200, headers: { 'content-type': 'application/json' },
    }))
  }))
})

it('ofrece Eliminar en la fila ajena y lo oculta en la propia', async () => {
  render(<Usuarios />)
  await screen.findByText('Dr. Perez')

  expect(screen.getByRole('button', { name: 'Eliminar Dr. Perez' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Eliminar Admin' })).not.toBeInTheDocument()
})
