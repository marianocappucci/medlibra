"""Add nullable created_at to patients (dashboard: pacientes nuevos en un rango)."""
from alembic import op
import sqlalchemy as sa

revision = "0010_patient_created_at"
down_revision = "0009_patient_billing_fields"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("patients", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_column("created_at")
