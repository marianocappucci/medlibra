// El ID del paciente es opcional: «se genera solo si lo dejás vacío» (ADR-071).
//
// Hasta el 2026-10-16 el formulario de Pacientes exigía un ID que tipeaba el usuario. Ahora el backend genera el
// número (`p-001`...) cuando el POST no trae `id`; con `id` lo respeta, como siempre. Lo que se mide es el cuerpo
// del POST: un `id: ''` mandado "por las dudas" es un 422 del backend, no un alta automática.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { Pacientes } from '../pages/Pacientes'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', username: 'ana', name: 'Ana', role: 'admin', active: true },
    loading: false, login: vi.fn(), logout: vi.fn(),
  }),
}))

let pedidos: { url: string; metodo: string; cuerpo: Record<string, unknown> | null }[]

beforeEach(() => {
  pedidos = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    pedidos.push({
      url: String(url), metodo: init?.method ?? 'GET',
      cuerpo: init?.body ? JSON.parse(String(init.body)) : null,
    })
    const cuerpo = init?.method === 'POST' ? { id: 'p-001' } : []
    return Promise.resolve(new Response(JSON.stringify(cuerpo), {
      status: init?.method === 'POST' ? 201 : 200, headers: { 'content-type': 'application/json' },
    }))
  }))
})

async function abrirAlta() {
  render(<MemoryRouter><Pacientes /></MemoryRouter>)
  await userEvent.click(await screen.findByRole('button', { name: /Nuevo paciente/ }))
  await screen.findByText('Se genera solo si lo dejás vacío.')
}

const alta = () => pedidos.find((p) => p.url === '/patients' && p.metodo === 'POST')

it('🔴 con el ID vacío crea el paciente y el POST no lleva id', async () => {
  await abrirAlta()
  await userEvent.type(screen.getByLabelText('Nombre'), 'Ana Prueba')
  await userEvent.click(screen.getByRole('button', { name: 'Crear' }))

  await waitFor(() => expect(alta()).toBeDefined())
  expect(alta()?.cuerpo).not.toHaveProperty('id')
  expect(alta()?.cuerpo).toMatchObject({ name: 'Ana Prueba' })
})

it('con un ID escrito lo manda tal cual (compatibilidad)', async () => {
  await abrirAlta()
  await userEvent.type(screen.getByLabelText('ID'), 'legajo-77')
  await userEvent.type(screen.getByLabelText('Nombre'), 'Ana Prueba')
  await userEvent.click(screen.getByRole('button', { name: 'Crear' }))

  await waitFor(() => expect(alta()?.cuerpo).toMatchObject({ id: 'legajo-77', name: 'Ana Prueba' }))
})
