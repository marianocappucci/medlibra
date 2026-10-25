"""`GET /api/nodo/conexion`: si esta instalación es la PC del consultorio (un nodo de LibraEdge) y si ve a la web (ADR-045).

Es lo que lee el cartel «Sin conexión» de `libra-ui` (`useConsultarConexionDelNodo`, ADR-077): `{es_nodo, en_linea, node_id,
a_facturar}`. Fuera de un nodo contesta `es_nodo: false` y el cartel deja de consultar. MedLibra no factura, así que
`a_facturar` es siempre 0: la consulta la manda a Contalibra la web cuando sube la atención (`atencion_nodo.py`).

La abre cualquier usuario de la instancia (`staff_or_admin`, como la barra del pie): la lee la pantalla en cuanto carga la sesión.
"""
from fastapi import APIRouter

from .. import offline

router = APIRouter(tags=["nodo"])


@router.get("/api/nodo/conexion")
def conexion_del_nodo() -> dict:
    node_id = offline.nodo()
    return {
        "es_nodo": node_id is not None,
        # Fuera de un nodo «en línea» no significa nada: el cartel no se dibuja.
        "en_linea": True if node_id is None else offline.en_linea(),
        "node_id": node_id,
        "a_facturar": 0,
    }
