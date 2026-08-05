// Shim sobre libra-ui/Layout (extraído 2026-07-26, era idéntico en
// Gestiolibra/MedLibra/VentaLibra salvo NAV_ITEMS/branding -- ver
// wiki/analyses/auditoria-duplicacion-familia-libra.md).
import { CalendarDays, LayoutDashboard, Receipt, ScrollText, UserCog, Users } from 'lucide-react'
import { createLayout } from 'libra-ui/Layout'

export const Layout = createLayout({
  productName: 'MedLibra',
  productInitial: 'M',
  navItems: [
    { to: '/agenda', label: 'Agenda', icon: CalendarDays },
    { to: '/pacientes', label: 'Pacientes', icon: Users },
    { to: '/reportes', label: 'Dashboard', icon: LayoutDashboard, adminOnly: true },
    { to: '/facturacion', label: 'Facturación', icon: Receipt, adminOnly: true },
    { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
    // Junto a Usuarios: se mira para responder "quien hizo esto".
    { to: '/logs', label: 'Logs', icon: ScrollText, adminOnly: true },
  ],
})
