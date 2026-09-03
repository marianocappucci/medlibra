/** La agenda, como calendario.
 *
 *  Pedido del humano (2026-08-22): *"agregar agenda normalizada, la que tiene
 *  libradesk y gestiolibra por libra-ui"*.
 *
 *  **Lo que reemplaza.** Hasta hoy esta pantalla era un formulario de alta
 *  arriba y una tabla abajo, con dos `<input type="date">` de rango. Podía
 *  decir *qué* turnos hay, pero no **cuánto ocupa cada uno ni dónde está el
 *  hueco**, que es la pregunta de quien atiende el teléfono. Y para saber qué
 *  hay el jueves había que mover el rango y perder de vista el resto.
 *
 *  El calendario en sí vive en `libra-ui/agenda`, extraído de LibraDesk. Lo que
 *  queda acá es lo que **es** de MedLibra: de dónde salen los turnos, qué es un
 *  evento, el alta, y las acciones sobre un turno (confirmar, cancelar,
 *  completar con su medio de pago y su factura).
 *
 *  **Todo el estado de la pantalla vive en la URL** — `?vista=`, `?dia=`,
 *  `?profesional=` y `?turno=` —, no en `useState`. Así se puede mandar "mirá
 *  el jueves" o "fijate este turno" por mensaje, el botón "atrás" del navegador
 *  vuelve del turno al día y del día a la semana, y recargar deja al usuario
 *  donde estaba.
 *
 *  ⚠️ **Las horas se muestran en el huso de la sede del profesional**, no en el
 *  del navegador: un turno de las 18:00 en un consultorio de Buenos Aires tiene
 *  que decir 18:00 sin importar desde dónde se mire la agenda, y el día al que
 *  pertenece también es el de la sede (ADR-028). La conversión la hace
 *  `components/agenda/datos.ts` una sola vez, al cargar.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { CalendarDays, Plus } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { BadgeEstado, type TonoEstado } from 'libra-ui/badge-estado'
import {
  LABEL_VISTA, NavegadorCalendario, ReferenciaDeColores, VISTAS, VistaMes,
  VistaSemana, clasePunto, diaDeLaUrl, hoyLocal, rangoDeVista, vistaDeLaUrl,
} from 'libra-ui/agenda'
import {
  api, ApiError, STATUS_LABELS,
  opcionesPaciente, opcionesServicio,
  type AppointmentStatus, type Branch, type CompleteAppointmentResponse,
  type EnvioAContalibra, type MedioPago, type Patient, type Resource, type Service,
} from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAgendaRango, type TurnoConProfesional } from '@/components/agenda/datos'
import { armadores, porDiaComoEventos } from '@/components/agenda/eventos'
import { VistaDia } from '@/components/agenda/vista-dia'
import { diaMesYHora, hora } from '@/lib/fechas'

const TODOS = '__todos__'

// 🔴 Acá había un `MEDIO_PAGO_LABELS` con cuatro medios escritos a mano, y uno
// de ellos —`tarjeta`— **no existía en el vocabulario de la familia**. Llegaba
// igual a Contalibra, creaba su movimiento de caja y salía en el cierre como un
// bucket suelto con el nombre crudo: la plata bien contada y el reparto mal.
//
// Peor: era la misma copia byte a byte que tiene Gestiolibra, así que dos
// productos inventaron el mismo medio por separado.
//
// Ahora la lista sale de `GET /medios-pago`, que la sirve `libracore.medios_pago`.
// La tarjeta viene **partida en débito y crédito**, que es como la declara ARCA.
// Ver `wiki/concepts/medios-de-pago-familia-libra.md`.

const STATUS_TONO: Record<AppointmentStatus, TonoEstado> = {
  pending: 'neutro',
  confirmed: 'curso',
  in_progress: 'curso',
  completed: 'ok',
  cancelled: 'negativo',
  no_show: 'negativo',
}

/** `22-08 17:00` a partir de la hora de pared que ya calculó `datos.ts`.
 *
 *  El formato vive en `lib/fechas`: era el mismo recorte que `PacienteFicha`
 *  tenia escrito aparte. */
function horaDePared(local: string): string {
  return diaMesYHora(local)
}

