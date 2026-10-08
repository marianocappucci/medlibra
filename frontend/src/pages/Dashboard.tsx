import { useEffect, useState } from 'react'
import { api, ApiError, STATUS_LABELS, type DashboardSummary } from '../api'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { TarjetaIndicador } from 'libra-ui/TarjetaIndicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS } from 'libra-ui/iconos-identidad'
import { hoyISO } from 'libra-ui/fechas'

export function Dashboard() {
  const [dateFrom, setDateFrom] = useState(hoyISO())
  const [dateTo, setDateTo] = useState(hoyISO())
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo])

  async function loadSummary() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<DashboardSummary>(
        `/dashboard?date_from=${dateFrom}&date_to=${dateTo}`,
      )
      setSummary(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('No tenés acceso al dashboard (requiere rol admin y el módulo "dashboard" habilitado en el plan).')
      } else {
        setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
      }
      setSummary(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid gap-4">
      <TituloPantalla
        icono={ICONOS.dashboard}
        acciones={
          <div className="flex items-end gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="date-from">Desde</Label>
              <Input id="date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-40" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="date-to">Hasta</Label>
              <Input id="date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-40" />
            </div>
          </div>
        }
      >
        Dashboard
      </TituloPantalla>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      )}

      {summary && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <TarjetaIndicador
            concepto="turnos" etiqueta="Turnos" valor={summary.turnos.total_en_periodo}
            ayuda={`en el rango — ${summary.turnos.hoy} hoy`}
          >
            <ul className="space-y-1">
              {Object.entries(summary.turnos.por_estado)
                .filter(([, count]) => count > 0)
                .map(([status, count]) => (
                  <li key={status} className="flex justify-between">
                    <span>{STATUS_LABELS[status as keyof typeof STATUS_LABELS] ?? status}</span>
                    <span className="font-medium text-foreground">{count}</span>
                  </li>
                ))}
            </ul>
          </TarjetaIndicador>

          <TarjetaIndicador
            concepto="pacientes" etiqueta="Pacientes" valor={summary.pacientes.total_activos}
            ayuda={`activos — ${summary.pacientes.nuevos_en_periodo} nuevos en el rango`}
          />

          <TarjetaIndicador concepto="recordatorios" etiqueta="Recordatorios y señas">
            <ul className="space-y-1">
              <li className="flex justify-between">
                <span>Recordatorios enviados</span>
                <span className="font-medium text-foreground">{summary.recordatorios_enviados_en_periodo}</span>
              </li>
              <li className="flex justify-between">
                <span>Señas pendientes</span>
                <span className="font-medium text-foreground">{summary.senas_pendientes}</span>
              </li>
            </ul>
          </TarjetaIndicador>
        </div>
      )}
    </div>
  )
}
