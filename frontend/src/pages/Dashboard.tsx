import { useEffect, useState } from 'react'
import { api, ApiError, STATUS_LABELS, type DashboardSummary } from '../api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { LayoutDashboard } from 'lucide-react'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export function Dashboard() {
  const [dateFrom, setDateFrom] = useState(todayIso())
  const [dateTo, setDateTo] = useState(todayIso())
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
      <div className="flex items-center justify-between">
        <TituloPantalla icono={LayoutDashboard}>Dashboard</TituloPantalla>
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
      </div>

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
          <Card>
            <CardHeader>
              <CardDescription>Turnos</CardDescription>
              <CardTitle className="text-3xl">{summary.turnos.total_en_periodo}</CardTitle>
              <CardDescription>en el rango — {summary.turnos.hoy} hoy</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm text-muted-foreground">
                {Object.entries(summary.turnos.por_estado)
                  .filter(([, count]) => count > 0)
                  .map(([status, count]) => (
                    <li key={status} className="flex justify-between">
                      <span>{STATUS_LABELS[status as keyof typeof STATUS_LABELS] ?? status}</span>
                      <span className="font-medium text-foreground">{count}</span>
                    </li>
                  ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Pacientes</CardDescription>
              <CardTitle className="text-3xl">{summary.pacientes.total_activos}</CardTitle>
              <CardDescription>activos — {summary.pacientes.nuevos_en_periodo} nuevos en el rango</CardDescription>
            </CardHeader>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Recordatorios y señas</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm text-muted-foreground">
                <li className="flex justify-between">
                  <span>Recordatorios enviados</span>
                  <span className="font-medium text-foreground">{summary.recordatorios_enviados_en_periodo}</span>
                </li>
                <li className="flex justify-between">
                  <span>Señas pendientes</span>
                  <span className="font-medium text-foreground">{summary.senas_pendientes}</span>
                </li>
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
