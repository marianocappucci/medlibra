"""Create actividad_log: quien creo, edito o borro que, y que cambio.

La escribe el `flush` de SQLAlchemy via `libraauth.auditoria` (v0.11.0), no los
repositorios -- ver `app/auditoria.py`.

**Va en la base del DOMINIO** (la de LibraGenda), no en la de LibraCore donde
vive `usuarios`: es donde ocurren las escrituras que audita y donde vive la
transaccion en la que se escribe la fila.

> 🔴 **En este producto el log NO guarda contenido clinico.** La fila dice que
> alguien creo, edito o borro una nota, una receta o una ficha, con quien y
> cuando; el texto de la nota, la medicacion de la receta y los datos
> identificatorios del paciente quedan afuera del diff **y** de la
> descripcion. Ver `app/auditoria.py` para las dos defensas y por que hacen
> falta las dos.

**Tabla nueva y nada mas**: no toca ninguna existente, no migra datos y no tiene
backfill posible. Lo que paso antes no quedo registrado en ningun lado, asi que
el log arranca vacio y desde hoy.

`auth_log` (accesos) NO esta aca: vive en la base de LibraCore y ya la crea su
schema. Lo unico que cambia es que ahora alguien la escribe.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_actividad_log"
down_revision = "0012_service_iva_rates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "actividad_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("usuario", sa.String(100), nullable=False),
        sa.Column("accion", sa.String(20), nullable=False),
        sa.Column("entidad", sa.String(50), nullable=False),
        sa.Column("entidad_id", sa.Integer()),
        sa.Column("descripcion", sa.String(500), nullable=False),
        sa.Column("cambios", sa.Text()),
    )
    op.create_index("ix_actividad_log_ts", "actividad_log", ["ts"])
    op.create_index("ix_actividad_log_accion", "actividad_log", ["accion"])
    op.create_index("ix_actividad_log_entidad", "actividad_log", ["entidad"])


def downgrade():
    op.drop_index("ix_actividad_log_entidad", table_name="actividad_log")
    op.drop_index("ix_actividad_log_accion", table_name="actividad_log")
    op.drop_index("ix_actividad_log_ts", table_name="actividad_log")
    op.drop_table("actividad_log")
