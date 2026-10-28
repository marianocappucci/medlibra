"""Cuándo se llamó a cada llegada de la demanda espontánea (ADR-048).

`walkins` guardaba cuándo **llegó** cada persona (`created_at`) y nada más, así que
"cuánto esperó" el que ya pasó a atención no se podía decir: cualquier cuenta
contra "ahora" crece sola y no mide nada. `called_at` es el instante en que la
llegada pasó a `in_progress` (el profesional la hizo pasar); la espera de los ya
atendidos es `called_at - created_at`.

Nace vacía, y vacía significa «no lo sabemos»: las llegadas que ya se llamaron
antes de esta migración no tienen ese dato y la pantalla muestra «—» en vez de
inventarlo. No hay backfill posible porque el dato nunca se guardó. Una llegada
que todavía espera, o que se sacó de la fila sin llamarla, tampoco lo tiene.

Corre en los dos mundos, igual que `0020_medio_del_saldo`: una instancia viva arma
su esquema con `create_all()` y puede no tener la tabla (estampada sin ejecutar) o
tener ya la columna (armada desde el modelo nuevo); en ninguno de los dos casos
puede fallar, porque una migración fallida aborta el deploy.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_walkin_called_at"
down_revision = "0024_libraedge"
branch_labels = None
depends_on = None


def _tiene_la_columna() -> bool | None:
    """`None` si ni la tabla existe; si no, si ya tiene `called_at`."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("walkins"):
        return None
    return any(c["name"] == "called_at" for c in inspector.get_columns("walkins"))


def upgrade():
    if _tiene_la_columna() is not False:
        return
    op.add_column("walkins", sa.Column("called_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    if _tiene_la_columna() is not True:
        return
    op.drop_column("walkins", "called_at")
