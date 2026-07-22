"""Create MedLibra's own prescriptions/prescription_items tables: recetas
medicas por paciente, con uno o mas items (medicamento, dosis,
indicaciones). Append-only, mismo criterio que clinical_notes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_prescriptions"
down_revision = "0004_business_config"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "prescriptions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(100), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
    )
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])
    op.create_table(
        "prescription_items",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("prescription_id", sa.String(100), sa.ForeignKey("prescriptions.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("medication", sa.String(200), nullable=False),
        sa.Column("dosage", sa.String(200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
    )
    op.create_index("ix_prescription_items_prescription_id", "prescription_items", ["prescription_id"])

def downgrade():
    op.drop_index("ix_prescription_items_prescription_id", table_name="prescription_items")
    op.drop_table("prescription_items")
    op.drop_index("ix_prescriptions_patient_id", table_name="prescriptions")
    op.drop_table("prescriptions")
