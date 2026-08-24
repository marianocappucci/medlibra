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

# 🔴 Va detras de `0019_sin_users`, que entro en `develop` en paralelo mientras
# esta rama estaba abierta. Las dos colgaban de `0018` y Alembic quedaba con DOS
# CABEZAS: `upgrade head` falla con "Multiple head revisions are present".
#
# No lo vio la suite local --este worktree tenia una sola de las dos-- sino el
# CI, que corre sobre el MERGE con `develop`. Es la unica forma de verlo.
revision = "0020_medio_del_saldo"
down_revision = "0019_sin_users"
branch_labels = None
depends_on = None


def _existe_la_tabla() -> bool:
    """🔴 **Los dos mundos, igual que `0019_sin_users`.**

    Una instancia viva puede estar **estampada en `0018` sin tener la tabla**:
    el esquema de las instancias lo arma `Base.metadata.create_all()` desde los
    modelos, no las migraciones, y `alembic stamp` no ejecuta nada. Un
    `add_column` pelado revienta ahi con *relation "envios_a_contalibra" does
    not exist*, y desde LibraCore v1.48.0 **una migracion fallida aborta el
    deploy**: el arreglo convertiria un deploy que funciona en uno que no.

    No es hipotetico. Lo puso en rojo `tests/test_migracion_sin_users.py`, que
    la sesion paralela escribio para exactamente este escenario -- y lo puso en
    rojo **contra PostgreSQL**, no en SQLite.
    """
    bind = op.get_bind()
    return sa.inspect(bind).has_table("envios_a_contalibra")


def upgrade():
    if not _existe_la_tabla():
        return
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
    if not _existe_la_tabla():
        return
    op.drop_column("envios_a_contalibra", "medio_del_saldo")
