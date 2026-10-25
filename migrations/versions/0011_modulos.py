"""Create modulos: gating de recordatorios/senas/facturacion/dashboard por plan.

Mismo patron que `modulos` de Gestiolibra/Contalibra/Restolibra, pero
propio de MedLibra -- no vive en LibraCore porque el catalogo de modulos
gateables es especifico de cada producto (ver plans.py). A diferencia de
Gestiolibra, el dominio clinico (pacientes, historia clinica, recetas,
estudios, documentos, consentimientos) nunca pasa por esta tabla -- solo
lo comercial (recordatorios/senas/facturacion/dashboard) es gateable.

2026-10-25 (ADR-043): la tabla se crea como `medlibra_modulos`, no `modulos`. LibraCore
tiene una `modulos` propia (otra forma) y en una base nueva y unica la cadena del motor
corre antes que esta: un `create_table("modulos")` moriria con «already exists». Las
bases que ya pasaron por esta revision la tienen como `modulos`; las renombra `0023`.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_modulos"
down_revision = "0010_patient_created_at"
branch_labels = None
depends_on = None

def upgrade():
    # Idempotente: una instancia armada por `create_all()` y despues estampada ya puede tenerla.
    if "medlibra_modulos" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "medlibra_modulos",
        sa.Column("modulo", sa.String(50), primary_key=True),
        sa.Column("habilitado", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("plan", sa.String(20), nullable=False, server_default="premium"),
    )

def downgrade():
    # Con el nombre nuevo, o con el viejo si `0023` ya se bajo y la dejo como `modulos`. Con el viejo
    # sólo si es la de MedLibra (sin `id`): una `modulos` con `id` es la de LibraCore y no es nuestra.
    insp = sa.inspect(op.get_bind())
    tablas = insp.get_table_names()
    if "medlibra_modulos" in tablas:
        op.drop_table("medlibra_modulos")
    elif "modulos" in tablas and "id" not in {c["name"] for c in insp.get_columns("modulos")}:
        op.drop_table("modulos")
