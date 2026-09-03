"""La fila por orden de llegada de los bloques de demanda espontanea.

No es una tabla de turnos: un turno de LibraGenda ES un horario, y una demanda
espontanea no tiene rato sino una posicion en una fila. Ver
app/services/walkins.py.

El unico por (block_id, day, arrival_order) no es decorativo: `registrar()`
asigna el numero con un `max + 1`, que entre dos llegadas simultaneas es una
condicion de carrera. Sin la restriccion, dos pacientes quedan en la misma
posicion y la fila se ve perfectamente bien.
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_walkins"
down_revision = "0015_consultorios_y_bloques"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "walkins",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column(
            "block_id", sa.String(100), sa.ForeignKey("agenda_blocks.id"), nullable=False,
        ),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("client_id", sa.String(100), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("service_id", sa.String(100), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("arrival_order", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Declarado en el create_table y no como un ALTER posterior: SQLite no
        # puede sumarle una restriccion a una tabla viva.
        sa.UniqueConstraint("block_id", "day", "arrival_order", name="uq_walkins_orden"),
    )
    op.create_index("ix_walkins_block_id", "walkins", ["block_id"])
    op.create_index("ix_walkins_day", "walkins", ["day"])
    op.create_index("ix_walkins_client_id", "walkins", ["client_id"])


def downgrade():
    op.drop_index("ix_walkins_client_id", table_name="walkins")
    op.drop_index("ix_walkins_day", table_name="walkins")
    op.drop_index("ix_walkins_block_id", table_name="walkins")
    op.drop_table("walkins")
