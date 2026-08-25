"""El cableado de LibraCore al arrancar: su base, su schema y su caja.

Era `app/services/billing.py` hasta el 2026-08-24. Cuando la facturación de este
producto se fue a [[contalibra]] (ADR-036), de ese archivo sólo quedó en pie esta
función — y `billing` pasó a ser un nombre que mentía: lo que hace no tiene nada
que ver con facturar.

🔴 **Sigue siendo imprescindible aunque MedLibra ya no facture.**
`libracore.db` es sqlite3 crudo con su propia conexión, separada del engine de
LibraGenda, y ahí viven **los usuarios** (ver `app/main.py`: la tabla `usuarios`
está en la base de LibraCore, no en la del dominio). Sin este `configure()` la
app no levanta: no hay schema, no hay usuarios y no hay caja por defecto.
"""
import os

from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db.schema import init_core_schema


def configure(db_path: str) -> None:
    """Llamar una vez al arrancar: configura `libracore.db` contra su propio
    destino, asegura el schema compartido y crea una caja por defecto."""
    # 🔴 **Este producto corre sobre PostgreSQL y nada mas.** La guarda va aca,
    # en el arranque del producto, y no dentro de `libracore.db.core`: el motor
    # tiene que poder abrir un SQLite igual, porque de eso vive la herramienta
    # de diagnostico `python -m libracore.db.schema_dump`, que vuelca el schema
    # de un archivo viejo o de la base de LibraEdge. La regla "este producto no
    # habla con otro motor" es del producto, no del motor.
    #
    # Aca habia un `if not es_url_postgres(...)` que salteaba el `makedirs`
    # cuando el destino era una URL. Existia para evitar un defecto medido: con
    # una URL, `os.path.dirname()` devuelve `postgresql://usuario:clave@host` y
    # `makedirs` lo creaba como carpeta --- **la contrasena escrita en el nombre
    # de un directorio**, que ademas caia dentro del checkout bind-mounteado y
    # se colaba en la imagen del siguiente build. Encontrado el 2026-08-10.
    #
    # Con la guarda ese camino no existe: si no hay ruta de archivo posible, no
    # hay carpeta que crear ni defecto que evitar. El bloque entero se va.
    if not libracore_core.es_url_postgres(str(db_path)):
        raise RuntimeError(
            "MedLibra corre solo sobre PostgreSQL y recibio {!r}, que es una "
            "ruta de archivo. El modo SQLite se retiro el 2026-08-12: no chequea "
            "las FK, tipa dinamicamente y acepta cadenas donde la base pide "
            "enteros.".format(db_path)
        )
    libracore_core.configure(db_path)
    conn = libracore_core.get_connection()
    try:
        init_core_schema(conn)
        conn.commit()
    finally:
        conn.close()
    if db_caja.get_default_caja_id() is None:
        caja_id = db_caja.create_caja_config(
            "Caja Consultorio", "", list(db_caja.MEDIOS_PAGO_LABELS),
        )
        db_caja.set_default_caja(caja_id)
