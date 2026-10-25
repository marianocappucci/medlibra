"""`modulos` pasa a `medlibra_modulos`: LibraCore tiene una tabla con ese nombre (ADR-043).

## Por qué

Con una sola base por producto (decision del humano, 2026-10-22), el dominio y LibraCore
comparten base, y las dos declaran una tabla `modulos` con formas distintas:

| | MedLibra (esta) | LibraCore |
|---|---|---|
| clave | `modulo` (texto, 50) | `id` serial; `modulo` unico |
| `habilitado` | `BOOLEAN` | `INTEGER` |
| `plan` | texto (20), default `premium` | texto, default `estandar` |

`libracore-unir-bases` corta con `choque_de_tablas` ante cualquier nombre repetido entre las
dos bases (ADR-078, punto 3), y en una base nueva y unica el segundo `CREATE TABLE` no se
puede. El producto renombra la suya *antes* de unir; el paso a la de LibraCore es aparte.

## Qué hace

1. Renombra `modulos` a `medlibra_modulos` y su clave primaria a `medlibra_modulos_pkey` (un
   `RENAME` de tabla no mueve el nombre de la clave, y el indice de `modulos_pkey` es un
   nombre de toda la base: se lo quedaria la de LibraCore).
2. **Sólo si `modulos` es la de MedLibra** (no tiene `id`). Si es la de LibraCore, o no existe
   (una base nueva: `0011` ya creo `medlibra_modulos`), no hace nada.
3. Si el arranque nuevo corrio antes de migrar, `create_all()` ya dejo una `medlibra_modulos`
   (con el sembrado de `ensure_seeded()`, todo habilitado): se pasan las filas de `modulos`,
   que son lo que alguien configuro, **ganando sobre el sembrado**, y se borra la vieja.

Sin perdida de filas: es un `RENAME`, o un traspaso con el conteo verificado.

## Downgrade

Devuelve el nombre (`modulos`, `modulos_pkey`) **si no hay ya una `modulos`**: en una base
unida esa es la de LibraCore y no se toca.

Revision ID: 0023_medlibra_modulos
Revises: 0022_consultorio_recurso
Create Date: 2026-10-25
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "0023_medlibra_modulos"
down_revision = "0022_consultorio_recurso"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")


def _es_la_de_medlibra(insp: sa.Inspector, tabla: str) -> bool:
    """La `modulos` de MedLibra no tiene `id`; la de LibraCore sí."""
    return tabla in insp.get_table_names() and "id" not in {c["name"] for c in insp.get_columns(tabla)}


def _renombrar_clave(insp: sa.Inspector, tabla: str, de: str, a: str) -> None:
    if insp.get_pk_constraint(tabla).get("name") == de:
        op.execute(f'ALTER TABLE "{tabla}" RENAME CONSTRAINT "{de}" TO "{a}"')


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not _es_la_de_medlibra(insp, "modulos"):
        log.info("0023: no hay una `modulos` de MedLibra que renombrar; no se toca nada.")
        return
    if "medlibra_modulos" not in insp.get_table_names():
        op.rename_table("modulos", "medlibra_modulos")
        _renombrar_clave(insp, "medlibra_modulos", "modulos_pkey", "medlibra_modulos_pkey")
        return
    # Las dos existen: el arranque nuevo corrio antes de migrar. La vieja manda.
    conn = op.get_bind()
    viejas = conn.execute(sa.text("SELECT count(*) FROM modulos")).scalar_one()
    log.warning("0023: `medlibra_modulos` ya existia; se pasan %s filas de `modulos` por encima del sembrado.", viejas)
    op.execute(
        "INSERT INTO medlibra_modulos (modulo, habilitado, plan) "
        "SELECT modulo, CAST(habilitado AS boolean), plan FROM modulos "
        "ON CONFLICT (modulo) DO UPDATE SET habilitado = EXCLUDED.habilitado, plan = EXCLUDED.plan"
    )
    # Verificado antes de borrar: cada modulo de la vieja tiene que estar en la nueva.
    faltan = conn.execute(sa.text(
        "SELECT count(*) FROM modulos v WHERE NOT EXISTS (SELECT 1 FROM medlibra_modulos n WHERE n.modulo = v.modulo)"
    )).scalar_one()
    if faltan:
        raise RuntimeError(f"0023: faltan {faltan} modulos en `medlibra_modulos` tras copiarlos; no se borra `modulos`.")
    op.drop_table("modulos")


def downgrade():
    insp = sa.inspect(op.get_bind())
    tablas = insp.get_table_names()
    if "medlibra_modulos" not in tablas:
        return
    if "modulos" in tablas:
        log.warning("0023 (downgrade): ya hay una `modulos` (la de LibraCore, en una base unida); `medlibra_modulos` queda como está.")
        return
    op.rename_table("medlibra_modulos", "modulos")
    _renombrar_clave(insp, "modulos", "medlibra_modulos_pkey", "modulos_pkey")
