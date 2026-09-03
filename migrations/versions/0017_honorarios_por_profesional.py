"""Honorarios: el precio de una prestacion con un profesional concreto.

`service_prices` modela (prestacion x sede) y no puede decir que la consulta
con la Dra. Vidal salga mas cara que con el Dr. Molina en la MISMA sede, que es
justo lo que distingue a un honorario de un precio de lista.

La tabla nace vacia: sin honorario propio, el turno se sigue cobrando al precio
de la sede exactamente como hasta ahora. Un `upgrade` sobre una base con datos
no le cambia la facturacion a ninguna instancia.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_honorarios_por_profesional"
down_revision = "0016_walkins"
branch_labels = None
depends_on = None


def upgrade():
    # El unico se declara dentro del create_table y no como un ALTER posterior:
    # SQLite no puede sumarle una restriccion a una tabla viva.
    op.create_table(
        "resource_service_prices",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("service_id", sa.String(100), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("resource_id", sa.String(100), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint(
            "service_id", "resource_id", name="uq_resource_service_prices",
        ),
    )
    op.create_index(
        "ix_resource_service_prices_service_id", "resource_service_prices", ["service_id"],
    )
    op.create_index(
        "ix_resource_service_prices_resource_id", "resource_service_prices", ["resource_id"],
    )


def downgrade():
    op.drop_index(
        "ix_resource_service_prices_resource_id", table_name="resource_service_prices",
    )
    op.drop_index(
        "ix_resource_service_prices_service_id", table_name="resource_service_prices",
    )
    op.drop_table("resource_service_prices")
