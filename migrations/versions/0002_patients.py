"""Create MedLibra's own patients table: clinical extension (dni,
birth_date) of LibraGenda's generic Client, sharing its id via FK.

2026-10-25 (ADR-043): la clave foranea apunta a `agenda_clients`, que es como llama
libragenda v0.14.0 a la tabla `clients` (la de LibraCore es otra). En una base que ya
corrio esta revision no cambia nada: el renombre de libragenda mueve la clave solo.
En una base nueva la cadena de libragenda corre antes y ya dejo `agenda_clients`.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_patients"
down_revision = "0001_users"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "patients",
        sa.Column("id", sa.String(100), sa.ForeignKey("agenda_clients.id"), primary_key=True),
        sa.Column("dni", sa.String(20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
    )

def downgrade():
    op.drop_table("patients")
