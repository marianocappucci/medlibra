#!/usr/bin/env python3
"""
Onboarding de nuevo cliente MedLibra.
Uso: python3 scripts/nuevo_cliente.py

Wrapper de configuración sobre libracore.provisioning.nuevo_cliente (lógica
compartida con Contalibra/Restolibra/Gestiolibra — ver wiki/entities/libracore.md).
Solo fija las constantes propias de MedLibra; la lógica real vive en
LibraCore.
"""
from pathlib import Path

from libracore.provisioning import configure
from libracore.provisioning.nuevo_cliente import (
    ClienteError, ask, build_image, crear_cliente, image_exists, main,
    network_exists, next_port, slugify, used_ports,
)

REPO_ROOT = Path(__file__).parent.parent.resolve()

configure(
    postgres=True,
    base_core_separada=True,
    product_name="MEDLIBRA",
    image_name="medlibra:latest",
    container_prefix="medlibra",
    db_filename="medlibra.db",
    # Las dos cadenas de Alembic de este producto, corridas por
    # `panel_admin.py actualizar` antes de mover la instancia a la imagen nueva,
    # y por el alta antes del primer arranque. Requiere libracore >= v1.51.0
    # (que es la que acepta una SECUENCIA de comandos) y libragenda >= v0.10.0
    # (que es la que trae `libragenda-migrar` como comando instalable).
    #
    # 🔑 **El orden no es estetico.** Las revisiones de este producto tienen FK
    # contra tablas de LibraGenda (`branches`), asi que la cadena del motor va
    # primero. Al reves, la primera revision que las toque muere con
    # `relation "branches" does not exist`.
    #
    # Son dos tablas de version distintas en la misma base: `alembic_version`
    # para LibraGenda y `alembic_version_medlibra` para esta cadena.
    migraciones=(
        ("libragenda-migrar", "upgrade"),
        ("alembic", "upgrade", "head"),
    ),
    repo_root=REPO_ROOT,
    base_port=8078,
)

# Re-exportados por compatibilidad con cualquier uso directo de este módulo.
CLIENTES_DIR = REPO_ROOT / "clientes"

if __name__ == "__main__":
    main()
