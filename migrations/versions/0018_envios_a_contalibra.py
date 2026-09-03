"""Que consultas se mandaron a Contalibra, y cuales no pudieron.

Completar un turno no se rompe porque Contalibra no conteste -- la atencion ya
ocurrio -- pero sin esta tabla el resultado seria una consulta que no se
facturo y de la que nadie se entera. Es la peor de las dos mitades: la plata se
pierde en silencio.

La tabla nace vacia y solo se usa si la instancia tiene CONTALIBRA_URL
configurada. Sin ella, MedLibra factura por su cuenta como hasta ahora y aca no
se escribe nada.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_envios_a_contalibra"
down_revision = "0017_honorarios_por_profesional"
branch_labels = None
depends_on = None


def upgrade():
    # Sin FK a `appointments`: el turno lo maneja LibraGenda, que no conoce esta
    # tabla y por lo tanto no la limpiaria en un borrado. Mismo criterio que
    # `appointment_rooms` en 0015.
    op.create_table(
        "envios_a_contalibra",
        sa.Column("appointment_id", sa.String(100), primary_key=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("venta_id", sa.Integer, nullable=True),
        sa.Column("error", sa.String(500), nullable=False, server_default=""),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actualizado", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_envios_a_contalibra_estado", "envios_a_contalibra", ["estado"])


def downgrade():
    op.drop_index("ix_envios_a_contalibra_estado", table_name="envios_a_contalibra")
    op.drop_table("envios_a_contalibra")
