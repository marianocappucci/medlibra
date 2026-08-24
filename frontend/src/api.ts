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
import type { OpcionSelect } from 'libra-ui/SelectBuscable'

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

/** Una sede. **El `timezone` no es decorativo**: es el huso en el que el
 *  backend valida y guarda los turnos (ADR-028), y por lo tanto el único con el
 *  que la agenda puede decir a qué día y a qué hora pertenece cada turno. Un
 *  turno de las 21:30 del lunes en Buenos Aires viaja como `2026-07-21T00:30Z`;
 *  leído con el huso del navegador, cada usuario lo pondría en un día distinto. */
export type Branch = {
  id: string
  name: string
  active: boolean
  timezone: string
  phone: string | null
  address: string | null
}

export type Service = {
  id: string
  name: string
  duration_minutes: number
  active: boolean
}

/** La sala física donde se atiende. **No es un `Resource`**: el motor asocia el
 *  turno a un solo recurso —el profesional— y la ocupación de la sala la valida
 *  MedLibra aparte (ADR-030). */
export type Consultorio = {
  id: string
  name: string
  branch_id: string | null
  active: boolean
}

export const DIAS_SEMANA = [
  'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo',
] as const

/** Una franja semanal: día + rango horario, en hora de pared de la sede. Es la
 *  forma del horario de atención (`/branches/{id}/hours`). */
export type VentanaSemanal = {
  id: number
  weekday: number
  starts_at: string
  ends_at: string
}

/** Un bloque de agenda: *"los lunes de 9 a 13 en el Consultorio 2, turnos de 20
 *  minutos, hasta el 31 de diciembre"*. Ver ADR-030. */
export type BloqueDeAgenda = {
  id: string
  resource_id: string
  consultorio_id: string
  weekday: number
  starts_at: string
  ends_at: string
  valid_from: string
  /** `null` = se repite indefinidamente. */
  valid_to: string | null
  slot_minutes: number
  modality: 'turnos' | 'espontanea'
}

/** Lo que el backend ofrece elegir. **Sale de la API y no de una constante acá**:
 *  la lista de duraciones es la que el alta valida, y dos copias divergen — la
 *  pantalla terminaría ofreciendo un valor que el alta rechaza con 422. */
export type OpcionesDeBloque = {
  duraciones: number[]
  modalidades: string[]
}

/** Un rato puntual en el que el profesional no atiende. Se carga en hora de
 *  pared de la sede y **se guarda como instante**; vuelve en UTC. */
export type Bloqueo = {
  id: number
  resource_id: string
  starts_at: string
  ends_at: string
  reason: string
}

/** Un día concreto que se cierra o se abre. **Le gana a la jornada**, en las dos
 *  direcciones. */
export type ExcepcionDeAgenda = {
  id: number
  resource_id: string
  day: string
  starts_at: string
  ends_at: string
  available: boolean
}

export type PrecioDeServicio = {
  id: string
  service_id: string
  branch_id: string
  price: string
}

/** El honorario: lo que sale una prestación con **un profesional concreto**.
 *
 *  **Pisa** al precio de la sede cuando existe, y sacarlo devuelve la prestación
 *  a ese precio de lista en vez de dejarla sin precio. */
export type Honorario = {
  id: string
  service_id: string
  resource_id: string
  price: string
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

// --- opciones para los selects con busqueda (libra-ui/SelectBuscable) ------
//
// Viven aca, junto a los tipos, para que toda pantalla que elija un paciente
// o un servicio lo muestre y lo busque igual. El `hint` no es decorativo:
// ademas de desambiguar dos nombres parecidos, **entra en la busqueda**.
//
// En un centro medico el DNI es el mejor discriminador -- es lo que trae el
// paciente y lo que figura en la orden -- y el telefono es lo que se tiene a
// mano cuando llama para sacar turno. Los dos entran en la busqueda.

export function opcionesPaciente(pacientes: Patient[]): OpcionSelect[] {
  return pacientes.map((p) => ({
    value: p.id,
    label: p.name,
    hint: [p.dni, p.phone, p.active ? null : 'inactivo']
      .filter(Boolean).join(' · ') || undefined,
  }))
}

export function opcionesServicio(servicios: Service[]): OpcionSelect[] {
  return servicios.map((s) => ({
    value: s.id,
    label: s.name,
    // La duracion es lo que distingue dos prestaciones de nombre parecido
    // ("Consulta" de 20 y "Consulta primera vez" de 40) al armar la agenda.
    hint: `${s.duration_minutes} min`,
  }))
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

// 🔴 Acá vivían `ArcaConfig`, `Factura` y `TIPO_COMPROBANTE_LABELS`. Se fueron
// con el motor de facturación local (ADR-036): **este producto ya no factura**,
// la contabilidad vive en Contalibra. No queda ningún tipo de comprobante
// porque no hay comprobante que MedLibra emita.

/** Cómo le fue a la consulta camino a Contalibra.
 *
 *  `sin_destino` **no es un fallo del otro lado**: es que no hay otro lado
 *  configurado (falta `CONTALIBRA_URL`). Se distingue de `error` porque el
 *  arreglo es distinto — configurar, no reintentar contra algo que falló. */
export type EnvioAContalibra = {
  appointment_id: string
  estado: 'pendiente' | 'enviado' | 'error' | 'sin_destino'
  venta_id: number | null
  error: string
  intentos: number
  actualizado: string
}

export type CompleteAppointmentResponse = {
  id: string
  status: AppointmentStatus
  /** `null` cuando el turno no tenía precio, o el módulo está apagado. */
  contalibra: EnvioAContalibra | null
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
