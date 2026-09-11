/** La fila de la demanda espontánea: quién llegó, en qué orden, y quién sigue.
 *
 *  Pedido del humano (2026-08-22): *"agenda por turnos o por demanda
 *  espontánea"*, resuelto como **sin horario, por orden de llegada** (ADR-031).
 *  El backend tenía la fila desde entonces; lo único que se podía hacer desde
 *  la pantalla era **configurar** un bloque `espontanea` — anotar a alguien o
 *  llamarlo sólo se podía por API. Ver ADR-038.
 *
 *  🔴 **No es la agenda con otro dibujo.** Una llegada no tiene horario: tiene
 *  una posición. Por eso esto es una lista numerada y no una grilla, y por eso
 *  vive en su propia pantalla en vez de pintarse encima de los turnos.
 *
 *  ⚠️ La hora de llegada es la de la **sede** del profesional, no la del
 *  navegador ni necesariamente la de Argentina (ADR-028): la API la manda en UTC
 *  y se convierte al mostrar.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { ListOrdered } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { BadgeEstado, type TonoEstado } from 'libra-ui/badge-estado'
import { hoyISO } from 'libra-ui/fechas'
import {
  ApiError, ESTADO_LLEGADA_LABELS, api, opcionesPaciente,
  type BloqueDeLaFila, type EstadoLlegada, type Llegada, type Patient,
  type PrestacionDeLaFila,
} from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { enHoraDePared } from '@/components/agenda/datos'
import { fecha, fechaHora } from '@/lib/fechas'
import { describirEspera, minutosDeEspera } from '@/lib/espera'

/** Cada cuánto se vuelve a pedir la fila. La operan dos puntas a la vez —el
 *  mostrador anota, el consultorio llama— y ninguna ve lo que hace la otra si
 *  la pantalla no se refresca sola. Medio minuto es también la resolución de la
 *  espera, que se muestra en minutos. */
const REFRESCO_MS = 30_000

const TONO: Record<EstadoLlegada, TonoEstado> = {
  waiting: 'atencion',
  in_progress: 'curso',
  completed: 'ok',
  cancelled: 'negativo',
}

type Accion = { ruta: 'llamar' | 'completar' | 'cancelar'; label: string }

/** Qué botones ofrece cada estado. **Es la tabla `TRANSICIONES` del backend
 *  (`app/services/walkins.py`) vista desde la pantalla**: un botón que el
 *  backend rechaza siempre con 409 es peor que no tenerlo, porque enseña a
 *  ignorar los errores de esta pantalla. */
const ACCIONES: Record<EstadoLlegada, Accion[]> = {
  waiting: [
    { ruta: 'llamar', label: 'Llamar' },
    { ruta: 'cancelar', label: 'Sacar de la fila' },
  ],
  in_progress: [
    { ruta: 'completar', label: 'Atendido' },
    { ruta: 'cancelar', label: 'Sacar de la fila' },
  ],
  completed: [],
  cancelled: [],
}

const llegadaSchema = z.object({
  client_id: z.string().min(1, 'Elegí un paciente'),
  service_id: z.string().min(1, 'Elegí una prestación'),
})

type LlegadaFormValues = z.infer<typeof llegadaSchema>

const DIA_ISO = /^\d{4}-\d{2}-\d{2}$/

/** `09:00:00` → `09:00`. Es una hora de pared de la sede, sin fecha ni zona:
 *  no hay nada que convertir. */
function horaCorta(valor: string): string {
  return valor.slice(0, 5)
}

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function describirBloque(b: BloqueDeLaFila): string {
  return `${b.profesional} · ${b.consultorio} · ${horaCorta(b.starts_at)} – ${horaCorta(b.ends_at)}`
}

