/** Las piezas que comparten las tres pantallas de parametrización de la agenda.
 *
 *  Sucursales, servicios y recursos son el mismo gesto tres veces: una lista
 *  arriba, un formulario de alta/edición, y —al elegir una fila— el detalle que
 *  cuelga de ella (los horarios de la sucursal, los precios del servicio, la
 *  disponibilidad del recurso). Lo que cambia son los campos; lo que se repite
 *  es el andamio.
 */
import type { ReactNode } from 'react'
import { ApiError } from '../../api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card'
import { cn } from '@/lib/utils'

export function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

/** Un identificador legible a partir del nombre.
 *
 *  La API pide un `id` explícito en el alta (es la clave con la que después se
 *  referencian los turnos), así que hay que inventarlo. Se deriva del nombre y
 *  **queda editable**: si dos servicios se llaman parecido, el alta devuelve
 *  409 y quien lo carga tiene que poder desambiguar sin adivinar qué pasó.
 */
export function comoIdentificador(nombre: string): string {
  return nombre
    .normalize('NFD')
    .split('')
    // Las marcas combinantes que deja NFD (U+0300 a U+036F). Se filtran por
    // codigo y no con un rango de regex escrito con los caracteres literales:
    // asi escrito el rango es invisible en el fuente y no se puede revisar.
    .filter((c) => c.charCodeAt(0) < 0x300 || c.charCodeAt(0) > 0x36f)
    .join('')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

/** La lista seleccionable de una entidad del catálogo. */
export function ListaDelCatalogo<T extends { id: string; active: boolean }>({
  titulo, descripcion, items, elegido, onElegir, nombre, detalleDeFila, vacio,
  acciones,
}: {
  titulo: string
  descripcion: string
  items: T[]
  elegido: string | null
  onElegir: (id: string) => void
  nombre: (item: T) => string
  /** La segunda línea de la fila: duración, sucursal, huso… */
  detalleDeFila: (item: T) => ReactNode
  vacio: string
  acciones?: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{titulo}</CardTitle>
        <CardDescription>{descripcion}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{vacio}</p>
        ) : (
          <ul className="grid gap-1">
            {items.map((item) => (
              <li key={item.id}>
                {/* Un `<button>` y no un `<div onClick>`: la lista se recorre
                    con el teclado y cada fila tiene que anunciar si está
                    elegida. `aria-pressed` es lo que lo dice. */}
                <button
                  type="button"
                  aria-pressed={elegido === item.id}
                  onClick={() => onElegir(item.id)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm',
                    'hover:bg-accent',
                    elegido === item.id && 'border-primary bg-accent',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{nombre(item)}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {detalleDeFila(item)}
                    </span>
                  </span>
                  {!item.active && <Badge variant="outline">Inactivo</Badge>}
                </button>
              </li>
            ))}
          </ul>
        )}
        {acciones}
      </CardContent>
    </Card>
  )
}

/** La casilla de "activo".
 *
 *  Un `<input type="checkbox">` nativo y no el `Switch` de shadcn: este
 *  producto no lo tiene vendorizado, y traerlo por una casilla sería sumarle
 *  un primitivo entero (y su dependencia de Radix) a los tres formularios más
 *  simples de la aplicación.
 */
export function CampoActivo({ id, checked, onChange, etiqueta = 'Activo' }: {
  id: string
  checked: boolean
  onChange: (valor: boolean) => void
  etiqueta?: string
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="checkbox"
        className="size-4 accent-primary"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <label htmlFor={id} className="text-sm font-medium">{etiqueta}</label>
    </div>
  )
}

/** El pie de un formulario de alta/edición. */
export function PieDeFormulario({ editando, guardando, onCancelar, onBorrar }: {
  editando: boolean
  guardando: boolean
  onCancelar: () => void
  onBorrar?: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="submit" disabled={guardando}>
        {guardando ? 'Guardando…' : editando ? 'Guardar cambios' : 'Crear'}
      </Button>
      <Button type="button" variant="outline" onClick={onCancelar}>
        {editando ? 'Cancelar edición' : 'Limpiar'}
      </Button>
      {editando && onBorrar && (
        <Button
          type="button" variant="outline"
          className="ml-auto text-destructive hover:text-destructive"
          onClick={onBorrar}
        >
          Borrar
        </Button>
      )}
    </div>
  )
}
