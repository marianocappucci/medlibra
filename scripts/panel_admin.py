#!/usr/bin/env python3
"""
Panel de administración MedLibra.
Gestiona todos los contenedores de clientes desde un menú interactivo.
Uso: python3 scripts/panel_admin.py [comando] [slug]
     python3 scripts/panel_admin.py           → menú interactivo
     python3 scripts/panel_admin.py listar
     python3 scripts/panel_admin.py backup miconsultorio

Wrapper de configuración sobre libracore.provisioning.panel_admin (lógica
compartida con Contalibra/Restolibra/Gestiolibra — ver wiki/entities/libracore.md).
Solo fija las constantes propias de MedLibra; la lógica real vive en
LibraCore.
"""
from pathlib import Path

from libracore.provisioning import (
    client_from_config,
    configure,
    forward_host_from_config,
    le_email_from_config,
    npm_available,
)
from libracore.provisioning.panel_admin import (
    _set_servicio_estado,
    cli,
    cmd_activar,
    cmd_actualizar,
    cmd_backup,
    cmd_backup_all,
    cmd_eliminar,
    cmd_estado_servicio,
    cmd_info,
    cmd_list_backups,
    cmd_listar,
    cmd_logs,
    cmd_npm_crear,
    cmd_npm_eliminar,
    cmd_npm_listar,
    cmd_pausar,
    cmd_restart,
    cmd_restore_db,
    cmd_start,
    cmd_stop,
    cmd_suspender,
    compose,
    container_status,
    find_client,
    interactive,
    load_clients,
    pick_client,
)

REPO_ROOT = Path(__file__).parent.parent.resolve()

configure(
    # El backup del cron arma el MISMO ZIP que la pantalla de Backups, en
    # `data/backups/`, en vez de un `tar.gz` aparte que la pantalla no lista
    # y el cliente no puede restaurar. Requiere libracore >= v1.29.0.
    #
    # Este producto puede prenderlo porque su pantalla sale de
    # `libracore.respaldo` (`build_backup_router` en app/main.py). Contalibra
    # y Restolibra tienen implementacion propia y todavia no.
    backup_zip=True,
    postgres=True,
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
    # 🔴 **TRES cadenas, y el orden no es decorativo.**
    #
    # 1. `libragenda-migrar` — va primero porque las revisiones propias de este
    #    producto tienen FK contra tablas de LibraGenda.
    # 2. `libracore-migrar` — el esquema de LibraCore vive en `medlibra_core`,
    #    una base **aparte**: el comando la resuelve por `MEDLIBRA_LIBRACORE_DB_PATH` y **no**
    #    por `DATABASE_URL`, que apunta al dominio. Ver
    #    `libracore.migrar.url_de_core`.
    # 3. `alembic` — la cadena propia.
    #
    # La del motor no la corría nadie hasta el 2026-08-25: sus migraciones no
    # viajaban en el wheel. Medido, `medlibra_core` de la demo no tiene
    # `alembic_version` ninguna y le faltan las cuatro columnas que la revisión
    # `0002` le agrega a `clients`.
    migraciones=(
        ("libragenda-migrar", "upgrade"),
        ("libracore-migrar", "upgrade", "--prefijo", "medlibra"),
        ("alembic", "upgrade", "head"),
    ),
    repo_root=REPO_ROOT,
    base_port=8078,
)

# Re-exportados por compatibilidad con cualquier uso directo de este módulo.
CLIENTES_DIR = REPO_ROOT / "clientes"
_NPM_AVAILABLE = npm_available()

if __name__ == "__main__":
    cli()