export function DemandaEspontanea() {
  const [params, setParams] = useSearchParams()
  // `hoyISO()` en cada render y no en un `useState`: si la pantalla queda
  // abierta pasada la medianoche, "hoy" tiene que ser el día nuevo.
  const hoy = hoyISO()
  const diaDeLaUrl = params.get('dia')
  const dia = diaDeLaUrl && DIA_ISO.test(diaDeLaUrl) ? diaDeLaUrl : hoy
  const bloqueDeLaUrl = params.get('bloque')

  //: Los bloques y la fila se guardan CON la clave de lo que se pidió, y la
  //: pantalla sólo usa lo que corresponde a lo que está mirando. Así, al cambiar
  //: de día o de bloque no hay que vaciar nada a mano dentro de un efecto: lo
  //: viejo deja de valer solo, y nunca se dibuja la fila de un bloque debajo
  //: del nombre de otro mientras llega la respuesta.
  const [bloquesDe, setBloquesDe] = useState<{ dia: string; lista: BloqueDeLaFila[] } | null>(null)
  const [pacientes, setPacientes] = useState<Patient[]>([])
  const [prestaciones, setPrestaciones] = useState<PrestacionDeLaFila[]>([])
  const [filaDe, setFilaDe] = useState<{ clave: string; items: Llegada[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [anotando, setAnotando] = useState(false)
  const [moviendo, setMoviendo] = useState<string | null>(null)
  //: "Ahora" para la espera. Se actualiza con el mismo intervalo que la fila:
  //: si se leyera `Date.now()` en el render, la espera sólo avanzaría cuando
  //: algo más hiciera re-renderizar la pantalla.
  const [ahora, setAhora] = useState(() => Date.now())

  const form = useForm<LlegadaFormValues>({
    resolver: zodResolver(llegadaSchema),
    defaultValues: { client_id: '', service_id: '' },
  })

  /** Los parámetros de la pantalla con algunos cambiados. Vacío = se saca. */
  const con = useCallback((cambios: Record<string, string>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) {
      if (v === '') p.delete(k)
      else p.set(k, v)
    }
    return p
  }, [params])

  useEffect(() => {
    Promise.all([
      api.get<Patient[]>('/patients'),
      api.get<PrestacionDeLaFila[]>('/walkins/prestaciones'),
    ]).then(([p, s]) => {
      // `Array.isArray` y no confiar en el tipo: un `{}` es truthy y el
      // `.filter()` de más abajo tumbaría la pantalla entera.
      setPacientes(Array.isArray(p) ? p : [])
      setPrestaciones(Array.isArray(s) ? s : [])
    }).catch((err) => setError(describirError(err)))
  }, [])

  useEffect(() => {
    // Cambiar de día con la respuesta anterior en vuelo: sin esta marca, la
    // lista del día que se dejó atrás puede llegar última y quedarse.
    let vigente = true
    api.get<BloqueDeLaFila[]>(`/walkins/bloques?day=${dia}`)
      .then((b) => { if (vigente) setBloquesDe({ dia, lista: Array.isArray(b) ? b : [] }) })
      .catch((err) => {
        if (!vigente) return
        setBloquesDe({ dia, lista: [] })
        setError(describirError(err))
      })
    return () => { vigente = false }
  }, [dia])

  //: `null` mientras no llegó la lista de ESTE día: es "cargando", no "vacía".
  const bloques = bloquesDe?.dia === dia ? bloquesDe.lista : null
  // El bloque de la URL si rige ese día; si no, el primero. Un `?bloque=` que
  // quedó de otro día no puede dejar la pantalla sin fila habiendo una.
  const bloque = bloques?.find((b) => b.id === bloqueDeLaUrl) ?? bloques?.[0] ?? null
  const bloqueId = bloque?.id ?? null
  const zona = bloque?.timezone ?? 'UTC'
  const claveFila = bloqueId ? `${bloqueId}|${dia}` : null
  const fila = filaDe && filaDe.clave === claveFila ? filaDe.items : []

  const enVuelo = useRef(0)
  const cargarFila = useCallback(async () => {
    const mia = ++enVuelo.current
    if (!bloqueId) return
    try {
      const items = await api.get<Llegada[]>(`/agenda-blocks/${bloqueId}/walkins?day=${dia}`)
      if (mia !== enVuelo.current) return
      setFilaDe({ clave: `${bloqueId}|${dia}`, items: Array.isArray(items) ? items : [] })
    } catch (err) {
      if (mia === enVuelo.current) setError(describirError(err))
    }
  }, [bloqueId, dia])

  useEffect(() => {
    void cargarFila()
    const intervalo = setInterval(() => {
      setAhora(Date.now())
      void cargarFila()
    }, REFRESCO_MS)
    return () => clearInterval(intervalo)
  }, [cargarFila])

  async function anotar(values: LlegadaFormValues) {
    if (!bloqueId) return
    setAnotando(true)
    setError(null)
    try {
      // 🔴 El día va explícito y es el de la PANTALLA, no el de hoy: la
      // secretaria puede estar armando la fila de otro día, y el backend lo
      // pide justamente para no adivinarlo con su propio reloj.
      await api.post(`/agenda-blocks/${bloqueId}/walkins`, { ...values, day: dia })
      // La prestación se conserva: casi toda la fila viene por lo mismo, y
      // volver a elegirla en cada llegada es fricción sobre el caso normal.
      form.reset({ client_id: '', service_id: values.service_id })
      // No se toca `ahora` acá: el recién llegado espera 0 minutos, que es lo
      // que da el piso de `minutosDeEspera` aunque `ahora` sea de hace un rato.
      await cargarFila()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setAnotando(false)
    }
  }

  async function mover(llegada: Llegada, accion: Accion) {
    setMoviendo(llegada.id)
    setError(null)
    try {
      await api.post(`/walkins/${llegada.id}/${accion.ruta}`)
    } catch (err) {
      setError(describirError(err))
    } finally {
      // Se recarga también si falló: un 409 casi siempre quiere decir que la
      // otra punta ya la movió, y lo que hay que mostrar es cómo quedó.
      await cargarFila()
      setMoviendo(null)
    }
  }

  const nombrePaciente = (id: string) => pacientes.find((p) => p.id === id)?.name ?? id
  const nombrePrestacion = (id: string) => prestaciones.find((s) => s.id === id)?.name ?? id

  // 🔴 Quién sigue es el primero que ESPERA, no el primero de la lista. El
  // número es histórico (ADR-031): con el N° 1 atendido y el N° 2 fuera de la
  // fila, el que sigue es el N° 3.
  const sigue = fila.find((l) => l.status === 'waiting')?.id ?? null
  const esperando = fila.filter((l) => l.status === 'waiting').length
  const enAtencion = fila.filter((l) => l.status === 'in_progress').length

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TituloPantalla icono={ListOrdered}>Demanda espontánea</TituloPantalla>
          <p className="text-sm text-muted-foreground">
            La fila por orden de llegada de los bloques sin turnos. Anotá a quien
            llega y llamalo cuando le toque.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-2">
            <Label htmlFor="fila-dia">Día</Label>
            <Input
              id="fila-dia" type="date" className="w-40"
              value={dia}
              onChange={(e) => {
                if (DIA_ISO.test(e.target.value)) {
                  setParams(con({ dia: e.target.value, bloque: '' }))
                }
              }}
            />
          </div>
          <Button
            variant="outline" disabled={dia === hoy}
            onClick={() => setParams(con({ dia: '', bloque: '' }))}
          >
            Hoy
          </Button>
          {bloques && bloques.length > 0 && (
            <div className="grid gap-2">
              <Label htmlFor="fila-bloque">Bloque</Label>
              <Select
                value={bloqueId ?? ''}
                onValueChange={(v) => setParams(con({ bloque: v }))}
              >
                <SelectTrigger id="fila-bloque" className="w-80">
                  <SelectValue placeholder="Bloque…" />
                </SelectTrigger>
                <SelectContent>
                  {bloques.map((b) => (
                    <SelectItem key={b.id} value={b.id}>{describirBloque(b)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {bloques === null ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          Cargando…
        </CardContent></Card>
      ) : !bloque ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          El {fecha(dia)} no hay ningún bloque de demanda espontánea vigente. Se
          arman en Configuración, en la agenda de cada profesional, con la
          modalidad «Demanda espontánea».
        </CardContent></Card>
      ) : (
        <>
          <Card>
            <CardContent className="grid gap-3 pt-6">
              <Form {...form}>
                <form
                  className="flex flex-wrap items-start gap-3"
                  onSubmit={form.handleSubmit(anotar)}
                >
                  <FormField
                    control={form.control}
                    name="client_id"
                    render={({ field }) => (
                      <FormItem className="min-w-64">
                        <FormLabel>Paciente</FormLabel>
                        <FormControl>
                          <SelectBuscable
                            value={field.value}
                            onChange={field.onChange}
                            opciones={opcionesPaciente(pacientes.filter((p) => p.active))}
                            placeholder="Paciente…"
                            ariaLabel="Paciente"
                            className="w-64"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="service_id"
                    render={({ field }) => (
                      <FormItem className="min-w-56">
                        <FormLabel>Prestación</FormLabel>
                        <FormControl>
                          <SelectBuscable
                            value={field.value}
                            onChange={field.onChange}
                            opciones={prestaciones.map((s) => ({ value: s.id, label: s.name }))}
                            placeholder="Prestación…"
                            ariaLabel="Prestación"
                            className="w-56"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <Button type="submit" className="mt-[1.375rem]" disabled={anotando}>
                    {anotando ? 'Anotando…' : 'Anotar llegada'}
                  </Button>
                </form>
              </Form>
              <p className="text-xs text-muted-foreground">
                ¿No está cargado? Dalo de alta en{' '}
                <Link to="/pacientes" className="underline">Pacientes</Link> y
                volvé: la fila sólo anota pacientes existentes.
              </p>
            </CardContent>
          </Card>

          <p className="text-sm text-muted-foreground">
            Fila del {fecha(dia)} · {esperando} esperando · {enAtencion} en atención
          </p>

          {fila.length === 0 ? (
            <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
              Todavía no llegó nadie.
            </CardContent></Card>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-14">N°</TableHead>
                    <TableHead>Paciente</TableHead>
                    <TableHead>Prestación</TableHead>
                    <TableHead>Llegó</TableHead>
                    <TableHead>Espera</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {fila.map((l) => (
                    <TableRow key={l.id}>
                      <TableCell className="tabular-nums font-medium">{l.arrival_order}</TableCell>
                      <TableCell>
                        <span className="flex items-center gap-2">
                          {nombrePaciente(l.client_id)}
                          {l.id === sigue && <BadgeEstado tono="curso">Sigue</BadgeEstado>}
                        </span>
                      </TableCell>
                      <TableCell>{nombrePrestacion(l.service_id)}</TableCell>
                      <TableCell className="tabular-nums">
                        {fechaHora(enHoraDePared(l.created_at, zona))}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {/* Sólo para quien espera: sin la hora en que lo
                            llamaron, "cuánto esperó" el ya atendido sería una
                            cuenta hasta ahora, que no mide nada. */}
                        {l.status === 'waiting'
                          ? describirEspera(minutosDeEspera(l.created_at, ahora))
                          : '—'}
                      </TableCell>
                      <TableCell>
                        <BadgeEstado tono={TONO[l.status]}>
                          {ESTADO_LLEGADA_LABELS[l.status]}
                        </BadgeEstado>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          {ACCIONES[l.status].map((a) => (
                            <Button
                              key={a.ruta} size="sm"
                              variant={a.ruta === 'cancelar' ? 'outline' : 'default'}
                              disabled={moviendo === l.id}
                              onClick={() => mover(l, a)}
                            >
                              {a.label}
                            </Button>
                          ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
