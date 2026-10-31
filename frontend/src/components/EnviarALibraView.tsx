// «Enviar a LibraView»: el diálogo que manda un pedido de estudios por imágenes a LibraView (el RIS) como una orden (ADR-051).
//
// Por qué se piden acá apellido, nombres y sexo: el paciente de MedLibra tiene un solo campo de nombre (viene de LibraGenda) y no tiene
// sexo, y LibraView necesita los tres. En vez de cambiarle el modelo al paciente se piden al mandar, precargando lo que se puede. El
// documento y la fecha de nacimiento sí son del paciente: si le faltan, el backend los completa con lo que se escriba acá.
//
// Cada ítem del pedido (texto libre: «Radiografía de tórax») se empareja con una práctica del catálogo de LibraView. Se preselecciona
// la que coincide sin mayúsculas ni acentos con el nombre o el código; si no coincide ninguna, queda sin elegir y hay que elegirla.
import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { hoyISO } from 'libra-ui/fechas'
import {
  api, ApiError,
  type EnvioLibraView, type Patient, type PracticaLibraView, type StudyOrder,
} from '../api'
import { partirNombre, practicaSugerida } from '@/lib/libraview'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'

const SEXOS = [
  { value: 'F', label: 'Femenino' },
  { value: 'M', label: 'Masculino' },
  { value: 'O', label: 'Otro' },
]
const PRIORIDADES = [
  { value: 'rutina', label: 'Rutina' },
  { value: 'urgente', label: 'Urgente' },
]

const esquema = z.object({
  items: z.array(z.object({
    item_id: z.string(),
    study_type: z.string(),
    codigo_practica: z.string().min(1, 'Elegí la práctica'),
  })).min(1),
  apellido: z.string().trim().min(1, 'El apellido es obligatorio'),
  nombres: z.string().trim().min(1, 'Los nombres son obligatorios'),
  sexo: z.string().refine((v) => SEXOS.some((s) => s.value === v), 'Elegí el sexo'),
  numero_documento: z.string().trim().min(1, 'El documento es obligatorio')
    .refine((v) => /^\d{6,9}$/.test(v.replace(/[.\s]/g, '')), 'El DNI tiene entre 6 y 9 dígitos'),
  fecha_nacimiento: z.string().min(1, 'La fecha de nacimiento es obligatoria')
    .refine((v) => v <= hoyISO(), 'La fecha de nacimiento no puede ser futura'),
  medico_solicitante: z.string().trim().min(1, 'El médico solicitante es obligatorio'),
  matricula_solicitante: z.string().trim().optional(),
  diagnostico_presuntivo: z.string().trim().optional(),
  prioridad: z.string(),
})
type Valores = z.infer<typeof esquema>

function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function valoresIniciales(patient: Patient, order: StudyOrder, catalogo: PracticaLibraView[]): Valores {
  const { apellido, nombres } = partirNombre(patient.name)
  const motivos = [...new Set(order.items.map((i) => (i.reason ?? '').trim()).filter(Boolean))]
  return {
    items: order.items.map((i) => ({
      item_id: i.id, study_type: i.study_type, codigo_practica: practicaSugerida(i.study_type, catalogo),
    })),
    apellido, nombres, sexo: '',
    numero_documento: patient.dni ?? '',
    fecha_nacimiento: patient.birth_date ?? '',
    medico_solicitante: order.author,
    matricula_solicitante: '',
    diagnostico_presuntivo: motivos.join('; '),
    prioridad: 'rutina',
  }
}

type Props = {
  patient: Patient
  order: StudyOrder
  /** Si el resultado vuelve solo (hay secreto del webhook). Cambia lo que el diálogo promete. */
  recibeResultados: boolean
  onClose: () => void
  /** Se llama con el envío que dejó el servidor (puede estar en error: el error se ve y se reintenta). */
  onEnviado: (envio: EnvioLibraView) => void
}

