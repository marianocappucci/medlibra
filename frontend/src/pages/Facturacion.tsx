import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { api, ApiError, type ArcaConfig } from '../api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form'
import { Skeleton } from '@/components/ui/skeleton'
import { Receipt } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

// punto_venta se maneja como string en el form (evita la friccion de tipos
// entre z.coerce.number() y react-hook-form) y se convierte a number recien
// al armar el payload para la API.
const arcaConfigSchema = z.object({
  cuit: z.string().trim().min(1, 'El CUIT es obligatorio'),
  punto_venta: z.string().trim().regex(/^\d+$/, 'Punto de venta inválido'),
  certificado_path: z.string().trim().min(1, 'Falta el path del certificado'),
  clave_path: z.string().trim().min(1, 'Falta el path de la clave'),
  ambiente: z.enum(['homologacion', 'produccion']),
})

type ArcaConfigFormValues = z.infer<typeof arcaConfigSchema>

const EMPTY_VALUES: ArcaConfigFormValues = {
  cuit: '', punto_venta: '1', certificado_path: '', clave_path: '', ambiente: 'homologacion',
}

export function Facturacion() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [forbidden, setForbidden] = useState(false)
  const [saved, setSaved] = useState(false)

  const form = useForm<ArcaConfigFormValues>({
    resolver: zodResolver(arcaConfigSchema),
    defaultValues: EMPTY_VALUES,
  })

  useEffect(() => {
    loadConfig()
  }, [])

  function describeError(err: unknown): string {
    if (err instanceof ApiError) return err.detail
    return 'Error de conexión.'
  }

  async function loadConfig() {
    setLoading(true)
    setError(null)
    setForbidden(false)
    try {
      const cfg = await api.get<ArcaConfig | null>('/config/arca')
      if (cfg) {
        form.reset({
          cuit: cfg.cuit,
          punto_venta: String(cfg.punto_venta),
          certificado_path: cfg.certificado_path,
          clave_path: cfg.clave_path,
          ambiente: cfg.ambiente as 'homologacion' | 'produccion',
        })
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setForbidden(true)
      } else {
        setError(describeError(err))
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(values: ArcaConfigFormValues) {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await api.put('/config/arca', { ...values, punto_venta: Number(values.punto_venta) })
      setSaved(true)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  if (forbidden) {
    return (
      <div className="grid gap-4">
        <TituloPantalla icono={Receipt}>Facturación</TituloPantalla>
        <p className="text-sm text-muted-foreground">
          No tenés acceso a facturación (requiere rol admin y el módulo "facturacion" habilitado
          en el plan).
        </p>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <TituloPantalla icono={Receipt}>Facturación</TituloPantalla>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {saved && <p className="text-sm text-emerald-600">Configuración guardada.</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Configuración ARCA</CardTitle>
          <CardDescription>
            Datos fiscales de la instancia (única "empresa" por consultorio). El certificado y la
            clave se referencian por path en el filesystem del servidor — subir el archivo real
            es tarea manual del admin todavía.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-48" />
          ) : (
            <Form {...form}>
              <form className="flex flex-wrap items-start gap-3" onSubmit={form.handleSubmit(handleSubmit)}>
                <FormField
                  control={form.control}
                  name="cuit"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>CUIT</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-40" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="punto_venta"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Punto de venta</FormLabel>
                      <FormControl>
                        <Input type="number" min={1} {...field} className="w-28" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="ambiente"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Ambiente</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-44">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="homologacion">Homologación</SelectItem>
                          <SelectItem value="produccion">Producción</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="certificado_path"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Path del certificado</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-56" placeholder="/ruta/certificado.crt" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="clave_path"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Path de la clave</FormLabel>
                      <FormControl>
                        <Input {...field} className="w-56" placeholder="/ruta/clave.key" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <Button type="submit" disabled={saving} className="mt-6">
                  {saving ? 'Guardando…' : 'Guardar'}
                </Button>
              </form>
            </Form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
