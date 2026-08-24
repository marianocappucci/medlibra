/** Profesionales: quién atiende, cuándo y dónde.
 *
 *  El `Resource` de LibraGenda es, en este producto, **el profesional** — lo
 *  dicen el seed y los mensajes de la agenda. Tres cosas cuelgan de él y las
 *  tres deciden si un turno entra:
 *
 *  1. **Bloques de agenda**: su jornada, con consultorio, vigencia, duración del
 *     turno y modalidad (ver `bloques.tsx`).
 *  2. **Bloqueos**: un rato puntual en el que no atiende (una reunión, una
 *     licencia de dos días).
 *  3. **Excepciones por fecha**: un día concreto que se cierra o se abre, y que
 *     **gana sobre la jornada**. Es lo que permite abrir un sábado puntual o
 *     cerrar un feriado sin tocar los bloques.
 *
 *  🔴 **Un profesional sin ningún bloque vigente no recibe turnos, nunca.** El
 *  motor no tiene con qué decir que sí, y toda alta vuelve con *"el profesional
 *  no atiende en ese horario"*. Es distinto del horario de la sede, que es
 *  opt-in: cargar sólo ése deja la agenda muerta.
 */
import { useCallback, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import {
  api, type Bloqueo, type Branch, type Consultorio,
  type ExcepcionDeAgenda, type Resource,
} from '../../api'
import { Button } from '@/components/ui/button'
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { BloquesDeAgenda } from './bloques'
import {
  CampoActivo, ListaDelCatalogo, PieDeFormulario, comoIdentificador, describirError,
} from './catalogo'

const SIN_SEDE = '__ninguna__'
const VACIO = { id: '', name: '', branch_id: SIN_SEDE, active: true }

export function ProfesionalesCard() {
  const [profesionales, setProfesionales] = useState<Resource[]>([])
  const [sedes, setSedes] = useState<Branch[]>([])
  const [consultorios, setConsultorios] = useState<Consultorio[]>([])
  const [elegido, setElegido] = useState<string | null>(null)
  const [form, setForm] = useState({ ...VACIO })
  const [editando, setEditando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const [r, b, c] = await Promise.all([
        api.get<Resource[]>('/resources'),
        api.get<Branch[]>('/branches'),
        api.get<Consultorio[]>('/consultorios'),
      ])
      setProfesionales(Array.isArray(r) ? r : [])
      setSedes(Array.isArray(b) ? b : [])
      setConsultorios(Array.isArray(c) ? c : [])
    } catch (err) {
      setError(describirError(err))
    } finally {
      setCargando(false)
    }
  }, [])

  useEffect(() => { void cargar() }, [cargar])

  function editar(id: string) {
    const r = profesionales.find((x) => x.id === id)
    setElegido(id)
    setError(null)
    if (!r) return
    setEditando(true)
    setForm({
      id: r.id, name: r.name,
      branch_id: r.branch_id ?? SIN_SEDE, active: r.active,
    })
  }

  function limpiar() {
    setEditando(false)
    setForm({ ...VACIO })
    setError(null)
  }

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    setGuardando(true)
    setError(null)
    const cuerpo = {
      name: form.name, active: form.active,
      branch_id: form.branch_id === SIN_SEDE ? null : form.branch_id,
    }
    try {
      if (editando) {
        await api.put(`/resources/${form.id}`, cuerpo)
      } else {
        const id = form.id || comoIdentificador(form.name)
        await api.post('/resources', { id, ...cuerpo })
        setElegido(id)
      }
      await cargar()
      if (!editando) limpiar()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setGuardando(false)
    }
  }

  async function borrar() {
    setError(null)
    try {
      await api.del(`/resources/${form.id}`)
      setElegido(null)
      limpiar()
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  const nombreSede = (id: string | null) =>
    (id && sedes.find((s) => s.id === id)?.name) || 'sin sede'

  return (
    <div className="grid gap-4">
      <ListaDelCatalogo
        titulo="Profesionales"
        descripcion="Quién atiende. Un turno ocupa un profesional, y los choques de agenda se calculan sobre él."
        items={profesionales}
        elegido={elegido}
        onElegir={editar}
        nombre={(r) => r.name}
        detalleDeFila={(r) => nombreSede(r.branch_id)}
        vacio={cargando ? 'Cargando…' : 'Todavía no hay profesionales. Creá el primero abajo.'}
        acciones={editando && <Button variant="outline" onClick={limpiar}>Nuevo profesional</Button>}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {editando ? `Editar «${form.name}»` : 'Nuevo profesional'}
          </CardTitle>
          <CardDescription>
            Sin sede, el profesional se agenda en UTC y queda fuera del horario de
            atención: conviene asignarle una siempre.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:max-w-2xl" onSubmit={guardar}>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="prof-nombre">Nombre</Label>
                <Input
                  id="prof-nombre" required value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="prof-id">Identificador</Label>
                <Input
                  id="prof-id" disabled={editando}
                  placeholder={comoIdentificador(form.name) || 'dra-perez'}
                  value={form.id}
                  onChange={(e) => setForm({ ...form, id: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="prof-sede">Sede</Label>
                <Select
                  value={form.branch_id}
                  onValueChange={(v) => setForm({ ...form, branch_id: v })}
                >
                  <SelectTrigger id="prof-sede"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={SIN_SEDE}>Sin sede</SelectItem>
                    {sedes.map((s) => (
                      <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <CampoActivo
              id="prof-activo" checked={form.active}
              onChange={(v) => setForm({ ...form, active: v })}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <PieDeFormulario
              editando={editando} guardando={guardando}
              onCancelar={limpiar} onBorrar={borrar}
            />
          </form>
        </CardContent>
      </Card>

      {elegido && profesionales.some((r) => r.id === elegido) && (
        <>
          <BloquesDeAgenda
            key={`blq-${elegido}`}
            resourceId={elegido}
            consultorios={consultorios.filter((c) => c.active)}
          />
          <Bloqueos key={`blo-${elegido}`} resourceId={elegido} />
          <Excepciones key={`exc-${elegido}`} resourceId={elegido} />
        </>
      )}
    </div>
  )
}

/** Los ratos puntuales en los que el profesional no atiende.
 *
 *  ⚠️ Se cargan en **hora de pared de la sede** —igual que un turno— y el
 *  backend los convierte a instante al guardarlos (ADR-028). Vuelven en UTC, así
 *  que se muestran tal como los devuelve la API con su `Z`: convertirlos de
 *  nuevo acá sería una segunda fuente de verdad para la misma cuenta.
 */
function Bloqueos({ resourceId }: { resourceId: string }) {
  const [items, setItems] = useState<Bloqueo[]>([])
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const datos = await api.get<Bloqueo[]>(`/resources/${resourceId}/blocks`)
      setItems((Array.isArray(datos) ? datos : []).slice().sort(
        (a, b) => a.starts_at.localeCompare(b.starts_at),
      ))
    } catch (err) {
      setError(describirError(err))
    }
  }, [resourceId])

  useEffect(() => { void cargar() }, [cargar])

  async function agregar() {
    setGuardando(true)
    setError(null)
    try {
      await api.post(`/resources/${resourceId}/blocks`, {
        starts_at: desde, ends_at: hasta, reason: motivo,
      })
      setMotivo('')
      await cargar()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setGuardando(false)
    }
  }

  async function borrar(id: number) {
    setError(null)
    try {
      await api.del(`/resources/${resourceId}/blocks/${id}`)
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Bloqueos</CardTitle>
        <CardDescription>
          Ratos puntuales en los que este profesional no atiende, aunque su
          agenda diga que sí. Se cargan en hora de la sede.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin bloqueos.</p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {items.map((b) => (
              <li key={b.id} className="flex items-center gap-3">
                <span className="tabular-nums">
                  {b.starts_at.slice(0, 16).replace('T', ' ')} → {b.ends_at.slice(0, 16).replace('T', ' ')}
                </span>
                <span className="text-muted-foreground">{b.reason}</span>
                <Button
                  size="icon" variant="ghost"
                  className="size-7 text-destructive hover:text-destructive"
                  aria-label={`Borrar bloqueo ${b.starts_at}`}
                  onClick={() => borrar(b.id)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-2 border-t pt-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`blo-desde-${resourceId}`}>Desde</Label>
            <Input
              id={`blo-desde-${resourceId}`} type="datetime-local"
              value={desde} onChange={(e) => setDesde(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`blo-hasta-${resourceId}`}>Hasta</Label>
            <Input
              id={`blo-hasta-${resourceId}`} type="datetime-local"
              value={hasta} onChange={(e) => setHasta(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`blo-motivo-${resourceId}`}>Motivo</Label>
            <Input
              id={`blo-motivo-${resourceId}`} className="w-48"
              value={motivo} onChange={(e) => setMotivo(e.target.value)}
            />
          </div>
          <Button onClick={agregar} disabled={guardando || !desde || !hasta}>
            Agregar bloqueo
          </Button>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}

/** Los días concretos que se cierran o se abren.
 *
 *  🔴 **Una excepción siempre gana sobre la jornada**, en las dos direcciones:
 *  cierra un día que los bloques abrían (un feriado) y abre uno que los bloques
 *  cerraban (un sábado puntual). Por eso el formulario pide explícitamente cuál
 *  de las dos cosas es, en vez de asumir que toda excepción es un cierre.
 */
function Excepciones({ resourceId }: { resourceId: string }) {
  const [items, setItems] = useState<ExcepcionDeAgenda[]>([])
  const [dia, setDia] = useState('')
  const [desde, setDesde] = useState('09:00')
  const [hasta, setHasta] = useState('19:00')
  const [abre, setAbre] = useState('cierra')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const datos = await api.get<ExcepcionDeAgenda[]>(`/resources/${resourceId}/exceptions`)
      setItems((Array.isArray(datos) ? datos : []).slice().sort(
        (a, b) => a.day.localeCompare(b.day),
      ))
    } catch (err) {
      setError(describirError(err))
    }
  }, [resourceId])

  useEffect(() => { void cargar() }, [cargar])

  async function agregar() {
    setGuardando(true)
    setError(null)
    try {
      await api.post(`/resources/${resourceId}/exceptions`, {
        day: dia, starts_at: `${desde}:00`, ends_at: `${hasta}:00`,
        available: abre === 'abre',
      })
      await cargar()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setGuardando(false)
    }
  }

  async function borrar(id: number) {
    setError(null)
    try {
      await api.del(`/resources/${resourceId}/exceptions/${id}`)
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  /** `2026-08-24` → `24-08-2026`, el formato visible del ecosistema. */
  const fecha = (iso: string) => `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Excepciones por fecha</CardTitle>
        <CardDescription>
          Un día concreto que se cierra (un feriado) o que se abre aunque la
          agenda no lo cubra (un sábado puntual). Le gana a los bloques.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin excepciones.</p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {items.map((e) => (
              <li key={e.id} className="flex items-center gap-3">
                <span className="w-24 font-medium tabular-nums">{fecha(e.day)}</span>
                <span className="tabular-nums">
                  {e.starts_at.slice(0, 5)} – {e.ends_at.slice(0, 5)}
                </span>
                <span className={e.available ? 'text-emerald-600' : 'text-destructive'}>
                  {e.available ? 'abre' : 'cierra'}
                </span>
                <Button
                  size="icon" variant="ghost"
                  className="size-7 text-destructive hover:text-destructive"
                  aria-label={`Borrar excepción ${fecha(e.day)}`}
                  onClick={() => borrar(e.id)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-2 border-t pt-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`exc-dia-${resourceId}`}>Fecha</Label>
            <Input
              id={`exc-dia-${resourceId}`} type="date"
              value={dia} onChange={(e) => setDia(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`exc-desde-${resourceId}`}>Desde</Label>
            <Input
              id={`exc-desde-${resourceId}`} type="time" className="w-28"
              value={desde} onChange={(e) => setDesde(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`exc-hasta-${resourceId}`}>Hasta</Label>
            <Input
              id={`exc-hasta-${resourceId}`} type="time" className="w-28"
              value={hasta} onChange={(e) => setHasta(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`exc-tipo-${resourceId}`}>Qué hace</Label>
            <Select value={abre} onValueChange={setAbre}>
              <SelectTrigger id={`exc-tipo-${resourceId}`} className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cierra">Cierra</SelectItem>
                <SelectItem value="abre">Abre</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button onClick={agregar} disabled={guardando || !dia}>Agregar excepción</Button>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}
