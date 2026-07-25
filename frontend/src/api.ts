// Cliente HTTP delgado sobre la API de MedLibra. Cookie de sesion
// (ml_session) manejada por el browser via `credentials: "include"` --
// en dev el proxy de Vite (vite.config.ts) mantiene todo en el mismo
// origen (localhost:5173) para que la cookie funcione sin CORS; en
// produccion el build de este frontend se sirve desde el mismo proceso
// FastAPI (ver app/asgi.py), tambien mismo origen. Mismo patron que
// Gestiolibra (ver wiki/entities/gestiolibra.md, ADR-019 de ese repo).

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 204) {
    return undefined as T
  }

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json() : undefined

  if (!response.ok) {
    const detail = (data && typeof data === 'object' && 'detail' in data)
      ? String((data as { detail: unknown }).detail)
      : response.statusText
    throw new ApiError(response.status, detail)
  }

  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

export type User = {
  id: string
  username: string
  name: string
  role: 'admin' | 'staff'
  active: boolean
}

export type Resource = {
  id: string
  name: string
  branch_id: string | null
  active: boolean
}

export type Service = {
  id: string
  name: string
  duration_minutes: number
  active: boolean
}

export type Patient = {
  id: string
  name: string
  phone: string | null
  email: string | null
  active: boolean
  dni: string | null
  birth_date: string | null
  cuit: string | null
  condicion_iva: string | null
}

export type AppointmentStatus =
  | 'pending' | 'confirmed' | 'in_progress' | 'completed' | 'cancelled' | 'no_show'

export const STATUS_LABELS: Record<AppointmentStatus, string> = {
  pending: 'Pendiente',
  confirmed: 'Confirmado',
  in_progress: 'En curso',
  completed: 'Completado',
  cancelled: 'Cancelado',
  no_show: 'No se presentó',
}

export type Appointment = {
  id: string
  resource_id: string
  service_id: string
  client_id: string
  starts_at: string
  ends_at: string
  status: AppointmentStatus
}
