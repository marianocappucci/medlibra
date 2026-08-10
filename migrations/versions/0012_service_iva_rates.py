"""Alicuota de IVA configurable: tabla por servicio + default de la instancia.

Antes de esto la facturacion asumia 21% fijo (`billing._split_iva`), que en
un producto de salud es el caso equivocado: la mayoria de las prestaciones
medicas estan exentas. Ver `app/services/iva_rates.py` para por que la lista
de alicuotas es cerrada.

El default arranca en 21% -- el valor que ya estaba hardcodeado -- para que
la migracion no le cambie la facturacion a ninguna instancia existente. Un
consultorio con prestaciones exentas lo baja a 0 una sola vez.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_service_iva_rates"
down_revision = "0011_modulos"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_iva_rates",
        sa.Column("service_id", sa.String(100), sa.ForeignKey("services.id"), primary_key=True),
        sa.Column("rate", sa.Numeric(6, 4), nullable=False),
    )
    op.add_column(
        "business_settings",
        sa.Column(
            "default_iva_rate", sa.Numeric(6, 4),
            nullable=False, server_default="0.21",
        ),
    )


def downgrade():
    op.drop_column("business_settings", "default_iva_rate")
    op.drop_table("service_iva_rates")
