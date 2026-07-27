// Cliente HTTP delgado sobre la API de MedLibra. Cookie de sesion
// (ml_session) manejada por el browser via `credentials: "include"` --
// en dev el proxy de Vite (vite.config.ts) mantiene todo en el mismo
// origen (localhost:5173) para que la cookie funcione sin CORS; en
// produccion el build de este frontend se sirve desde el mismo proceso
// FastAPI (ver app/asgi.py), tambien mismo origen. Mismo patron que
// Gestiolibra (ver wiki/entities/gestiolibra.md, ADR-019 de ese repo).
//
// El cliente base (ApiError/request/get/post/put/del) y el tipo User
// viven en libra-ui/api-client desde el 2026-07-26 (era byte-idéntico en
// Gestiolibra/MedLibra/VentaLibra -- ver
// wiki/analyses/auditoria-duplicacion-familia-libra.md). `postForm` es
// específico de MedLibra (documentos clínicos), se suma acá encima del
// objeto base.
import { api as baseApi, ApiError, type User } from 'libra-ui/api-client'

export { ApiError, type User }

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
  ...baseApi,
  // Multipart, para subir documentos clinicos -- unica excepcion al resto
  // de la API que es JSON puro (ver app/routers/clinical_documents.py).
  postForm: postFormData,
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

// Facturación: instancia única por cliente (una sola "empresa" ARCA fija,
// ver app/services/billing.py), sin lista de empresas para elegir a
// diferencia de Contalibra/Restolibra.
export type ArcaConfig = {
  empresa: string
  cuit: string
  punto_venta: number
  ambiente: string
  certificado_path: string
  clave_path: string
}

export type Factura = {
  id: number
  tipo: number
  punto_venta: number
  numero: number
  fecha: string
  cliente_cuit: string
  cliente_razon: string
  total: number
  cae: string
  cae_vto: string
}

// Solo A/B: MedLibra emite tipo A si el paciente es Responsable
// Inscripto, B en cualquier otro caso (ver app/services/billing.py).
export const TIPO_COMPROBANTE_LABELS: Record<number, string> = {
  1: 'Factura A',
  6: 'Factura B',
}

export type CompleteAppointmentResponse = {
  id: string
  status: AppointmentStatus
  factura: Factura | null
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

// Dashboard: resumen de lectura pura, admin-only y gateado por el módulo
// "dashboard" del plan (ver app/services/dashboard.py). Sin facturación/
// caja (fuera del primer corte, a diferencia de Gestiolibra).
export type DashboardSummary = {
  date_from: string
  date_to: string
  turnos: {
    total_en_periodo: number
    por_estado: Record<AppointmentStatus, number>
    hoy: number
  }
  pacientes: {
    total_activos: number
    nuevos_en_periodo: number
  }
  recordatorios_enviados_en_periodo: number
  senas_pendientes: number
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
