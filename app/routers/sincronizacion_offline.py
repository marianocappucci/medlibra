"""El central expone la sincronización del nodo offline: `/sync/v1/push`, `/pull`, `/ticket-arca` y `/carga-inicial`.

PR 10 del plan «GestioLibra, MedLibra y LibraDesk en la versión de escritorio» (ADR-045). Es el mismo armado que
LibraClub (ADR-023), con las operaciones de MedLibra y sin lo que este producto no tiene (caja, ventas, ARCA).

## Por qué se monta siempre, y no sólo en las instancias con nodos

El gateo está del otro lado: sin un nodo registrado no existe **ningún secreto válido**, así que en una instancia sin
nodos las rutas responden 401 a todo. Montarlas condicionalmente agregaría una bandera más que puede quedar mal puesta, y
el modo de fallar sería el peor posible: un nodo instalado que no puede sincronizar contra un central que «debería» tener
el endpoint.

## La conexión es por request

Se le pasa `libracore.db.core.get_connection` —la fábrica del motor— y no una conexión armada: el router abre una por
request (ver `create_sync_router` en LibraEdge). En MedLibra el dominio y LibraCore son la misma base (ADR-044), así que
esa conexión ve `patients`, `walkins` y `node_identity` a la vez.

## Qué se aplica

Un `Despachador` (libraedge ADR-007) con **todas** las operaciones que un nodo de MedLibra sube:

| Operación | De quién es | Qué trae |
|---|---|---|
| `turno.atendido` | LibraGenda (ADR-019), con el envío a ContaLibra de MedLibra | la atención de un turno (en curso, atendido, «no vino») y, al completar, la consulta con sus pagos |
| `paciente.alta` | MedLibra (`pacientes_nodo.py`) | un paciente dado de alta sin conexión: se une al que tenga su DNI o recibe su `p-NNN` |
| `nota.alta`, `receta.alta`, `pedido_estudio.alta`, `consentimiento.alta` | MedLibra (`historia_en_nodo.py`) | la historia clínica cargada sin conexión, con el mismo id |
| `walkin.registrado`, `walkin.estado` | MedLibra (`walkins_nodo.py`) | la demanda espontánea anotada y su pase de estado |

Lo que no tiene aplicador **no se marca aplicado**: va a revisión manual (`libraedge-central revision
listar|reintentar|descartar`, con `LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador`).

El router además controla la versión del esquema (`version_de_alembic`: 409 si el nodo no está migrado igual que el
central). MedLibra no factura: no presta el ticket de ARCA (`/sync/v1/ticket-arca` contesta 501) ni tiene carga inicial
de existencias.
"""

from libracore.db.core import get_connection
from libraedge.sync.api import create_sync_router
from libraedge.sync.despacho import Despachador
from libraedge.sync.esquema import version_de_alembic

from app.services import atencion_nodo, historia_en_nodo, pacientes_nodo, walkins_nodo


def armar_despachador() -> Despachador:
    """Las operaciones que el central de MedLibra sabe aplicar (ver el docstring del módulo). Registrar dos veces un mismo
    tipo falla al arrancar: es la regla del `Despachador`."""
    despachador = Despachador()
    pacientes_nodo.registrar_en(despachador)
    historia_en_nodo.registrar_en(despachador)
    walkins_nodo.registrar_en(despachador)
    atencion_nodo.registrar_en(despachador)
    return despachador


despachador = armar_despachador()

router = create_sync_router(get_connection, despachador=despachador, version_esquema=version_de_alembic)
