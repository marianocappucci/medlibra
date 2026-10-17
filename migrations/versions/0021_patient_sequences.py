"""El contador del numero de paciente.

`POST /patients` sin `id` genera el proximo `p-NNN` (ADR-071, alta de paciente
desde Nuevo turno y Anotar llegada). El numero sale de esta tabla y no de un
`max(id) + 1`: con el maximo, borrar al ultimo paciente devuelve su numero y el
alta siguiente hereda un id que puede seguir en un turno o un mensaje viejo.

La tabla nace VACIA. La fila de la serie la crea el primer alta sin id, partiendo
del `p-NNN` mas alto que ya exista, asi que no hace falta un backfill aca (y un
backfill de SQL puro tendria que repetir la expresion regular del codigo).
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_patient_sequences"
down_revision = "0020_medio_del_saldo"
branch_labels = None
depends_on = None


def _existe_la_tabla() -> bool:
    """Los dos mundos, igual que `0019_sin_users` y `0020_medio_del_saldo`: una
    instancia viva arma su esquema con `Base.metadata.create_all()` y puede tener
    la tabla antes de que la migracion corra. Un `create_table` pelado revienta
    ahi con *relation already exists*, y una migracion fallida aborta el deploy."""
    return sa.inspect(op.get_bind()).has_table("patient_sequences")


def upgrade():
    if _existe_la_tabla():
        return
    op.create_table(
        "patient_sequences",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("last", sa.Integer, nullable=False),
    )


def downgrade():
    if not _existe_la_tabla():
        return
    op.drop_table("patient_sequences")
