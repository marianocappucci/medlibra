import { useEffect, useMemo, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { type ColumnDef } from '@tanstack/react-table'
import { api, ApiError, type Patient } from '../api'
import { useAuth } from '../context/AuthContext'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import { DataTable, sortableHeader } from '@/components/data-table'

const CONDICIONES_IVA = [
  'Responsable Inscripto',
  'Monotributista',
  'IVA Exento',
  'Consumidor Final',
  'No Alcanzado',
]

const patientSchema = z.object({
  id: z.string().trim().min(1, 'El ID es obligatorio'),
  name: z.string().trim().min(1, 'El nombre es obligatorio'),
  phone: z.string().trim().optional(),
  email: z.string().trim().email('Email inválido').optional().or(z.literal('')),
  dni: z.string().trim().optional(),
  birth_date: z.string().optional(),
  cuit: z.string().trim().optional(),
  condicion_iva: z.string().optional(),
})

type PatientFormValues = z.infer<typeof patientSchema>

const EMPTY_VALUES: PatientFormValues = {
  id: '', name: '', phone: '', email: '', dni: '', birth_date: '', cuit: '', condicion_iva: '',
}

export function Pacientes() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [patients, setPatients] = useState<Patient[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const form = useForm<PatientFormValues>({
    resolver: zodResolver(patientSchema),
    defaultValues: EMPTY_VALUES,
  })

  useEffect(() => {
    loadPatients()
  }, [])

  function describeError(err: unknown): string {
    if (err instanceof ApiError) return err.detail
    return 'Error de conexión.'
  }

  async function loadPatients() {
    setLoading(true)
    setError(null)
    try {
      const items = await api.get<Patient[]>('/patients')
      setPatients(items.sort((a, b) => a.name.localeCompare(b.name)))
    } catch (err) {
      setError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  function startCreate() {
    setEditingId('new')
    form.reset(EMPTY_VALUES)
  }

  function startEdit(patient: Patient) {
    setEditingId(patient.id)
    form.reset({
      id: patient.id,
      name: patient.name,
      phone: patient.phone ?? '',
      email: patient.email ?? '',
      dni: patient.dni ?? '',
      birth_date: patient.birth_date ?? '',
      cuit: patient.cuit ?? '',
      condicion_iva: patient.condicion_iva ?? '',
    })
  }

  function cancelEdit() {
    setEditingId(null)
    form.reset(EMPTY_VALUES)
  }

  async function handleSubmit(values: PatientFormValues) {
    setSaving(true)
    setError(null)
    const payload = {
      name: values.name,
      phone: values.phone || null,
      email: values.email || null,
      dni: values.dni || null,
      birth_date: values.birth_date || null,
      cuit: values.cuit || null,
      condicion_iva: values.condicion_iva || null,
    }
    try {
      if (editingId === 'new') {
        await api.post('/patients', { id: values.id, ...payload })
      } else if (editingId) {
        await api.put(`/patients/${editingId}`, payload)
      }
      cancelEdit()
      await loadPatients()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(patient: Patient) {
    setError(null)
    try {
      await api.del(`/patients/${patient.id}`)
      await loadPatients()
    } catch (err) {
      setError(describeError(err))
    }
  }

  const columns = useMemo<ColumnDef<Patient>[]>(() => {
    const base: ColumnDef<Patient>[] = [
      { accessorKey: 'name', header: sortableHeader('Nombre'), cell: ({ row }) => <span className="font-medium">{row.original.name}</span> },
      { accessorKey: 'dni', header: 'DNI', cell: ({ row }) => row.original.dni ?? '—' },
      { accessorKey: 'phone', header: 'Teléfono', cell: ({ row }) => row.original.phone ?? '—' },
      { accessorKey: 'email', header: 'Email', cell: ({ row }) => row.original.email ?? '—' },
      {
        accessorKey: 'active',
        header: 'Estado',
        cell: ({ row }) => (
          <Badge variant={row.original.active ? 'default' : 'outline'}>
            {row.original.active ? 'Activo' : 'Inactivo'}
          </Badge>
        ),
      },
      {
        id: 'actions',
        header: () => <div className="text-right">Acciones</div>,
        cell: ({ row }) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => startEdit(row.original)}>Editar</Button>
            {isAdmin && (
              <Button size="sm" variant="outline" onClick={() => handleDelete(row.original)}>Eliminar</Button>
            )}
          </div>
        ),
      },
    ]
    return base
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin])

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Pacientes</h2>
        {editingId === null && (
          <Button onClick={startCreate}>+ Nuevo paciente</Button>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {editingId !== null && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{editingId === 'new' ? 'Nuevo paciente' : 'Editar paciente'}</CardTitle>
          </CardHeader>
          <CardContent>
            <Form {...form}>
              <form className="flex flex-wrap items-start gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
                {editingId === 'new' && (
                  <FormField
                    control={form.control}
                    name="id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>ID</FormLabel>
                        <FormControl>
                          <Input {...field} className="w-32" />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Nombre</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-48" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="dni"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>DNI</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-32" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="birth_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Fecha de nacimiento</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} className="w-40" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="phone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Teléfono</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-40" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="email"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Email</FormLabel>
                      <FormControl>
                        <Input type="email" {...field} className="w-52" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="cuit"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>CUIT</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-36" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="condicion_iva"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Condición de IVA</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-52">
                            <SelectValue placeholder="Condición de IVA…" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {CONDICIONES_IVA.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex gap-2 pt-6">
                  <Button type="submit" disabled={saving}>
                    {saving ? 'Guardando…' : editingId === 'new' ? 'Crear' : 'Guardar'}
                  </Button>
                  <Button type="button" variant="outline" onClick={cancelEdit}>Cancelar</Button>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent>
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Cargando…</p>
          ) : (
            <DataTable columns={columns} data={patients} emptyMessage="Sin pacientes todavía." />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
