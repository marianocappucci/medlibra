import { useEffect, useMemo, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { type ColumnDef } from '@tanstack/react-table'
import {
  api, ApiError, STATUS_LABELS, TIPO_COMPROBANTE_LABELS,
  type Appointment, type AppointmentStatus, type CompleteAppointmentResponse,
  type Factura, type Patient, type Resource, type Service,
} from '../api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { DataTable, sortableHeader } from '@/components/data-table'

const MEDIO_PAGO_LABELS: Record<string, string> = {
  efectivo: 'Efectivo',
  transferencia: 'Transferencia',
  tarjeta: 'Tarjeta',
  mercadopago: 'MercadoPago',
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' }).format(value)
}

function formatNumeroComprobante(f: Factura): string {
  return `${String(f.punto_venta).padStart(4, '0')}-${String(f.numero).padStart(8, '0')}`
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('es-AR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

const STATUS_BADGE_VARIANT: Record<AppointmentStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  pending: 'outline',
  confirmed: 'secondary',
  in_progress: 'secondary',
  completed: 'default',
  cancelled: 'destructive',
  no_show: 'destructive',
}

const appointmentSchema = z.object({
  service_id: z.string().min(1, 'Elegí un servicio'),
  client_id: z.string().min(1, 'Elegí un paciente'),
  starts_at: z.string().min(1, 'Elegí un horario'),
})

type AppointmentFormValues = z.infer<typeof appointmentSchema>

export function Agenda() {
  const [resources, setResources] = useState<Resource[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [patients, setPatients] = useState<Patient[]>([])
  const [resourceId, setResourceId] = useState<string>('')
  const [dateFrom, setDateFrom] = useState(todayIso())
  const [dateTo, setDateTo] = useState(todayIso())
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [completeTarget, setCompleteTarget] = useState<Appointment | null>(null)
  const [medioPago, setMedioPago] = useState('')
  const [completing, setCompleting] = useState(false)
  const [factura, setFactura] = useState<Factura | null>(null)

  const form = useForm<AppointmentFormValues>({
    resolver: zodResolver(appointmentSchema),
    defaultValues: { service_id: '', client_id: '', starts_at: '' },
  })

  useEffect(() => {
    Promise.all([
      api.get<Resource[]>('/resources'),
      api.get<Service[]>('/services'),
      api.get<Patient[]>('/patients'),
    ]).then(([r, s, p]) => {
      setResources(r)
      setServices(s)
      setPatients(p)
      if (r.length > 0) setResourceId(r[0].id)
    }).catch((err) => setError(describeError(err)))
  }, [])

  useEffect(() => {
    if (!resourceId) return
    loadAgenda()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceId, dateFrom, dateTo])

  function describeError(err: unknown): string {
    if (err instanceof ApiError) return err.detail
    return 'Error de conexión.'
  }

  async function loadAgenda() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<Appointment[]>(
        `/resources/${resourceId}/agenda?date_from=${dateFrom}&date_to=${dateTo}`,
      )
      setAppointments(items.sort((a, b) => a.starts_at.localeCompare(b.starts_at)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(values: AppointmentFormValues) {
    setCreating(true)
    setError(null)
    try {
      await api.post('/appointments', {
        resource_id: resourceId,
        service_id: values.service_id,
        client_id: values.client_id,
        starts_at: values.starts_at,
      })
      form.reset({ service_id: '', client_id: '', starts_at: '' })
      await loadAgenda()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleAction(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await loadAgenda()
    } catch (err) {
      setError(describeError(err))
    }
  }

  async function completeAppointment(a: Appointment, medioPagoValue?: string) {
    setError(null)
    setCompleting(true)
    try {
      const response = await api.post<CompleteAppointmentResponse>(
        `/appointments/${a.id}/complete`,
        medioPagoValue ? { medio_pago: medioPagoValue } : undefined,
      )
      setCompleteTarget(null)
      setMedioPago('')
      if (response.factura) setFactura(response.factura)
      await loadAgenda()
    } catch (err) {
      // Sin medio_pago todavía intentado: el turno tiene saldo pendiente y
      // el backend pide medio_pago (422) -- se pide en un diálogo en vez de
      // mostrarlo como error crudo.
      if (err instanceof ApiError && err.status === 422 && !medioPagoValue) {
        setCompleteTarget(a)
      } else {
        setError(describeError(err))
        setCompleteTarget(null)
      }
    } finally {
      setCompleting(false)
    }
  }

  function patientName(id: string): string {
    return patients.find((p) => p.id === id)?.name ?? id
  }

  function serviceName(id: string): string {
    return services.find((s) => s.id === id)?.name ?? id
  }

  const columns = useMemo<ColumnDef<Appointment>[]>(() => [
    { accessorKey: 'starts_at', header: sortableHeader('Horario'), cell: ({ row }) => formatTime(row.original.starts_at) },
    { id: 'patient', header: 'Paciente', cell: ({ row }) => patientName(row.original.client_id) },
    { id: 'service', header: 'Servicio', cell: ({ row }) => serviceName(row.original.service_id) },
    {
      accessorKey: 'status',
      header: 'Estado',
      cell: ({ row }) => (
        <Badge variant={STATUS_BADGE_VARIANT[row.original.status]}>{STATUS_LABELS[row.original.status]}</Badge>
      ),
    },
    {
      id: 'actions',
      header: () => <div className="text-right">Acciones</div>,
      cell: ({ row }) => {
        const a = row.original
        return (
          <div className="flex flex-wrap justify-end gap-2">
            {a.status === 'pending' && (
              <Button size="sm" variant="outline" onClick={() => handleAction(() => api.post(`/appointments/${a.id}/confirm`))}>
                Confirmar
              </Button>
            )}
            {(a.status === 'pending' || a.status === 'confirmed') && (
              <Button size="sm" variant="outline" onClick={() => handleAction(() => api.post(`/appointments/${a.id}/cancel`))}>
                Cancelar
              </Button>
            )}
            {a.status === 'confirmed' && (
              <Button size="sm" variant="outline" onClick={() => completeAppointment(a)}>
                Completar
              </Button>
            )}
          </div>
        )
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [patients, services])

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1.5">
          <Label>Recurso</Label>
          <Select value={resourceId} onValueChange={setResourceId}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="Recurso…" />
            </SelectTrigger>
            <SelectContent>
              {resources.map((r) => (
                <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="date-from">Desde</Label>
          <Input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-40" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="date-to">Hasta</Label>
          <Input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-40" />
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Nuevo turno</CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form className="flex flex-wrap items-start gap-3" onSubmit={form.handleSubmit(handleCreate)}>
              <FormField
                control={form.control}
                name="service_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Servicio</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-56">
                          <SelectValue placeholder="Servicio…" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {services.map((s) => (
                          <SelectItem key={s.id} value={s.id}>{s.name} ({s.duration_minutes} min)</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="client_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Paciente</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-56">
                          <SelectValue placeholder="Paciente…" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {patients.map((p) => (
                          <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="starts_at"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Horario</FormLabel>
                    <FormControl>
                      <Input type="datetime-local" {...field} className="w-56" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" disabled={creating || !resourceId} className="mt-6">
                {creating ? 'Creando…' : 'Crear turno'}
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Cargando…</p>
          ) : (
            <DataTable columns={columns} data={appointments} emptyMessage="Sin turnos en el rango seleccionado." />
          )}
        </CardContent>
      </Card>

      <Dialog open={completeTarget !== null} onOpenChange={(open) => { if (!open) setCompleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Medio de pago requerido</DialogTitle>
            <DialogDescription>
              Este turno tiene un saldo pendiente de cobro. Elegí cómo se cobró para completarlo
              y facturarlo.
            </DialogDescription>
          </DialogHeader>
          <Select value={medioPago} onValueChange={setMedioPago}>
            <SelectTrigger>
              <SelectValue placeholder="Medio de pago…" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(MEDIO_PAGO_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompleteTarget(null)}>Cancelar</Button>
            <Button
              disabled={!medioPago || completing}
              onClick={() => completeTarget && completeAppointment(completeTarget, medioPago)}
            >
              {completing ? 'Completando…' : 'Completar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={factura !== null} onOpenChange={(open) => { if (!open) setFactura(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Factura emitida</DialogTitle>
          </DialogHeader>
          {factura && (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Tipo</span>
                <span className="font-medium">{TIPO_COMPROBANTE_LABELS[factura.tipo] ?? factura.tipo}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Número</span>
                <span className="font-medium">{formatNumeroComprobante(factura)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">CAE</span>
                <span className="font-medium">{factura.cae || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total</span>
                <span className="font-medium">{formatCurrency(factura.total)}</span>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setFactura(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
