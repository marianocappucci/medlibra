"""Create MedLibra's own study_orders/study_order_items/study_results
tables: pedidos de estudios/analisis por paciente, con uno o mas items
(tipo de estudio, motivo) y uno o mas resultados por item (llegan por
separado, en momentos distintos). Append-only, mismo criterio que
prescriptions/clinical_notes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_study_orders"
down_revision = "0005_prescriptions"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "study_orders",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(100), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
    )
    op.create_index("ix_study_orders_patient_id", "study_orders", ["patient_id"])
    op.create_table(
        "study_order_items",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("order_id", sa.String(100), sa.ForeignKey("study_orders.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("study_type", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_study_order_items_order_id", "study_order_items", ["order_id"])
    op.create_table(
        "study_results",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("item_id", sa.String(100), sa.ForeignKey("study_order_items.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_study_results_item_id", "study_results", ["item_id"])

def downgrade():
    op.drop_index("ix_study_results_item_id", table_name="study_results")
    op.drop_table("study_results")
    op.drop_index("ix_study_order_items_order_id", table_name="study_order_items")
    op.drop_table("study_order_items")
    op.drop_index("ix_study_orders_patient_id", table_name="study_orders")
    op.drop_table("study_orders")
