import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './context/AuthContext.tsx'
import { cargarMarca } from 'libra-ui/marca'
import { cargarTema } from 'libra-ui/tema'
import { aplicarIdentidad } from 'libra-ui/identidad'
import { ErrorBoundary } from 'libra-ui/ErrorBoundary'
import { instalarReporteDeErrores } from 'libra-ui/errores-del-navegador'

// El tema de la suite (libra-ui ADR-007/008): aplica lo último guardado de inmediato y pide los colores a esta misma instancia. No espera
// ni puede fallar: sin red o con un error, la app arranca con los colores de siempre.
void cargarTema()

// La identidad del producto (libra-ui ADR-033): su acento (`--primary`, `--ring`, `--sidebar-*`, en claro y en oscuro) y el `theme-color`.
// Va en un `<style>`, así que el acento que el backoffice elige por instancia (`cargarTema`, en línea) sigue ganando.
aplicarIdentidad('medlibra')

// Los errores del navegador que nadie atrapó, al registro de errores de la instancia (libra-ui ADR-053, libracore ADR-045):
// `POST /api/errores-cliente`. Antes de montar, para que también quede lo que falla al arrancar.
instalarReporteDeErrores()

// La marca de la instancia (libra-ui ADR-098, marca blanca): si el revendedor cargo la suya, se aplica antes de pintar, asi la primera visita
// no parpadea con el nombre del producto. Espera como mucho 2 s y nunca falla: sin marca propia la app arranca como siempre.
void cargarMarca().finally(() =>
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {/* «Algo falló» en vez de la pantalla en blanco cuando un render revienta; afuera de todo, así atrapa también a los providers. */}
      <ErrorBoundary>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </ErrorBoundary>
    </StrictMode>,
  ),
)

// Instalable como aplicación: el service worker no cachea nada (ver
// `public/sw.js`), sólo existe para que el navegador ofrezca instalarla.
// El fallo se traga a propósito: que no se pueda registrar —contexto sin
// https, un navegador que no lo soporta— no tiene por qué romper la app.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
