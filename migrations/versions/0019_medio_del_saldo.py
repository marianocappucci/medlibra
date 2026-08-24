"""Con que se cobro el saldo de la consulta.

Es el unico dato del cobro que NO se puede recalcular desde el turno. La sena
queda en `deposits` con su medio; el medio del saldo llega en el pedido de
completar y hasta ahora no se guardaba en ningun lado.

Sin esto, el reintento de `/facturacion-externa/{id}/reintentar` tenia que
asumir "efectivo" -- y eso reintroduce EN EL REINTENTO el mismo defecto que se
esta arreglando: un saldo cobrado por transferencia entraba a la caja de
Contalibra como efectivo, y el cierre no cuadra contra el arqueo.

Nace vacia, y vacia significa "no lo sabemos": las filas anteriores a esta
migracion siguen reintentandose con "efectivo", que es lo que ya venian
mandando. No hay backfill posible porque el dato nunca existio.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_medio_del_saldo"
down_revision = "0018_envios_a_contalibra"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "envios_a_contalibra",
        # `server_default=""` y no NULL: el codigo hace
        # `envio.get("medio_del_saldo") or "efectivo"`, asi que los dos
        # funcionarian -- pero con NOT NULL la columna no admite el caso
        # ambiguo de "se guardo vacio" contra "nunca se guardo", que aca da lo
        # mismo y no vale la pena distinguir.
        sa.Column("medio_del_saldo", sa.String(40), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("envios_a_contalibra", "medio_del_saldo")
