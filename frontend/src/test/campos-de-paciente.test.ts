// Guard: todo campo donde se elige un paciente ofrece darlo de alta ahí mismo (ADR-071, libra-ui v0.158.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir es que vuelva a nacer un desplegable de pacientes sin alta (el caso que lo originó:
// el mostrador de LibraDesk, donde un cliente no cargado no se podía elegir). Eso se ve en el JSX. El motor vive en
// `libra-ui/auditoria-de-clientes` y tiene sus propios tests allá.
//
// En MedLibra el cliente se llama **paciente** (y `patient` en el código), por eso las palabras. Un filtro de listado que no crea nada se marca con
// `cliente-sin-alta: <motivo>` en el renglón o en los tres de arriba.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarCamposDeCliente, describirCamposSinAlta } from 'libra-ui/auditoria-de-clientes'

const SRC = join(process.cwd(), 'src')

describe('todo campo que elige un paciente ofrece el alta', () => {
  const r = auditarCamposDeCliente(SRC, { palabras: ['client', 'paciente', 'patient'] })

  it('🔴 el control — el guard midió algo (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.campos).toBeGreaterThan(0)
    // Las dos pantallas que eligen paciente (Nuevo turno y Anotar llegada) ya son SelectCliente.
    expect(r.conAlta).toBeGreaterThanOrEqual(2)
  })

  it('🔴 ningún campo de paciente es un desplegable sin alta', () => {
    expect(describirCamposSinAlta(r.infracciones)).toEqual([])
  })
})
