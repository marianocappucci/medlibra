"""Create MedLibra's own patients table: clinical extension (dni,
birth_date) of LibraGenda's generic Client, sharing its id via FK.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_patients"
down_revision = "0001_users"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "patients",
        sa.Column("id", sa.String(100), sa.ForeignKey("clients.id"), primary_key=True),
        sa.Column("dni", sa.String(20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
    )

def downgrade():
    op.drop_table("patients")
