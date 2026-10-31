"""La costura con LibraView, el RIS de imágenes (ADR-051): los envíos, los estudios y los avisos ya procesados.

- `envios_a_libraview`: un envío por pedido de estudios, con su estado, el error y **el cuerpo exacto que se mandó** (el reintento
  reenvía ése, así LibraView contesta 200 idempotente y no 409).
- `estudios_en_libraview`: cada ítem del pedido y el número de acceso que le dio LibraView (el puente de la vuelta).
- `eventos_de_libraview`: los avisos del webhook ya procesados (la deduplicación por `id_evento`).

Nacen vacías y sólo se escriben si la instancia tiene `LIBRAVIEW_URL` y `LIBRAVIEW_TOKEN`.

Corre en los dos mundos, como `0025_walkin_called_at`: una instancia viva arma su esquema con `Base.metadata.create_all()` y puede tener ya las
tablas (las crea desde los modelos nuevos cuando arranca con el código nuevo antes de migrar), y una migración fallida aborta el deploy. Cada
tabla se crea sólo si falta.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_libraview"
down_revision = "0025_walkin_called_at"
branch_labels = None
depends_on = None


def _falta(tabla: str) -> bool:
    return not sa.inspect(op.get_bind()).has_table(tabla)


def upgrade():
    if _falta("envios_a_libraview"):
        op.create_table(
            "envios_a_libraview",
            sa.Column("order_id", sa.String(100), sa.ForeignKey("study_orders.id"), primary_key=True),
            sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
            sa.Column("cuerpo", sa.Text, nullable=False),
            sa.Column("orden_libraview_id", sa.Integer, nullable=True),
            sa.Column("error", sa.String(500), nullable=False, server_default=""),
            sa.Column("intentos", sa.Integer, nullable=False, server_default="0"),
            sa.Column("actualizado", sa.DateTime(timezone=True), nullable=False),
            sa.Column("enviado_por", sa.String(200), nullable=False, server_default=""),
        )
        op.create_index("ix_envios_a_libraview_estado", "envios_a_libraview", ["estado"])
    if _falta("estudios_en_libraview"):
        op.create_table(
            "estudios_en_libraview",
            sa.Column("item_id", sa.String(100), sa.ForeignKey("study_order_items.id"), primary_key=True),
            sa.Column("order_id", sa.String(100), sa.ForeignKey("study_orders.id"), nullable=False),
            sa.Column("codigo_practica", sa.String(100), nullable=False),
            sa.Column("numero_acceso", sa.String(64), nullable=True),
        )
        op.create_index("ix_estudios_en_libraview_order_id", "estudios_en_libraview", ["order_id"])
        # Único cuando no es nulo (PostgreSQL permite varios nulos en un índice único): los ítems recién preparados todavía no lo tienen.
        op.create_index(
            "ix_estudios_en_libraview_numero_acceso", "estudios_en_libraview", ["numero_acceso"], unique=True,
        )
    if _falta("eventos_de_libraview"):
        op.create_table(
            "eventos_de_libraview",
            sa.Column("id_evento", sa.String(100), primary_key=True),
            sa.Column("evento", sa.String(40), nullable=False),
            sa.Column("numero_acceso", sa.String(64), nullable=False),
            sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
            sa.Column("result_id", sa.String(100), nullable=True),
        )


def downgrade():
    # Se borran sólo si están: si nunca se usaron (o las armó otro camino) no puede fallar.
    for tabla in ("eventos_de_libraview", "estudios_en_libraview", "envios_a_libraview"):
        if not _falta(tabla):
            op.drop_table(tabla)
