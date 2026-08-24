/** Consultorios: las salas donde se atiende.
 *
 *  🔴 **Un consultorio no es un profesional.** Son las dos cosas que un turno
 *  ocupa, y son escasas por separado: el profesional tiene una agenda, la sala
 *  tiene capacidad uno. Modelarlas juntas es lo que hacía que dos agendas
 *  impecables se pisaran en la puerta del Consultorio 2 sin que nada protestara
 *  (ADR-030).
 *
 *  Se cargan **antes** que los profesionales a propósito: un bloque de agenda
 *  necesita decir en qué consultorio atiende, así que sin consultorios cargados
 *  no se puede armar ninguna agenda.
 */
import { useCallback, useEffect, useState } from 'react'
import { api, type Branch, type Consultorio } from '../../api'
import { Button } from '@/components/ui/button'
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  CampoActivo, ListaDelCatalogo, PieDeFormulario, comoIdentificador, describirError,
} from './catalogo'

const SIN_SEDE = '__ninguna__'
const VACIO = { id: '', name: '', branch_id: SIN_SEDE, active: true }

export function ConsultoriosCard() {
  const [consultorios, setConsultorios] = useState<Consultorio[]>([])
  const [sedes, setSedes] = useState<Branch[]>([])
  const [form, setForm] = useState({ ...VACIO })
  const [elegido, setElegido] = useState<string | null>(null)
  const [editando, setEditando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const [c, b] = await Promise.all([
        api.get<Consultorio[]>('/consultorios'),
        api.get<Branch[]>('/branches'),
      ])
      setConsultorios(Array.isArray(c) ? c : [])
      setSedes(Array.isArray(b) ? b : [])
    } catch (err) {
      setError(describirError(err))
    } finally {
      setCargando(false)
    }
  }, [])

  useEffect(() => { void cargar() }, [cargar])

  function editar(id: string) {
    const c = consultorios.find((x) => x.id === id)
    setElegido(id)
    setError(null)
    if (!c) return
    setEditando(true)
    setForm({
      id: c.id, name: c.name,
      branch_id: c.branch_id ?? SIN_SEDE, active: c.active,
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
        await api.put(`/consultorios/${form.id}`, cuerpo)
      } else {
        const id = form.id || comoIdentificador(form.name)
        await api.post('/consultorios', { id, ...cuerpo })
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
      await api.del(`/consultorios/${form.id}`)
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
        titulo="Consultorios"
        descripcion="Las salas. Un turno ocupa un consultorio además del profesional, y dos profesionales no pueden compartir sala a la misma hora."
        items={consultorios}
        elegido={elegido}
        onElegir={editar}
        nombre={(c) => c.name}
        detalleDeFila={(c) => nombreSede(c.branch_id)}
        vacio={
          cargando
            ? 'Cargando…'
            : 'Todavía no hay consultorios. Creá el primero abajo: un bloque de agenda necesita uno para poder existir.'
        }
        acciones={editando && <Button variant="outline" onClick={limpiar}>Nuevo consultorio</Button>}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {editando ? `Editar «${form.name}»` : 'Nuevo consultorio'}
          </CardTitle>
          <CardDescription>
            Dar de baja un consultorio con agenda o turnos asociados no lo borra:
            se desactiva y sale de las listas, conservando el historial.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 md:max-w-2xl" onSubmit={guardar}>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="cons-nombre">Nombre</Label>
                <Input
                  id="cons-nombre" required value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="cons-id">Identificador</Label>
                <Input
                  id="cons-id" disabled={editando}
                  placeholder={comoIdentificador(form.name) || 'consultorio-1'}
                  value={form.id}
                  onChange={(e) => setForm({ ...form, id: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="cons-sede">Sede</Label>
                <Select
                  value={form.branch_id}
                  onValueChange={(v) => setForm({ ...form, branch_id: v })}
                >
                  <SelectTrigger id="cons-sede"><SelectValue /></SelectTrigger>
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
              id="cons-activo" checked={form.active}
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
    </div>
  )
}
