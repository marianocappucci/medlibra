// Shim sobre libra-ui/Layout (extraído 2026-07-26, era idéntico en
// Gestiolibra/MedLibra/VentaLibra salvo NAV_ITEMS/branding -- ver
// wiki/analyses/auditoria-duplicacion-familia-libra.md).
import { CalendarDays, LayoutDashboard, ScrollText, Settings, UserCog, Users } from 'lucide-react'
import { createLayout } from 'libra-ui/Layout'
import { LOGO, WORDMARK } from '@/branding'

export const Layout = createLayout({
  productName: 'MedLibra',
  productInitial: 'M',
  // El logo y el nombre en Montserrat Bold. Las clases salen de `@/branding`,
  // el mismo archivo que usa el login: es lo que garantiza que las dos
  // pantallas escriban "MedLibra" igual.
  //
  // El override de colapsado NO es decorativo: con la sidebar en modo icono el
  // ancho util son 32 px y sin bajarlo el logo de 36 se sale de la barra.
  logo: {
    src: LOGO,
    className: 'h-9 w-9 group-data-[collapsible=icon]:h-8 group-data-[collapsible=icon]:w-8',
  },
  // 🔴 El interlineado va PEGADO al tamano (`/[21px]`) y no como `leading-*`
  // aparte: en Tailwind v4 una utilidad de tamano emite tambien `line-height`,
  // asi que el `leading-none` que libra-ui pone por defecto perderia contra
  // este `text-[15px]` y el nombre se quedaria con 22,5 px de caja.
  // 21 = 36 (el alto del logo) menos los 15 de la linea de la empresa.
  wordmarkClassName: `${WORDMARK} text-[15px]/[21px]`,
  navItems: [
    { to: '/agenda', label: 'Agenda', icon: CalendarDays },
    { to: '/pacientes', label: 'Pacientes', icon: Users },
    { to: '/reportes', label: 'Dashboard', icon: LayoutDashboard, adminOnly: true },
    // 🔴 Facturación NO está: sale de la vista por pedido del humano
    // (2026-08-22). La facturación de este producto pasa a Contalibra, que es
    // donde vive la contabilidad; ver ADR-034.
    { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
    // Junto a Usuarios: se mira para responder "quien hizo esto".
    { to: '/logs', label: 'Logs', icon: ScrollText, adminOnly: true },
    { to: '/configuracion', label: 'Configuración', icon: Settings, adminOnly: true },
  ],
})
