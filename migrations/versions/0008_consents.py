"""Create MedLibra's own consents table: consentimientos informados por
paciente (procedimiento, quien autoriza, texto libre). Append-only, mismo
criterio que clinical_notes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_consents"
down_revision = "0007_clinical_documents"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "consents",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(100), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("procedure", sa.String(300), nullable=False),
        sa.Column("granted_by", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_consents_patient_id", "consents", ["patient_id"])

def downgrade():
    op.drop_index("ix_consents_patient_id", table_name="consents")
    op.drop_table("consents")
