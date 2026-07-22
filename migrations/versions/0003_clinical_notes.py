"""Create MedLibra's own clinical_notes table: append-only historia
clinica basica (free-text evolution notes per patient).
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_clinical_notes"
down_revision = "0002_patients"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "clinical_notes",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(100), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_clinical_notes_patient_id", "clinical_notes", ["patient_id"])

def downgrade():
    op.drop_index("ix_clinical_notes_patient_id", table_name="clinical_notes")
    op.drop_table("clinical_notes")
