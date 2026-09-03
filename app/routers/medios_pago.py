"""Con qué se puede cobrar una consulta.

🔴 **La lista es del motor, no de este producto.** Hasta el 2026-08-24 vivía
hardcodeada en `frontend/src/pages/Agenda.tsx` —cuatro medios: efectivo,
transferencia, **tarjeta** y mercadopago— y ese `tarjeta` **no existía en el
vocabulario de la familia**. Llegaba igual a [[contalibra]], creaba su
movimiento de caja y aparecía en el cierre como un bucket suelto con el nombre
crudo: la plata bien contada y el reparto mal.

Peor todavía: era la misma copia byte a byte que tenía Gestiolibra, así que dos
productos inventaban el mismo medio por separado.

Ahora sale de `libracore.medios_pago`, que es la única lista de la familia (ver
`wiki/concepts/medios-de-pago-familia-libra.md`). Un medio nuevo allá aparece acá
sin tocar nada, y la tarjeta viene **partida en débito y crédito** — que es como
ARCA la declara.

## Por qué no se ofrece la cuenta corriente

No es un medio de cobro: es la marca de que la operación se hizo a crédito. Un
consultorio que completa un turno está cobrando; ofrecerla ahí dejaría registrar
un cobro que no cobra nada, y del otro lado sumaría deuda del paciente en vez de
plata en la caja.
"""
from fastapi import APIRouter
from libracore import medios_pago as vocabulario

router = APIRouter(prefix="/medios-pago", tags=["medios-pago"])


@router.get("")
def listar() -> list[dict]:
    """`[{id, label}]` para el selector de medio de pago al completar un turno."""
    return vocabulario.para_selector(incluir_cuenta_corriente=False)
