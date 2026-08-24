/** Prestaciones: qué se hace y cuánto sale en cada sede.
 *
 *  ⚠️ **La duración de la prestación ya no manda en la agenda.** Desde ADR-030
 *  cuánto dura un turno lo fija el **bloque de agenda** (10 a 30 minutos): la
 *  prestación dice *qué* se hace, no cuánto ocupa. Este campo sigue existiendo
 *  porque es el valor que se propone al armar un bloque y porque un turno dado
 *  sobre una jornada cargada por el camino viejo —sin bloque— lo sigue usando.
 *
 *  El precio es **por sede** (`/services/{id}/prices`), que es como lo modela el
 *  backend: la misma consulta puede costar distinto en dos consultorios. Una
 *  prestación sin precio en la sede del turno se completa **sin facturar**.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  api, type Branch, type PrecioDeServicio, type Service,
} from '../../api'
import { Button } from '@/components/ui/button'
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  CampoActivo, ListaDelCatalogo, PieDeFormulario, comoIdentificador, describirError,
} from './catalogo'

const VACIO = { id: '', name: '', duration_minutes: '20', active: true }

function pesos(valor: string | number): string {
  return new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' })
    .format(Number(valor))
}

export function PrestacionesCard() {
  const [prestaciones, setPrestaciones] = useState<Service[]>([])
  const [sedes, setSedes] = useState<Branch[]>([])
  const [elegida, setElegida] = useState<string | null>(null)
  const [form, setForm] = useState({ ...VACIO })
  const [editando, setEditando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const [s, b] = await Promise.all([
        api.get<Service[]>('/services'),
        api.get<Branch[]>('/branches'),
      ])
      setPrestaciones(Array.isArray(s) ? s : [])
      setSedes(Array.isArray(b) ? b : [])
    } catch (err) {
      setError(describirError(err))
    } finally {
      setCargando(false)
    }
  }, [])

  useEffect(() => { void cargar() }, [cargar])

  function editar(id: string) {
    const s = prestaciones.find((x) => x.id === id)
    setElegida(id)
    setError(null)
    if (!s) return
    setEditando(true)
    setForm({
      id: s.id, name: s.name,
      duration_minutes: String(s.duration_minutes), active: s.active,
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
      name: form.name,
      duration_minutes: Number(form.duration_minutes),
      active: form.active,
    }
    try {
      if (editando) {
        await api.put(`/services/${form.id}`, cuerpo)
      } else {
        const id = form.id || comoIdentificador(form.name)
        await api.post('/services', { id, ...cuerpo })
        setElegida(id)
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
      await api.del(`/services/${form.id}`)
      setElegida(null)
      limpiar()
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  return (
    <div className="grid gap-4">
      <ListaDelCatalogo
        titulo="Prestaciones"
        descripcion="Qué se hace en la consulta. Cuánto dura un turno lo fija el bloque de agenda, no la prestación."
        items={prestaciones}
        elegido={elegida}
        onElegir={editar}
        nombre={(s) => s.name}
        detalleDeFila={(s) => `${s.duration_minutes} min sugeridos`}
        vacio={cargando ? 'Cargando…' : 'Todavía no hay prestaciones. Creá la primera abajo.'}
        acciones={editando && <Button variant="outline" onClick={limpiar}>Nueva prestación</Button>}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {editando ? `Editar «${form.name}»` : 'Nueva prestación'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:max-w-2xl" onSubmit={guardar}>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="grid gap-1.5 md:col-span-2">
                <Label htmlFor="prest-nombre">Nombre</Label>
                <Input
                  id="prest-nombre" required value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="prest-dur">Duración sugerida (min)</Label>
                <Input
                  id="prest-dur" type="number" min={1} required
                  value={form.duration_minutes}
                  onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5 md:col-span-2">
                <Label htmlFor="prest-id">Identificador</Label>
                <Input
                  id="prest-id" disabled={editando}
                  placeholder={comoIdentificador(form.name) || 'consulta'}
                  value={form.id}
                  onChange={(e) => setForm({ ...form, id: e.target.value })}
                />
              </div>
            </div>
            <CampoActivo
              id="prest-activa" checked={form.active} etiqueta="Activa"
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

      {elegida && prestaciones.some((s) => s.id === elegida) && (
        <PreciosDeLaPrestacion key={elegida} serviceId={elegida} sedes={sedes} />
      )}
    </div>
  )
}

/** El precio de la prestación, uno por sede.
 *
 *  Se listan **todas** las sedes y no sólo las que ya tienen precio: una
 *  prestación sin precio en una sede no factura al completarse, y eso es
 *  información, no una fila que falta.
 */
function PreciosDeLaPrestacion({ serviceId, sedes }: {
  serviceId: string
  sedes: Branch[]
}) {
  const [precios, setPrecios] = useState<Record<string, string>>({})
  const [borrador, setBorrador] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState('')

  const cargar = useCallback(async () => {
    try {
      const items = await api.get<PrecioDeServicio[]>(`/services/${serviceId}/prices`)
      const mapa = Object.fromEntries(
        (Array.isArray(items) ? items : []).map((p) => [p.branch_id, String(p.price)]),
      )
      setPrecios(mapa)
      setBorrador(mapa)
    } catch (err) {
      setError(describirError(err))
    }
  }, [serviceId])

  useEffect(() => { void cargar() }, [cargar])

  async function guardar(branchId: string) {
    setGuardando(branchId)
    setError(null)
    try {
      await api.put(`/services/${serviceId}/prices`, {
        branch_id: branchId, price: borrador[branchId] ?? '0',
      })
      await cargar()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setGuardando('')
    }
  }

  async function quitar(branchId: string) {
    setError(null)
    try {
      await api.del(`/services/${serviceId}/prices/${branchId}`)
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Precio por sede</CardTitle>
        <CardDescription>
          Cuánto se cobra esta prestación en cada sede. Sin precio cargado, el
          turno se completa sin facturar.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {sedes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No hay sedes cargadas: el precio es por sede, así que primero hay que
            crear una.
          </p>
        ) : (
          sedes.map((s) => (
            <div key={s.id} className="flex flex-wrap items-end gap-2">
              <div className="grid gap-1.5">
                <Label htmlFor={`precio-${s.id}`}>{s.name}</Label>
                <Input
                  id={`precio-${s.id}`} type="number" min={0} step="0.01"
                  className="w-40"
                  placeholder="sin precio"
                  value={borrador[s.id] ?? ''}
                  onChange={(e) => setBorrador({ ...borrador, [s.id]: e.target.value })}
                />
              </div>
              <Button
                variant="outline"
                disabled={guardando === s.id || !borrador[s.id]}
                onClick={() => guardar(s.id)}
              >
                {guardando === s.id ? 'Guardando…' : 'Guardar'}
              </Button>
              {precios[s.id] !== undefined && (
                <Button
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => quitar(s.id)}
                >
                  Quitar
                </Button>
              )}
              <span className="pb-2 text-xs text-muted-foreground">
                {precios[s.id] !== undefined ? `Vigente: ${pesos(precios[s.id])}` : 'Sin precio'}
              </span>
            </div>
          ))
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}
