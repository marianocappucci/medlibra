/** El armador de la agenda de un profesional.
 *
 *  Un bloque es una frase: *"la Dra. Vidal atiende **los lunes de 9 a 13** en el
 *  **Consultorio 2**, turnos de **20 minutos**, **hasta el 31 de diciembre**"*.
 *  Ver ADR-030 para por qué no se guarda como `Availability` del motor.
 *
 *  🔴 **El formulario deja elegir VARIOS días de una vez, y crea un bloque por
 *  día.** El backend modela un bloque por día de la semana a propósito —así el
 *  miércoles puede estar en otra sala—, pero cargar "lunes a viernes de 9 a 13"
 *  como cinco altas idénticas a mano, por cada profesional, es el gesto que más
 *  se repite en toda esta pantalla. La multiplicación va acá y no en el backend:
 *  el modelo de datos no tiene por qué cargar con una comodidad de la UI.
 *
 *  ⚠️ Las horas son **hora de pared de la sede**, no del navegador (ADR-028).
 */
import { useCallback, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import {
  DIAS_SEMANA, api,
  type BloqueDeAgenda, type Consultorio, type OpcionesDeBloque,
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
import { describirError } from './catalogo'

const MODALIDAD_LABEL: Record<string, string> = {
  turnos: 'Por turnos',
  espontanea: 'Demanda espontánea',
}

/** `09:00:00` → `09:00`, que es lo que entiende un `<input type="time">`. */
function aHoraCorta(valor: string): string {
  return valor.slice(0, 5)
}

/** `2026-08-24` → `24-08-2026`, el formato visible del ecosistema. Se corta el
 *  string en vez de construir un `Date`: un `YYYY-MM-DD` pasado por `Date` se
 *  interpreta como medianoche UTC y en UTC-3 muestra el día anterior. */
function comoFecha(iso: string): string {
  return `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}`
}

const HABILES = [0, 1, 2, 3, 4]

export function BloquesDeAgenda({ resourceId, consultorios }: {
  resourceId: string
  consultorios: Consultorio[]
}) {
  const [bloques, setBloques] = useState<BloqueDeAgenda[]>([])
  const [opciones, setOpciones] = useState<OpcionesDeBloque | null>(null)
  const [dias, setDias] = useState<number[]>(HABILES)
  const [consultorio, setConsultorio] = useState('')
  const [desde, setDesde] = useState('09:00')
  const [hasta, setHasta] = useState('13:00')
  const [vigenteDesde, setVigenteDesde] = useState('')
  const [vigenteHasta, setVigenteHasta] = useState('')
  const [duracion, setDuracion] = useState('20')
  const [modalidad, setModalidad] = useState('turnos')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const [items, ops] = await Promise.all([
        api.get<BloqueDeAgenda[]>(`/agenda-blocks?resource_id=${resourceId}`),
        api.get<OpcionesDeBloque>('/agenda-blocks/opciones'),
      ])
      setBloques(Array.isArray(items) ? items : [])
      setOpciones(ops)
    } catch (err) {
      setError(describirError(err))
    }
  }, [resourceId])

  useEffect(() => { void cargar() }, [cargar])

  // La vigencia arranca hoy si nadie dice otra cosa: una agenda que se carga
  // hoy empieza a valer hoy, y pedirle la fecha a quien la carga es fricción
  // sobre el caso normal.
  useEffect(() => {
    if (!vigenteDesde) setVigenteDesde(new Date().toISOString().slice(0, 10))
  }, [vigenteDesde])

  useEffect(() => {
    if (!consultorio && consultorios.length > 0) setConsultorio(consultorios[0].id)
  }, [consultorio, consultorios])

  function alternarDia(dia: number) {
    setDias((actuales) => actuales.includes(dia)
      ? actuales.filter((d) => d !== dia)
      : [...actuales, dia].sort((a, b) => a - b))
  }

  async function agregar() {
    setGuardando(true)
    setError(null)
    try {
      // Secuencial y no `Promise.all`: si uno falla —por ejemplo, una duración
      // que el backend no acepta— hay que cortar ahí. En paralelo se crearían
      // los otros cuatro igual y el error diría una sola cosa mientras la
      // agenda quedó a medio cargar.
      for (const dia of dias) {
        await api.post('/agenda-blocks', {
          resource_id: resourceId,
          consultorio_id: consultorio,
          weekday: dia,
          starts_at: `${desde}:00`,
          ends_at: `${hasta}:00`,
          valid_from: vigenteDesde,
          valid_to: vigenteHasta || null,
          slot_minutes: Number(duracion),
          modality: modalidad,
        })
      }
      await cargar()
    } catch (err) {
      setError(describirError(err))
      // Se recarga igual: los días que sí entraron antes del error tienen que
      // aparecer en la lista, o el usuario los vuelve a cargar y se duplican.
      await cargar()
    } finally {
      setGuardando(false)
    }
  }

  async function borrar(id: string) {
    setError(null)
    try {
      await api.del(`/agenda-blocks/${id}`)
      await cargar()
    } catch (err) {
      setError(describirError(err))
    }
  }

  const nombreConsultorio = (id: string) =>
    consultorios.find((c) => c.id === id)?.name ?? id

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Agenda</CardTitle>
        <CardDescription>
          Cuándo, dónde y cómo atiende este profesional. Cada bloque vale para un
          día de la semana y se repite hasta la fecha de fin.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {consultorios.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No hay consultorios cargados: un bloque de agenda necesita uno.
            Cargalos en la sección Consultorios.
          </p>
        ) : bloques.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            🔴 Sin ningún bloque, este profesional <strong>no recibe turnos</strong>:
            toda alta se rechaza porque no hay con qué decir que sí.
          </p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {bloques.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-24 font-medium">{DIAS_SEMANA[b.weekday]}</span>
                <span className="tabular-nums">
                  {aHoraCorta(b.starts_at)} – {aHoraCorta(b.ends_at)}
                </span>
                <span className="text-muted-foreground">
                  {nombreConsultorio(b.consultorio_id)}
                </span>
                <span className="text-muted-foreground">
                  {b.modality === 'espontanea'
                    ? MODALIDAD_LABEL.espontanea
                    : `turnos de ${b.slot_minutes} min`}
                </span>
                <span className="text-xs text-muted-foreground">
                  desde {comoFecha(b.valid_from)}
                  {b.valid_to ? ` hasta ${comoFecha(b.valid_to)}` : ' · sin fin'}
                </span>
                <Button
                  size="icon" variant="ghost"
                  className="size-7 text-destructive hover:text-destructive"
                  aria-label={`Borrar ${DIAS_SEMANA[b.weekday]} ${aHoraCorta(b.starts_at)}`}
                  onClick={() => borrar(b.id)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="grid gap-3 border-t pt-3">
          <div className="grid gap-1.5">
            <Label>Días</Label>
            <div className="flex flex-wrap gap-1">
              {DIAS_SEMANA.map((nombre, i) => (
                <Button
                  key={nombre}
                  type="button"
                  size="sm"
                  variant={dias.includes(i) ? 'default' : 'outline'}
                  aria-pressed={dias.includes(i)}
                  onClick={() => alternarDia(i)}
                >
                  {nombre.slice(0, 3)}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-cons-${resourceId}`}>Consultorio</Label>
              <Select value={consultorio} onValueChange={setConsultorio}>
                <SelectTrigger id={`blq-cons-${resourceId}`} className="w-44">
                  <SelectValue placeholder="Consultorio…" />
                </SelectTrigger>
                <SelectContent>
                  {consultorios.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-desde-${resourceId}`}>Desde</Label>
              <Input
                id={`blq-desde-${resourceId}`} type="time" className="w-28"
                value={desde} onChange={(e) => setDesde(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-hasta-${resourceId}`}>Hasta</Label>
              <Input
                id={`blq-hasta-${resourceId}`} type="time" className="w-28"
                value={hasta} onChange={(e) => setHasta(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-modo-${resourceId}`}>Modalidad</Label>
              <Select value={modalidad} onValueChange={setModalidad}>
                <SelectTrigger id={`blq-modo-${resourceId}`} className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(opciones?.modalidades ?? ['turnos']).map((m) => (
                    <SelectItem key={m} value={m}>{MODALIDAD_LABEL[m] ?? m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* La duración no se muestra en demanda espontánea: ahí no hay
                turnos que durar, se atiende por orden de llegada. Ofrecerla
                igual haría creer que hace algo. */}
            {modalidad === 'turnos' && (
              <div className="grid gap-1.5">
                <Label htmlFor={`blq-dur-${resourceId}`}>Duración</Label>
                <Select value={duracion} onValueChange={setDuracion}>
                  <SelectTrigger id={`blq-dur-${resourceId}`} className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(opciones?.duraciones ?? []).map((d) => (
                      <SelectItem key={d} value={String(d)}>{d} min</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-vd-${resourceId}`}>Desde el día</Label>
              <Input
                id={`blq-vd-${resourceId}`} type="date"
                value={vigenteDesde} onChange={(e) => setVigenteDesde(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`blq-vh-${resourceId}`}>Repetir hasta</Label>
              <Input
                id={`blq-vh-${resourceId}`} type="date"
                value={vigenteHasta} onChange={(e) => setVigenteHasta(e.target.value)}
              />
            </div>
            <Button
              onClick={agregar}
              disabled={guardando || dias.length === 0 || !consultorio || !vigenteDesde}
            >
              {guardando ? 'Agregando…' : `Agregar ${dias.length} día${dias.length === 1 ? '' : 's'}`}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            «Repetir hasta» vacío = sin fecha de fin.
          </p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}
