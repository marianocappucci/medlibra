import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Proxy de API en dev: mismo origen que el front (localhost:5173) hacia
// el backend FastAPI (localhost:8000) para que la cookie de sesion
// (ml_session) funcione sin lidiar con CORS/SameSite cross-origin --
// mismo truco que se usa en produccion, donde el build de este frontend
// se sirve desde el mismo proceso FastAPI (ver app/asgi.py).
const API_PATHS = [
  '/auth', '/branches', '/resources', '/services', '/patients',
  '/business', '/users', '/reminders', '/deposits', '/config',
  '/dashboard', '/appointments', '/health',
]

// Las claves del proxy se emiten como regex (Vite trata como RegExp toda
// clave que empieza con `^`) que exige que el path TERMINE ahi o siga con
// `/`. Con el match por prefijo simple de antes, una ruta de la SPA que
// EMPIEZA igual que un prefijo de la API quedaba secuestrada por el proxy y
// el navegador recibia el JSON del backend en vez de la pagina.
//
// Hoy este producto no tiene ninguna colision (`/pacientes` vs `/patients`
// difieren antes del final), asi que esto es preventivo: la trampa se
// activaria sola al agregar una ruta como `/configuracion` (capturada por
// `/config`) o `/dashboard-x`. Es lo que paso en VentaLibra el 2026-07-28
// con `/catalogo` y `/config-arca` -- ver
// wiki/concepts/estandares-desarrollo.md.
//
// Solo afecta al dev server: en produccion sirve FastAPI, que matchea rutas
// exactas y deja caer esos paths al catch-all de la SPA.
const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: Object.fromEntries(
      API_PATHS.map((apiPath) => [
        `^${escapeRegex(apiPath)}(?:/|$)`,
        { target: 'http://localhost:8000', changeOrigin: true },
      ]),
    ),
  },
})
