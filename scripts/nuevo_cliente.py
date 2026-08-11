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
    repo_root=REPO_ROOT,
    base_port=8078,
)

# Re-exportados por compatibilidad con cualquier uso directo de este módulo.
CLIENTES_DIR = REPO_ROOT / "clientes"

if __name__ == "__main__":
    main()
