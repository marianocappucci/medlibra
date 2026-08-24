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
    # 🔴 `db_path` puede ser una URL de PostgreSQL, y entonces NO hay carpeta
    # que crear. Sin esta guarda, `os.path.dirname()` de
    # `postgresql://usuario:clave@host:5432/base` devuelve
    # `postgresql://usuario:clave@host:5432` y `makedirs` lo crea como
    # directorio: **la contraseña queda escrita en el nombre de una carpeta**.
    # Y donde el repo está bind-mounteado en `/app`, esa carpeta cae dentro del
    # checkout del VPS y el siguiente `docker build` la mete en la imagen.
    # Encontrado en VentaLibra el 2026-08-10, al cortar su demo a PostgreSQL.
    #
    # 🔴 **El criterio sale de LibraCore, no se escribe acá.** La lista a mano
    # que había —`("postgres://", "postgresql://")`— **no reconocía
    # `postgresql+psycopg://`**, que es la forma que este mismo arranque
    # anticipa unas líneas más abajo (`app/main.py`, al armar el engine de
    # libraauth). O sea que la guarda existía y el defecto que dice tapar
    # pasaba igual, con la contraseña en el nombre de la carpeta, para la
    # única URL de PostgreSQL que este producto realmente usa.
    # `es_url_postgres` es el mismo criterio en un solo lugar, y existe
    # exactamente por esto.
    if not libracore_core.es_url_postgres(str(db_path)):
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
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
