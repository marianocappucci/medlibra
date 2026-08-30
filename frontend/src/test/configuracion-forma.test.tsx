// La FORMA de la pantalla de Configuración de este producto.
//
// La pantalla la rinde `libra-ui/Configuracion`, que tiene sus propios tests:
// lo que se prueba acá es **lo que declara MedLibra**, que es lo único que vive
// en este repo y lo único que puede divergir del resto de la familia sin que
// nadie lo note.
//
// 🔴 Y hay dos ausencias que hay que sostener con un test, porque un agregado
// bien intencionado las rompe sin síntoma:
//
//  - **ARCA no va.** Desde el ADR-036 este producto no factura —la facturación
//    es de Contalibra— y `/config/arca` devuelve 404. Una pestaña de ARCA acá
//    guardaría un certificado que nadie usa y le diría al cliente que ya puede
//    facturar.
//  - **MercadoPago tampoco.** No hay cobro con QR de mostrador, así que no hay
//    endpoints del otro lado: las credenciales se guardarían contra un 404.
//
// El nombre del producto se afirma explícitamente porque **sale en el tutorial
// de Gmail**: es el que el cliente tiene que escribir al crear la contraseña de
// aplicación en su cuenta de Google. Si dijera "Contalibra", el tutorial sería
// peor que no estar — parece correcto y lleva a crear la credencial mal.
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Configuracion } from '../pages/Configuracion'

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    if (u.includes('/logo')) return Promise.resolve(new Response('', { status: 404 }))
    if (u.includes('/admin/smtp')) {
      return Promise.resolve(json({
        origen: 'entorno', host: '', port: 587, user: '', from_email: '', from_name: '',
        password_definida: false, password_indescifrable: false, configurado: false,
      }))
    }
    if (u.includes('/api/config/empresa')) {
      return Promise.resolve(json({
        empresa_nombre: '', empresa_direccion: '', empresa_cuit: '', empresa_telefono: '',
        empresa_email: '', empresa_iibb: '', empresa_iva_condition: 'Monotributista',
        empresa_inicio_actividades: '',
      }))
    }
    return Promise.resolve(json([]))
  }))
})

const montar = (ruta = '/configuracion') =>
  render(<MemoryRouter initialEntries={[ruta]}><Configuracion /></MemoryRouter>)

describe('la Configuración de MedLibra', () => {
  it('tiene las pestañas de la familia, en el orden del arranque de un consultorio', async () => {
    montar()

    const pestanias = (await screen.findAllByRole('tab')).map((t) => t.textContent)
    expect(pestanias).toEqual([
      'Empresa', 'Integraciones',
      // El orden importa: un consultorio se carga sin sede a la cual
      // pertenecer, una prestación sin poder ponerle precio —el precio es por
      // sede— y un bloque de agenda sin consultorio donde ubicarlo.
      'Sedes', 'Consultorios', 'Prestaciones', 'Profesionales',
      // Última: es la que más rompe si se toca sin querer.
      'Datos / Backup',
    ])
  })

  it('🔴 el correo es la ÚNICA integración: sin sub-navegación lateral', async () => {
    // Se afirma primero la ausencia de la barra lateral y no el contenido: si
    // alguien agrega una integración, esto falla en el acto diciendo que
    // apareció un botón de navegación, en vez de agotar el timeout buscando un
    // texto que dejó de estar a la vista porque cambió la sección por defecto.
    montar('/configuracion?seccion=integraciones')

    // El punto de espera es la barra de pestañas, que existe siempre. Esperar
    // el contenido del correo haría que el test se colgara 5 s y reportara
    // "timed out" cuando lo que pasó es que apareció otra integración y el
    // correo dejó de ser la sección por defecto.
    await screen.findAllByRole('tab')
    const navegacion = screen.queryAllByRole('button', { name: /MercadoPago|ARCA|Email \/ SMTP/ })
    expect(navegacion.map((b) => b.textContent),
      'con una sola integración el kit muestra el contenido directo, sin barra lateral').toEqual([])
    expect(screen.getByText(/Correo saliente/)).toBeInTheDocument()
  })

  it('🔴 no ofrece ARCA: este producto no factura', async () => {
    montar('/configuracion?seccion=integraciones')

    await screen.findAllByRole('tab')
    // Ni la sección, ni una pestaña propia, ni el formulario del certificado.
    expect(screen.queryByText(/ARCA/)).toBeNull()
    expect(screen.queryByRole('tab', { name: /ARCA/ })).toBeNull()
    expect(screen.queryByLabelText(/Punto de venta/)).toBeNull()
  })

  it('🔴 no ofrece MercadoPago: no hay cobro con QR acá', async () => {
    montar('/configuracion?seccion=integraciones')

    await screen.findAllByRole('tab')
    expect(screen.queryByText(/MercadoPago/)).toBeNull()
    expect(screen.queryByLabelText(/Access Token/)).toBeNull()
  })

  it('el tutorial de Gmail está, y nombra a MedLibra', async () => {
    // Sin el tutorial, quien configura el correo pone la contraseña de su
    // cuenta de Google, guarda, y el `forgot-password` sigue fallando sin decir
    // por qué: Gmail no acepta la contraseña normal desde una app externa.
    montar('/configuracion?seccion=integraciones&integracion=email')

    // `findAllByText` y no `findByText`: "contraseña de aplicación" aparece en
    // el título del acordeón Y en el cuerpo, y `findByText` reintenta ante
    // CUALQUIER error —incluido "hay más de una"— hasta agotar el timeout. El
    // test fallaba con "timed out" y no con "found multiple", que no dice nada
    // de lo que pasa.
    expect(await screen.findAllByText(/contraseña de aplicación/)).not.toHaveLength(0)
    expect(screen.getByText(/¿Cómo configurar Gmail/)).toBeInTheDocument()
    expect(screen.getByText('MedLibra')).toBeInTheDocument()
    // Y NO el nombre del producto del que salió la pantalla.
    expect(screen.queryByText('Contalibra')).toBeNull()
  })

  it('el botón de backup rápido está desde la primera pestaña', async () => {
    // Es lo que el cliente aprieta antes de hacer algo que lo pone nervioso:
    // tiene que estar sin entrar a Datos / Backup.
    montar()

    expect(await screen.findByRole('link', { name: /Backup rápido/ }))
      .toHaveAttribute('href', '/api/config/backup-ahora')
  })
})