function Formulario({ patient, order, recibeResultados, onClose, onEnviado, catalogo }: Props & { catalogo: PracticaLibraView[] }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nombrePartido = partirNombre(patient.name).partido
  const form = useForm<Valores>({
    resolver: zodResolver(esquema),
    defaultValues: valoresIniciales(patient, order, catalogo),
  })
  const opciones = catalogo.map((p) => ({ value: p.codigo, label: p.nombre, hint: p.codigo }))

  async function enviar(v: Valores) {
    setSaving(true)
    setError(null)
    try {
      const envio = await api.post<EnvioLibraView>(`/patients/${patient.id}/study-orders/${order.id}/libraview`, {
        items: v.items.map((i) => ({ item_id: i.item_id, codigo_practica: i.codigo_practica })),
        paciente: {
          apellido: v.apellido, nombres: v.nombres, sexo: v.sexo,
          numero_documento: v.numero_documento, fecha_nacimiento: v.fecha_nacimiento,
        },
        medico_solicitante: v.medico_solicitante,
        matricula_solicitante: v.matricula_solicitante || null,
        diagnostico_presuntivo: v.diagnostico_presuntivo || null,
        prioridad: v.prioridad,
      })
      onEnviado(envio)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Form {...form}>
      <form className="grid gap-3" onSubmit={form.handleSubmit(enviar)}>
        <div className="grid gap-2">
          {order.items.map((item, index) => (
            <FormField
              key={item.id}
              control={form.control}
              name={`items.${index}.codigo_practica`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Práctica para «{item.study_type}»</FormLabel>
                  <FormControl>
                    <SelectBuscable
                      value={field.value}
                      onChange={field.onChange}
                      opciones={opciones}
                      placeholder="Buscar práctica de LibraView…"
                      ariaLabel={`Práctica para «${item.study_type}»`}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <FormField
            control={form.control} name="apellido"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Apellido</FormLabel>
                <FormControl><Input autoComplete="off" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control} name="nombres"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Nombres</FormLabel>
                <FormControl><Input autoComplete="off" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        {!nombrePartido && (
          <p className="-mt-1 text-xs text-muted-foreground">
            En la ficha el nombre está en un solo campo: «{patient.name}». Completá el apellido y los nombres por separado.
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <FormField
            control={form.control} name="sexo"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Sexo</FormLabel>
                {/* select-cerrado: tres opciones fijas (Femenino, Masculino, Otro), el vocabulario de LibraView */}
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger className="w-full"><SelectValue placeholder="Elegí…" /></SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {SEXOS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control} name="numero_documento"
            render={({ field }) => (
              <FormItem>
                <FormLabel>DNI</FormLabel>
                <FormControl><Input inputMode="numeric" autoComplete="off" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control} name="fecha_nacimiento"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Fecha de nacimiento</FormLabel>
                <FormControl><Input type="date" max={hoyISO()} {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <FormField
            control={form.control} name="medico_solicitante"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Médico solicitante</FormLabel>
                <FormControl><Input autoComplete="off" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control} name="matricula_solicitante"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Matrícula</FormLabel>
                <FormControl><Input autoComplete="off" {...field} /></FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <FormField
          control={form.control} name="diagnostico_presuntivo"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Diagnóstico presuntivo</FormLabel>
              <FormControl><Textarea rows={2} {...field} /></FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control} name="prioridad"
          render={({ field }) => (
            <FormItem className="max-w-xs">
              <FormLabel>Prioridad</FormLabel>
              {/* select-cerrado: dos opciones fijas (Rutina, Urgente), el vocabulario de LibraView */}
              <Select value={field.value} onValueChange={field.onChange}>
                <FormControl>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                </FormControl>
                <SelectContent>
                  {PRIORIDADES.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        {!recibeResultados && (
          <p className="text-xs text-muted-foreground">
            Esta instancia no tiene configurado el aviso de LibraView: el pedido se manda, pero el informe no vuelve solo.
          </p>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
          <Button type="submit" disabled={saving}>{saving ? 'Enviando…' : 'Enviar a LibraView'}</Button>
        </DialogFooter>
      </form>
    </Form>
  )
}

/** El diálogo. Se monta cuando hay un pedido para mandar; el formulario se arma recién con el catálogo en la mano, para que la
 *  preselección de las prácticas entre en los valores iniciales. */
export function EnviarALibraView(props: Props) {
  const [catalogo, setCatalogo] = useState<PracticaLibraView[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [intento, setIntento] = useState(0)

  useEffect(() => {
    let vigente = true
    api.get<PracticaLibraView[]>('/integraciones/libraview/practicas')
      .then((c) => { if (vigente) setCatalogo(c) })
      .catch((err) => { if (vigente) setError(describeError(err)) })
    return () => { vigente = false }
  }, [intento])

  return (
    <Dialog open onOpenChange={(abierto) => { if (!abierto) props.onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enviar a LibraView</DialogTitle>
          <DialogDescription>
            El pedido se manda como una orden de estudios por imágenes.
            {props.recibeResultados ? ' Cuando el informe esté publicado, vuelve solo a este pedido.' : ''}
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <div className="grid gap-3">
            <p role="alert" className="text-sm text-destructive">No se pudo traer el catálogo de LibraView: {error}</p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={props.onClose}>Cancelar</Button>
              <Button type="button" onClick={() => { setError(null); setIntento((n) => n + 1) }}>Reintentar</Button>
            </DialogFooter>
          </div>
        ) : catalogo === null ? (
          <p className="text-sm text-muted-foreground">Cargando el catálogo de LibraView…</p>
        ) : (
          <Formulario {...props} catalogo={catalogo} />
        )}
      </DialogContent>
    </Dialog>
  )
}
