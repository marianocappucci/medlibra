"""Create MedLibra's own clinical_documents table: archivos adjuntos por
paciente (informes externos, estudios escaneados). Solo metadata en la
base -- el archivo en si vive en filesystem bajo MEDLIBRA_DOCUMENTS_DIR.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_clinical_documents"
down_revision = "0006_study_orders"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "clinical_documents",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(100), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("stored_filename", sa.String(300), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
    )
    op.create_index("ix_clinical_documents_patient_id", "clinical_documents", ["patient_id"])

def downgrade():
    op.drop_index("ix_clinical_documents_patient_id", table_name="clinical_documents")
    op.drop_table("clinical_documents")
