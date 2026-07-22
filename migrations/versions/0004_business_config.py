"""Configuracion comercial del consultorio: horario por sucursal, precio
por servicio y sucursal, contacto de sucursal, y datos del negocio
(nombre/moneda). Mismo feature ya aplicado en Gestiolibra.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_business_config"
down_revision = "0003_clinical_notes"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "branch_contacts",
        sa.Column("branch_id", sa.String(100), sa.ForeignKey("branches.id"), primary_key=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.String(300), nullable=True),
    )

    op.create_table(
        "branch_hours",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("branch_id", sa.String(100), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("weekday", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.Time, nullable=False),
        sa.Column("ends_at", sa.Time, nullable=False),
    )
    op.create_index("ix_branch_hours_branch_id", "branch_hours", ["branch_id"])

    op.create_table(
        "service_prices",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("service_id", sa.String(100), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("branch_id", sa.String(100), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index("ix_service_prices_service_id", "service_prices", ["service_id"])
    op.create_index("ix_service_prices_branch_id", "service_prices", ["branch_id"])
    op.create_unique_constraint(
        "uq_service_prices_service_branch", "service_prices", ["service_id", "branch_id"],
    )

    op.create_table(
        "business_settings",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("business_name", sa.String(200), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ARS"),
    )

def downgrade():
    op.drop_table("business_settings")
    op.drop_constraint("uq_service_prices_service_branch", "service_prices", type_="unique")
    op.drop_index("ix_service_prices_branch_id", table_name="service_prices")
    op.drop_index("ix_service_prices_service_id", table_name="service_prices")
    op.drop_table("service_prices")
    op.drop_index("ix_branch_hours_branch_id", table_name="branch_hours")
    op.drop_table("branch_hours")
    op.drop_table("branch_contacts")