const turnoSchema = z.object({
  resource_id: z.string().min(1, 'Elegí un profesional'),
  service_id: z.string().min(1, 'Elegí una prestación'),
  client_id: z.string().min(1, 'Elegí un paciente'),
  starts_at: z.string().min(1, 'Elegí un horario'),
})

type TurnoFormValues = z.infer<typeof turnoSchema>

export function Agenda() {
  const [params, setParams] = useSearchParams()
  const [resources, setResources] = useState<Resource[]>([])
  const [branches, setBranches] = useState<Branch[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [patients, setPatients] = useState<Patient[]>([])
  const [errorCatalogo, setErrorCatalogo] = useState<string | null>(null)
  // 🔴 Si el catálogo YA se pidió. No alcanza con `resources.length === 0`
  // para distinguir "todavía cargando" de "no hay ninguno": son el mismo valor,
  // y una instancia recién creada —la que más necesita el cartel que manda a
  // Configuración— se quedaría en "Cargando…" para siempre.
  const [catalogoCargado, setCatalogoCargado] = useState(false)
  const [errorAccion, setErrorAccion] = useState<string | null>(null)
  const [creando, setCreando] = useState(false)
  const [altaAbierta, setAltaAbierta] = useState(false)
  const [medioPago, setMedioPago] = useState('')
  //: Los medios que sirve el motor (`GET /medios-pago`). Vacío hasta que
  //: conteste: el diálogo de cobro no se abre antes de que cargue el catálogo.
  const [mediosPago, setMediosPago] = useState<MedioPago[]>([])
  const [pidiendoMedioPago, setPidiendoMedioPago] = useState<TurnoConProfesional | null>(null)
  const [completando, setCompletando] = useState(false)
  // Sólo se llena cuando la consulta NO llegó a facturarse. El caso feliz no
  // interrumpe a nadie: viajó a Contalibra y no hay nada que mostrar.
  const [sinFacturar, setSinFacturar] = useState<EnvioAContalibra | null>(null)

  const vista = vistaDeLaUrl(params.get('vista'))
  // `hoyLocal()` en cada render y no en un `useState`: si alguien deja la
  // pantalla abierta pasada la medianoche, "hoy" tiene que ser el día nuevo.
  const hoy = hoyLocal()
  const dia = diaDeLaUrl(params.get('dia'), hoy)
  const filtro = params.get('profesional') ?? TODOS
  const turnoAbierto = params.get('turno')

  function describirError(err: unknown): string {
    if (err instanceof ApiError) return err.detail
    return 'Error de conexión.'
  }

  useEffect(() => {
    Promise.all([
      api.get<Resource[]>('/resources'),
      api.get<Branch[]>('/branches'),
      api.get<Service[]>('/services'),
      api.get<Patient[]>('/patients'),
      api.get<MedioPago[]>('/medios-pago'),
    ]).then(([r, b, s, p, m]) => {
      // `Array.isArray` y no confiar en el tipo: un cuerpo truncado o un `{}`
      // es truthy, y el `.filter()` de más abajo tumbaría la pantalla entera
      // con un TypeError en vez de mostrar de menos.
      setResources(Array.isArray(r) ? r : [])
      setBranches(Array.isArray(b) ? b : [])
      setServices(Array.isArray(s) ? s : [])
      setPatients(Array.isArray(p) ? p : [])
      setMediosPago(Array.isArray(m) ? m : [])
    }).catch((err) => setErrorCatalogo(describirError(err)))
      .finally(() => setCatalogoCargado(true))
  }, [])

  // Sólo los activos: un profesional dado de baja no se agenda, y sus turnos
  // viejos en la grilla serían ruido permanente.
  const activos = useMemo(() => resources.filter((r) => r.active), [resources])

  const { desde, dias } = rangoDeVista(vista, dia)
  const { porDia, error, recargar } = useAgendaRango(activos, branches, desde, dias)

  const form = useForm<TurnoFormValues>({
    resolver: zodResolver(turnoSchema),
    defaultValues: { resource_id: '', service_id: '', client_id: '', starts_at: '' },
  })

  /** Los parámetros de la pantalla con algunos cambiados. Los demás se
   *  conservan: cambiar de vista no tiene por qué olvidar el profesional
   *  elegido. */
  const con = useCallback((cambios: Record<string, string>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) {
      if (v === '') p.delete(k)
      else p.set(k, v)
    }
    return p
  }, [params])

  const href = useCallback(
    (cambios: Record<string, string>) => `/agenda?${con(cambios)}`,
    [con],
  )

  const nombrePaciente = useCallback(
    (id: string) => patients.find((p) => p.id === id)?.name ?? id, [patients])
  const nombrePrestacion = useCallback(
    (id: string) => services.find((s) => s.id === id)?.name ?? id, [services])
  const nombreSede = useCallback(
    (id: string | null) => (id ? branches.find((b) => b.id === id)?.name ?? null : null),
    [branches])

  const como = useMemo(
    () => armadores((id) => href({ turno: id }), nombrePaciente, nombrePrestacion),
    [href, nombrePaciente, nombrePrestacion],
  )

  // El filtro recorta lo que se dibuja, no lo que se pide (ver `datos.ts`).
  const visibles = filtro === TODOS
    ? porDia
    : Object.fromEntries(Object.entries(porDia).map(([d, ts]) => [
      d, ts.filter((t) => t.resource_id === filtro),
    ]))
  const profesionalesVisibles = filtro === TODOS
    ? activos
    : activos.filter((r) => r.id === filtro)

  const turno = useMemo(() => {
    if (!turnoAbierto) return null
    return Object.values(porDia).flat().find((t) => t.id === turnoAbierto) ?? null
  }, [turnoAbierto, porDia])

  function cerrarTurno() {
    setErrorAccion(null)
    setParams(con({ turno: '' }))
  }

  async function accion(hacer: () => Promise<unknown>) {
    setErrorAccion(null)
    try {
      await hacer()
      await recargar()
      cerrarTurno()
    } catch (err) {
      setErrorAccion(describirError(err))
    }
  }

  async function completar(t: TurnoConProfesional, medio?: string) {
    setErrorAccion(null)
    setCompletando(true)
    try {
      const respuesta = await api.post<CompleteAppointmentResponse>(
        `/appointments/${t.id}/complete`,
        medio ? { medio_pago: medio } : undefined,
      )
      setPidiendoMedioPago(null)
      setMedioPago('')
      // 🔴 Sólo se avisa si NO se facturó. `enviado` es el caso normal y no
      // merece un diálogo; `sin_destino` y `error` sí, porque son un turno
      // cobrado sin comprobante y el mostrador es el último lugar donde
      // todavía hay alguien mirando.
      const envio = respuesta.contalibra
      if (envio && envio.estado !== 'enviado') setSinFacturar(envio)
      await recargar()
      cerrarTurno()
    } catch (err) {
      // Sin medio de pago todavía intentado: el turno tiene saldo pendiente y
      // el backend lo pide (422). Se pregunta en un diálogo en vez de mostrar
      // el error crudo.
      if (err instanceof ApiError && err.status === 422 && !medio) {
        setPidiendoMedioPago(t)
      } else {
        setErrorAccion(describirError(err))
        setPidiendoMedioPago(null)
      }
    } finally {
      setCompletando(false)
    }
  }

  async function crear(values: TurnoFormValues) {
    setCreando(true)
    setErrorAccion(null)
    try {
      await api.post('/appointments', values)
      form.reset({ resource_id: values.resource_id, service_id: '', client_id: '', starts_at: '' })
      setAltaAbierta(false)
      await recargar()
    } catch (err) {
      setErrorAccion(describirError(err))
    } finally {
      setCreando(false)
    }
  }

  /** El huso del profesional elegido en el alta, para rotular el campo de
   *  horario. Sin el rótulo, quien carga un turno no tiene forma de saber si
   *  "18:00" es la hora del consultorio o la de su propia máquina. */
  const profesionalDelAlta = form.watch('resource_id')
  const zonaDelAlta = useMemo(() => {
    const profesional = activos.find((r) => r.id === profesionalDelAlta)
    const sede = profesional?.branch_id
      ? branches.find((b) => b.id === profesional.branch_id) : undefined
    return sede?.timezone ?? 'UTC'
  }, [profesionalDelAlta, activos, branches])

  function abrirAlta() {
    form.reset({
      resource_id: filtro !== TODOS ? filtro : (activos[0]?.id ?? ''),
      service_id: '', client_id: '',
      // Prellenado con el día que se está mirando: quien abre el alta parado en
      // el jueves quiere un turno el jueves, no hoy.
      starts_at: `${dia}T09:00`,
    })
    setErrorAccion(null)
    setAltaAbierta(true)
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TituloPantalla icono={CalendarDays}>Agenda</TituloPantalla>
          <p className="text-sm text-muted-foreground">
            Qué tiene cada profesional y dónde queda lugar. Entrá a un turno para
            confirmarlo, cancelarlo o completarlo.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-2">
            <Label htmlFor="filtro-profesional">Profesional</Label>
            <Select
              value={filtro}
              onValueChange={(v) => setParams(con({ profesional: v }))}
            >
              <SelectTrigger id="filtro-profesional" className="w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={TODOS}>Todos los profesionales</SelectItem>
                {activos.map((r) => (
                  <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={abrirAlta} disabled={activos.length === 0}>
            <Plus />Nuevo turno
          </Button>
        </div>
      </div>

      <NavegadorCalendario vista={vista} dia={dia} hoy={hoy} href={href}>
        {/* Las pestañas de shadcn: la vista la manda la URL, así que el
            conmutador es controlado (`value`, no `defaultValue`) — con el
            default, entrar con `?vista=mes` pintaría la primera pestaña y
            mostraría otra cosa. */}
        <Tabs value={vista} onValueChange={(v) => setParams(con({ vista: v }))}>
          <TabsList>
            {VISTAS.map((v) => (
              <TabsTrigger key={v} value={v}>{LABEL_VISTA[v]}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </NavegadorCalendario>

      {/* La referencia no se muestra en el día, que ya viene con una columna
          por profesional y el nombre en cada encabezado. */}
      {vista !== 'dia' && (
        <ReferenciaDeColores carriles={activos.map((r, i) => ({
          clave: r.id, nombre: r.name, clasePunto: clasePunto(i),
        }))} />
      )}

      {(errorCatalogo || error) && (
        <p className="text-sm text-destructive">{errorCatalogo ?? error}</p>
      )}

      {activos.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          {catalogoCargado
            ? 'No hay profesionales activos. Cargá uno en Configuración.'
            : 'Cargando…'}
        </CardContent></Card>
      ) : vista === 'dia' ? (
        <VistaDia
          profesionales={profesionalesVisibles}
          turnos={visibles[dia] ?? []}
          esHoy={dia === hoy}
          comoEvento={como.dia}
          nombreSede={nombreSede}
        />
      ) : vista === 'semana' ? (
        <VistaSemana
          desde={desde} porDia={porDiaComoEventos(visibles, como.semana)} hoy={hoy}
          hrefDia={(d) => href({ vista: 'dia', dia: d })}
        />
      ) : (
        <VistaMes
          desde={desde} celdas={dias} mes={dia}
          porDia={porDiaComoEventos(visibles, como.chip)} hoy={hoy}
          hrefDia={(d) => href({ vista: 'dia', dia: d })}
        />
      )}

      {/* ── El alta ───────────────────────────────────────────────────── */}
      <Dialog open={altaAbierta} onOpenChange={setAltaAbierta}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo turno</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form className="grid gap-3" onSubmit={form.handleSubmit(crear)}>
              <FormField
                control={form.control}
                name="resource_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Profesional</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger><SelectValue placeholder="Profesional…" /></SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {activos.map((r) => (
                          <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="service_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Prestación</FormLabel>
                    <FormControl>
                      <SelectBuscable
                        value={field.value}
                        onChange={field.onChange}
                        opciones={opcionesServicio(services.filter((s) => s.active))}
                        placeholder="Prestación…"
                        ariaLabel="Prestación"
                      />
                    </FormControl>
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
                    <FormControl>
                      <SelectBuscable
                        value={field.value}
                        onChange={field.onChange}
                        opciones={opcionesPaciente(patients.filter((p) => p.active))}
                        placeholder="Paciente…"
                        ariaLabel="Paciente"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="starts_at"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Horario ({zonaDelAlta})</FormLabel>
                    <FormControl>
                      <Input type="datetime-local" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {errorAccion && <p className="text-sm text-destructive">{errorAccion}</p>}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setAltaAbierta(false)}>
                  Cancelar
                </Button>
                <Button type="submit" disabled={creando}>
                  {creando ? 'Creando…' : 'Crear turno'}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      {/* ── El turno abierto ──────────────────────────────────────────── */}
      <Dialog open={turno !== null} onOpenChange={(abierto) => { if (!abierto) cerrarTurno() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{turno && nombrePaciente(turno.client_id)}</DialogTitle>
          </DialogHeader>
          {turno && (
            <div className="grid gap-2 text-sm">
              {[
                ['Prestación', nombrePrestacion(turno.service_id)],
                ['Profesional', turno.profesional_nombre],
                ['Horario', `${horaDePared(turno.desde)} – ${hora(turno.hasta)}`],
              ].map(([rotulo, valor]) => (
                <div key={rotulo} className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{rotulo}</span>
                  <span className="font-medium">{valor}</span>
                </div>
              ))}
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Estado</span>
                <BadgeEstado tono={STATUS_TONO[turno.status]}>
                  {STATUS_LABELS[turno.status]}
                </BadgeEstado>
              </div>
              {errorAccion && <p className="text-sm text-destructive">{errorAccion}</p>}
            </div>
          )}
          <DialogFooter>
            {turno?.status === 'pending' && (
              <Button
                variant="outline"
                onClick={() => accion(() => api.post(`/appointments/${turno.id}/confirm`))}
              >
                Confirmar
              </Button>
            )}
            {turno && (turno.status === 'pending' || turno.status === 'confirmed') && (
              <Button
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={() => accion(() => api.post(`/appointments/${turno.id}/cancel`))}
              >
                Cancelar turno
              </Button>
            )}
            {turno?.status === 'confirmed' && (
              <Button onClick={() => completar(turno)}>Completar</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── El medio de pago, cuando el turno tiene saldo ─────────────── */}
      <Dialog
        open={pidiendoMedioPago !== null}
        onOpenChange={(abierto) => { if (!abierto) setPidiendoMedioPago(null) }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Medio de pago requerido</DialogTitle>
            <DialogDescription>
              Este turno tiene un saldo pendiente de cobro. Elegí cómo se cobró para
              completarlo y facturarlo.
            </DialogDescription>
          </DialogHeader>
          <Select value={medioPago} onValueChange={setMedioPago}>
            <SelectTrigger><SelectValue placeholder="Medio de pago…" /></SelectTrigger>
            <SelectContent>
              {mediosPago.map((m) => (
                <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPidiendoMedioPago(null)}>Cancelar</Button>
            <Button
              disabled={!medioPago || completando}
              onClick={() => pidiendoMedioPago && completar(pidiendoMedioPago, medioPago)}
            >
              {completando ? 'Completando…' : 'Completar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── La consulta que NO llegó a facturarse ─────────────────────── */}
      {/*  🔴 Reemplaza al diálogo de "Factura emitida", que se fue con el motor
           local (ADR-036). El caso feliz ya no interrumpe a nadie: la consulta
           viajó a Contalibra y no hay nada que mostrar. Lo que sí interrumpe es
           el caso malo — un turno cobrado que no se facturó es plata que se
           pierde en silencio, y el mostrador es el único momento en que
           todavía hay alguien mirando. */}
      <Dialog
        open={sinFacturar !== null}
        onOpenChange={(abierto) => { if (!abierto) setSinFacturar(null) }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>El turno se completó, pero no se facturó</DialogTitle>
            <DialogDescription>
              {/* 🔴 **Nada se manda solo.** No hay reintento automático: el
                  único camino es `POST /facturacion-externa/{id}/reintentar`,
                  a mano. Decir "se manda sola cuando se configure" haría que
                  nadie vuelva a mirarla, y la consulta se quedaría ahí. */}
              {sinFacturar?.estado === 'sin_destino'
                ? 'Este consultorio todavía no tiene configurado a dónde mandar las consultas a facturar. La consulta quedó registrada como pendiente: una vez configurado el destino, hay que reenviarla.'
                : 'Contalibra no pudo recibir la consulta. Quedó registrada como pendiente y hay que reintentarla.'}
            </DialogDescription>
          </DialogHeader>
          {sinFacturar?.error && (
            <p className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
              {sinFacturar.error}
            </p>
          )}
          <DialogFooter>
            <Button onClick={() => setSinFacturar(null)}>Entendido</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
