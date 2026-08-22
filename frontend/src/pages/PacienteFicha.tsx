import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { zodResolver } from '@hookform/resolvers/zod'
import { useFieldArray, useForm } from 'react-hook-form'
import { z } from 'zod'
import {
  api, ApiError,
  type ClinicalDocument, type ClinicalNote, type Consent, type Patient,
  type Prescription, type StudyOrder,
} from '../api'
import { useAuth } from '../context/AuthContext'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Users } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

// dd-mm-aaaa HH:MM (regla del 2026-08-12). Se arma por partes en vez de
// devolver el string de `toLocaleString`, que usa barra y mete una coma entre
// la fecha y la hora.
function formatDateTime(iso: string): string {
  const partes = new Intl.DateTimeFormat('es-AR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const p: Record<string, string> = {}
  for (const parte of partes) p[parte.type] = parte.value
  return `${p.day}-${p.month}-${p.year} ${p.hour}:${p.minute}`
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ── Historia clínica ─────────────────────────────────────────────────────

const noteSchema = z.object({
  author: z.string().trim().min(1, 'El autor es obligatorio'),
  text: z.string().trim().min(1, 'El texto es obligatorio'),
})
type NoteFormValues = z.infer<typeof noteSchema>

function NotesSection({ patientId, isAdmin }: { patientId: string; isAdmin: boolean }) {
  const { user } = useAuth()
  const [notes, setNotes] = useState<ClinicalNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const form = useForm<NoteFormValues>({
    resolver: zodResolver(noteSchema),
    defaultValues: { author: user?.name ?? '', text: '' },
  })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<ClinicalNote[]>(`/patients/${patientId}/notes`)
      setNotes(items.sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: NoteFormValues) {
    setSaving(true)
    setError(null)
    try {
      await api.post(`/patients/${patientId}/notes`, values)
      form.reset({ author: values.author, text: '' })
      await load()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(note: ClinicalNote) {
    setError(null)
    try {
      await api.del(`/patients/${patientId}/notes/${note.id}`)
      await load()
    } catch (err) {
      setError(describeError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Nueva nota de evolución</CardTitle></CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="grid gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
              <FormField
                control={form.control}
                name="author"
                render={({ field }) => (
                  <FormItem className="max-w-xs">
                    <FormLabel>Autor</FormLabel>
                    <FormControl><Input {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="text"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Nota</FormLabel>
                    <FormControl><Textarea rows={3} {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div><Button type="submit" disabled={saving}>{saving ? 'Guardando…' : 'Agregar nota'}</Button></div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : notes.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin notas todavía.</p>
      ) : (
        <div className="grid gap-3">
          {notes.map((note) => (
            <Card key={note.id}>
              <CardContent className="pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{note.author}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(note.created_at)}</p>
                  </div>
                  {isAdmin && (
                    <Button size="sm" variant="outline" onClick={() => handleDelete(note)}>Eliminar</Button>
                  )}
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{note.text}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Recetas ───────────────────────────────────────────────────────────────

const prescriptionItemSchema = z.object({
  medication: z.string().trim().min(1, 'Medicamento obligatorio'),
  dosage: z.string().trim().min(1, 'Dosis obligatoria'),
  instructions: z.string().trim().optional(),
})
const prescriptionSchema = z.object({
  author: z.string().trim().min(1, 'El autor es obligatorio'),
  items: z.array(prescriptionItemSchema).min(1, 'Agregá al menos un ítem'),
})
type PrescriptionFormValues = z.infer<typeof prescriptionSchema>

const EMPTY_PRESCRIPTION_ITEM = { medication: '', dosage: '', instructions: '' }

function PrescriptionsSection({ patientId, isAdmin }: { patientId: string; isAdmin: boolean }) {
  const { user } = useAuth()
  const [prescriptions, setPrescriptions] = useState<Prescription[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const form = useForm<PrescriptionFormValues>({
    resolver: zodResolver(prescriptionSchema),
    defaultValues: { author: user?.name ?? '', items: [EMPTY_PRESCRIPTION_ITEM] },
  })
  const { fields, append, remove } = useFieldArray({ control: form.control, name: 'items' })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<Prescription[]>(`/patients/${patientId}/prescriptions`)
      setPrescriptions(items.sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: PrescriptionFormValues) {
    setSaving(true)
    setError(null)
    try {
      await api.post(`/patients/${patientId}/prescriptions`, {
        author: values.author,
        items: values.items.map((item) => ({ ...item, instructions: item.instructions || null })),
      })
      form.reset({ author: values.author, items: [EMPTY_PRESCRIPTION_ITEM] })
      await load()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(prescription: Prescription) {
    setError(null)
    try {
      await api.del(`/patients/${patientId}/prescriptions/${prescription.id}`)
      await load()
    } catch (err) {
      setError(describeError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Nueva receta</CardTitle></CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="grid gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
              <FormField
                control={form.control}
                name="author"
                render={({ field }) => (
                  <FormItem className="max-w-xs">
                    <FormLabel>Autor</FormLabel>
                    <FormControl><Input {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="grid gap-2">
                {fields.map((item, index) => (
                  <div key={item.id} className="flex flex-wrap items-start gap-2">
                    <FormField
                      control={form.control}
                      name={`items.${index}.medication`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Medicamento</FormLabel>
                          <FormControl><Input {...field} className="w-44" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`items.${index}.dosage`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Dosis</FormLabel>
                          <FormControl><Input {...field} className="w-32" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`items.${index}.instructions`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Indicaciones</FormLabel>
                          <FormControl><Input {...field} className="w-52" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <Button
                      type="button" variant="outline" size="sm" className="mt-6"
                      disabled={fields.length === 1}
                      onClick={() => remove(index)}
                    >
                      Quitar
                    </Button>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => append(EMPTY_PRESCRIPTION_ITEM)}>
                  + Agregar ítem
                </Button>
                <Button type="submit" disabled={saving}>{saving ? 'Guardando…' : 'Crear receta'}</Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : prescriptions.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin recetas todavía.</p>
      ) : (
        <div className="grid gap-3">
          {prescriptions.map((prescription) => (
            <Card key={prescription.id}>
              <CardContent className="pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{prescription.author}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(prescription.created_at)}</p>
                  </div>
                  {isAdmin && (
                    <Button size="sm" variant="outline" onClick={() => handleDelete(prescription)}>Eliminar</Button>
                  )}
                </div>
                <ul className="mt-2 space-y-1 text-sm">
                  {prescription.items.map((item) => (
                    <li key={item.id}>
                      <span className="font-medium">{item.medication}</span> — {item.dosage}
                      {item.instructions ? ` (${item.instructions})` : ''}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Estudios ──────────────────────────────────────────────────────────────

const studyOrderItemSchema = z.object({
  study_type: z.string().trim().min(1, 'Tipo de estudio obligatorio'),
  reason: z.string().trim().optional(),
})
const studyOrderSchema = z.object({
  author: z.string().trim().min(1, 'El autor es obligatorio'),
  items: z.array(studyOrderItemSchema).min(1, 'Agregá al menos un ítem'),
})
type StudyOrderFormValues = z.infer<typeof studyOrderSchema>

const EMPTY_STUDY_ITEM = { study_type: '', reason: '' }

function AddResultForm({
  patientId, orderId, itemId, onAdded,
}: { patientId: string; orderId: string; itemId: string; onAdded: () => void }) {
  const { user } = useAuth()
  const [author, setAuthor] = useState(user?.name ?? '')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.post(`/patients/${patientId}/study-orders/${orderId}/items/${itemId}/results`, { author, text })
      setText('')
      onAdded()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={handleSubmit}>
      <div className="grid gap-1">
        <Label className="text-xs">Autor</Label>
        <Input value={author} onChange={(e) => setAuthor(e.target.value)} className="h-8 w-36" />
      </div>
      <div className="grid gap-1">
        <Label className="text-xs">Resultado</Label>
        <Input value={text} onChange={(e) => setText(e.target.value)} className="h-8 w-64" />
      </div>
      <Button type="submit" size="sm" disabled={saving || !author.trim() || !text.trim()}>
        {saving ? 'Guardando…' : 'Agregar resultado'}
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </form>
  )
}

function StudyOrdersSection({ patientId, isAdmin }: { patientId: string; isAdmin: boolean }) {
  const { user } = useAuth()
  const [orders, setOrders] = useState<StudyOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const form = useForm<StudyOrderFormValues>({
    resolver: zodResolver(studyOrderSchema),
    defaultValues: { author: user?.name ?? '', items: [EMPTY_STUDY_ITEM] },
  })
  const { fields, append, remove } = useFieldArray({ control: form.control, name: 'items' })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<StudyOrder[]>(`/patients/${patientId}/study-orders`)
      setOrders(items.sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: StudyOrderFormValues) {
    setSaving(true)
    setError(null)
    try {
      await api.post(`/patients/${patientId}/study-orders`, {
        author: values.author,
        items: values.items.map((item) => ({ ...item, reason: item.reason || null })),
      })
      form.reset({ author: values.author, items: [EMPTY_STUDY_ITEM] })
      await load()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(order: StudyOrder) {
    setError(null)
    try {
      await api.del(`/patients/${patientId}/study-orders/${order.id}`)
      await load()
    } catch (err) {
      setError(describeError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Nuevo pedido de estudios</CardTitle></CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="grid gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
              <FormField
                control={form.control}
                name="author"
                render={({ field }) => (
                  <FormItem className="max-w-xs">
                    <FormLabel>Autor</FormLabel>
                    <FormControl><Input {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="grid gap-2">
                {fields.map((item, index) => (
                  <div key={item.id} className="flex flex-wrap items-start gap-2">
                    <FormField
                      control={form.control}
                      name={`items.${index}.study_type`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Tipo de estudio</FormLabel>
                          <FormControl><Input {...field} className="w-52" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`items.${index}.reason`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Motivo</FormLabel>
                          <FormControl><Input {...field} className="w-52" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <Button
                      type="button" variant="outline" size="sm" className="mt-6"
                      disabled={fields.length === 1}
                      onClick={() => remove(index)}
                    >
                      Quitar
                    </Button>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => append(EMPTY_STUDY_ITEM)}>
                  + Agregar ítem
                </Button>
                <Button type="submit" disabled={saving}>{saving ? 'Guardando…' : 'Crear pedido'}</Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : orders.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin pedidos de estudios todavía.</p>
      ) : (
        <div className="grid gap-3">
          {orders.map((order) => (
            <Card key={order.id}>
              <CardContent className="pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{order.author}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(order.created_at)}</p>
                  </div>
                  {isAdmin && (
                    <Button size="sm" variant="outline" onClick={() => handleDelete(order)}>Eliminar</Button>
                  )}
                </div>
                <div className="mt-3 grid gap-3">
                  {order.items.map((item) => (
                    <div key={item.id} className="rounded-md border p-3">
                      <p className="text-sm font-medium">
                        {item.study_type}{item.reason ? ` — ${item.reason}` : ''}
                      </p>
                      {item.results.length > 0 && (
                        <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
                          {item.results.map((result) => (
                            <li key={result.id}>
                              <span className="font-medium text-foreground">{result.author}</span>
                              {' '}({formatDateTime(result.created_at)}): {result.text}
                            </li>
                          ))}
                        </ul>
                      )}
                      <AddResultForm
                        patientId={patientId} orderId={order.id} itemId={item.id} onAdded={load}
                      />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Documentos clínicos ───────────────────────────────────────────────────

const documentSchema = z.object({
  author: z.string().trim().min(1, 'El autor es obligatorio'),
  title: z.string().trim().min(1, 'El título es obligatorio'),
  description: z.string().trim().optional(),
})
type DocumentFormValues = z.infer<typeof documentSchema>

function DocumentsSection({ patientId, isAdmin }: { patientId: string; isAdmin: boolean }) {
  const { user } = useAuth()
  const [documents, setDocuments] = useState<ClinicalDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [file, setFile] = useState<File | null>(null)

  const form = useForm<DocumentFormValues>({
    resolver: zodResolver(documentSchema),
    defaultValues: { author: user?.name ?? '', title: '', description: '' },
  })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<ClinicalDocument[]>(`/patients/${patientId}/documents`)
      setDocuments(items.sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: DocumentFormValues) {
    if (!file) {
      setError('Elegí un archivo para subir.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('author', values.author)
      formData.append('title', values.title)
      if (values.description) formData.append('description', values.description)
      formData.append('file', file)
      await api.postForm(`/patients/${patientId}/documents`, formData)
      form.reset({ author: values.author, title: '', description: '' })
      setFile(null)
      await load()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(document: ClinicalDocument) {
    setError(null)
    try {
      await api.del(`/patients/${patientId}/documents/${document.id}`)
      await load()
    } catch (err) {
      setError(describeError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nuevo documento</CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="flex flex-wrap items-start gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
              <FormField
                control={form.control}
                name="author"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Autor</FormLabel>
                    <FormControl><Input {...field} className="w-40" /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Título</FormLabel>
                    <FormControl><Input {...field} className="w-52" /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Descripción</FormLabel>
                    <FormControl><Input {...field} className="w-52" /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="grid gap-1.5">
                <Label htmlFor="document-file">Archivo (PDF/PNG/JPG, máx. 20MB)</Label>
                <input
                  id="document-file"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="text-sm"
                />
              </div>
              <Button type="submit" disabled={saving} className="mt-6">
                {saving ? 'Subiendo…' : 'Subir documento'}
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : documents.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin documentos todavía.</p>
      ) : (
        <div className="grid gap-3">
          {documents.map((document) => (
            <Card key={document.id}>
              <CardContent className="flex items-center justify-between gap-3 pt-6">
                <div>
                  <p className="text-sm font-medium">{document.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {document.original_filename} · {formatBytes(document.size_bytes)} · {document.author} · {formatDateTime(document.created_at)}
                  </p>
                  {document.description && <p className="mt-1 text-sm">{document.description}</p>}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button asChild size="sm" variant="outline">
                    <a href={`/patients/${patientId}/documents/${document.id}/file`} target="_blank" rel="noreferrer">
                      Descargar
                    </a>
                  </Button>
                  {isAdmin && (
                    <Button size="sm" variant="outline" onClick={() => handleDelete(document)}>Eliminar</Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Consentimientos ───────────────────────────────────────────────────────

const consentSchema = z.object({
  author: z.string().trim().min(1, 'El autor es obligatorio'),
  procedure: z.string().trim().min(1, 'El procedimiento es obligatorio'),
  granted_by: z.string().min(1, 'Elegí quién autoriza'),
  text: z.string().trim().min(1, 'El texto es obligatorio'),
})
type ConsentFormValues = z.infer<typeof consentSchema>

function ConsentsSection({ patientId, isAdmin }: { patientId: string; isAdmin: boolean }) {
  const { user } = useAuth()
  const [consents, setConsents] = useState<Consent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const form = useForm<ConsentFormValues>({
    resolver: zodResolver(consentSchema),
    defaultValues: { author: user?.name ?? '', procedure: '', granted_by: '', text: '' },
  })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<Consent[]>(`/patients/${patientId}/consents`)
      setConsents(items.sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: ConsentFormValues) {
    setSaving(true)
    setError(null)
    try {
      await api.post(`/patients/${patientId}/consents`, values)
      form.reset({ author: values.author, procedure: '', granted_by: '', text: '' })
      await load()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(consent: Consent) {
    setError(null)
    try {
      await api.del(`/patients/${patientId}/consents/${consent.id}`)
      await load()
    } catch (err) {
      setError(describeError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Nuevo consentimiento</CardTitle></CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="grid gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
              <div className="flex flex-wrap gap-3">
                <FormField
                  control={form.control}
                  name="author"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Autor</FormLabel>
                      <FormControl><Input {...field} className="w-40" /></FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="procedure"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Procedimiento</FormLabel>
                      <FormControl><Input {...field} className="w-52" /></FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="granted_by"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Quién autoriza</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-48">
                            <SelectValue placeholder="Quién autoriza…" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="Paciente">Paciente</SelectItem>
                          <SelectItem value="Tutor o responsable">Tutor o responsable</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <FormField
                control={form.control}
                name="text"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Texto del consentimiento</FormLabel>
                    <FormControl><Textarea rows={3} {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div><Button type="submit" disabled={saving}>{saving ? 'Guardando…' : 'Registrar consentimiento'}</Button></div>
            </form>
          </Form>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : consents.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin consentimientos todavía.</p>
      ) : (
        <div className="grid gap-3">
          {consents.map((consent) => (
            <Card key={consent.id}>
              <CardContent className="pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{consent.procedure}</p>
                    <p className="text-xs text-muted-foreground">
                      Autoriza: {consent.granted_by} · {consent.author} · {formatDateTime(consent.created_at)}
                    </p>
                  </div>
                  {isAdmin && (
                    <Button size="sm" variant="outline" onClick={() => handleDelete(consent)}>Eliminar</Button>
                  )}
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{consent.text}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────

export function PacienteFicha() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [patient, setPatient] = useState<Patient | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api.get<Patient>(`/patients/${id}`).then(setPatient).catch((err) => setError(describeError(err)))
  }, [id])

  if (!id) return null

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-3">
        <Button asChild variant="outline" size="sm">
          <Link to="/pacientes">← Pacientes</Link>
        </Button>
        <TituloPantalla icono={Users}>{patient?.name ?? 'Cargando…'}</TituloPantalla>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {patient && (
        <Card>
          <CardContent className="flex flex-wrap gap-x-6 gap-y-1 pt-6 text-sm text-muted-foreground">
            <span>DNI: {patient.dni ?? '—'}</span>
            <span>Teléfono: {patient.phone ?? '—'}</span>
            <span>Email: {patient.email ?? '—'}</span>
            <span>CUIT: {patient.cuit ?? '—'}</span>
            <span>Condición de IVA: {patient.condicion_iva ?? '—'}</span>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="notas">
        <TabsList>
          <TabsTrigger value="notas">Historia clínica</TabsTrigger>
          <TabsTrigger value="recetas">Recetas</TabsTrigger>
          <TabsTrigger value="estudios">Estudios</TabsTrigger>
          <TabsTrigger value="documentos">Documentos</TabsTrigger>
          <TabsTrigger value="consentimientos">Consentimientos</TabsTrigger>
        </TabsList>
        <TabsContent value="notas"><NotesSection patientId={id} isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="recetas"><PrescriptionsSection patientId={id} isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="estudios"><StudyOrdersSection patientId={id} isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="documentos"><DocumentsSection patientId={id} isAdmin={isAdmin} /></TabsContent>
        <TabsContent value="consentimientos"><ConsentsSection patientId={id} isAdmin={isAdmin} /></TabsContent>
      </Tabs>
    </div>
  )
}
