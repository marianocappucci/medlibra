"""Add cuit and condicion_iva to patients (facturacion con LibraCore)."""
import sqlalchemy as sa
from alembic import op

revision = "0009_patient_billing_fields"
down_revision = "0008_consents"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("patients", sa.Column("cuit", sa.String(20), nullable=True))
    op.add_column("patients", sa.Column("condicion_iva", sa.String(50), nullable=True))

def downgrade():
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_column("condicion_iva")
        batch_op.drop_column("cuit")
