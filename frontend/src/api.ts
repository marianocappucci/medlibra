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

async function postFormData<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: 'POST', credentials: 'include', body: form })
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
  // Multipart, para subir documentos clinicos -- unica excepcion al resto
  // de la API que es JSON puro (ver app/routers/clinical_documents.py).
  postForm: postFormData,
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

// Dominio clínico: todo append-only -- crear/listar/borrar (admin-only),
// sin edición. Ver app/routers/{clinical_notes,prescriptions,study_orders,
// consents,clinical_documents}.py.

export type ClinicalNote = {
  id: string
  patient_id: string
  created_at: string
  author: string
  text: string
}

export type PrescriptionItem = {
  id: string
  medication: string
  dosage: string
  instructions: string | null
}

export type Prescription = {
  id: string
  patient_id: string
  created_at: string
  author: string
  items: PrescriptionItem[]
}

export type StudyResult = {
  id: string
  item_id: string
  created_at: string
  author: string
  text: string
}

export type StudyOrderItem = {
  id: string
  study_type: string
  reason: string | null
  results: StudyResult[]
}

export type StudyOrder = {
  id: string
  patient_id: string
  created_at: string
  author: string
  items: StudyOrderItem[]
}

export type Consent = {
  id: string
  patient_id: string
  created_at: string
  author: string
  procedure: string
  granted_by: string
  text: string
}

export type ClinicalDocument = {
  id: string
  patient_id: string
  created_at: string
  author: string
  title: string
  description: string | null
  original_filename: string
  content_type: string | null
  size_bytes: number
}
