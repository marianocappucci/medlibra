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
    # ⚠️ **Tiene que decir lo mismo que `scripts/panel_admin.py`.** Hasta el
    # 2026-08-24 este archivo no pasaba `backup_zip` y el otro sí. Como pisan un
    # `_cfg` GLOBAL y `libracore.admin.services` importa los dos módulos en el
    # mismo proceso, una diferencia acá hace que el resultado dependa del orden
    # de los imports. `tests/test_provisioning.py` lo compara entero con
    # `asdict`.
    #
    # **No estaba mordiendo**: todo camino que hoy lee `cfg.backup_zip` entra por
    # `panel_admin.py`, que ya lo tenía en `True`. Se ve en el servidor — las
    # instancias vienen armando su ZIP diario en `data/backups/`. Era una mina,
    # no un incendio.
    #
    # `True` es el valor correcto y no un empate arbitrario: este producto sirve
    # su pantalla de Backups con el `build_backup_router` de `libracore.respaldo`,
    # así que el ZIP del cron es exactamente el que el cliente puede listar,
    # bajar y restaurar solo. Sin el flag, el `tar.gz` empaqueta `data/` mientras
    # el dump de PostgreSQL queda **afuera**.
    backup_zip=True,
    base_core_separada=True,
    product_name="MEDLIBRA",
    image_name="medlibra:latest",
    container_prefix="medlibra",
    db_filename="medlibra.db",
    # Las dos cadenas de Alembic de este producto, corridas por
    # `panel_admin.py actualizar` antes de mover la instancia a la imagen nueva,
    # y por el alta antes del primer arranque. Requiere libracore >= v1.51.0
    # (que es la que acepta una SECUENCIA de comandos) y libragenda >= v0.9.1
    # (que es la que trae `libragenda-migrar` como comando instalable).
    #
    # 🔴 **`v0.9.1` y no `v0.10.0`, a proposito.** Entre esos dos tags del motor
    # entraron recursos secundarios, historial de estados y **reserva atomica**
    # (ADR-009 a ADR-013), y ese ultimo le cambia la interfaz al repositorio de
    # turnos: `_TurnosEnHoraLocal` no implementa `reserve()`, asi que subir a
    # `v0.10.0` rompe mas de 20 tests de agenda de este producto. Lo verifico el
    # CI el 2026-08-24, no una lectura del changelog. Ese salto es un trabajo
    # aparte; la `v0.9.1` es un backport que trae SOLO el empaquetado de las
    # migraciones, con `application.py` identico a la `v0.9.0`.
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
