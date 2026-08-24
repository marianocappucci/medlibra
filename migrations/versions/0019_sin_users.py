"""Retira la tabla `users` del dominio: es un vestigio del auth propio.

🔴 **El auth se mudo a libraauth el 2026-07-30 y esta tabla quedo huerfana.**
`0001_users` la crea en la base del DOMINIO, pero desde aquella migracion los
usuarios viven en `usuarios`, la tabla de `libraauth.models`, contra el
`auth_engine` --- que en este producto apunta a la base de LibraCore, no a esta.

Nadie la consulta: `app/services/users.py` es un shim sobre
`libraauth.repository.UserRepository`, que se construye con el `session_factory`
del auth. Un grep por `users` en `app/` y `tests/` no devuelve ni un modelo, ni
un `Table("users")`, ni SQL crudo contra ella.

## Por que hacia falta sacarla, y no solo ignorarla

Las instancias vivas **no tienen** esta tabla: su esquema lo creo
`Base.metadata.create_all()` desde los modelos, y `users` no es un modelo de
este producto. Medido el 2026-08-24 contra la demo: su esquema coincide exacto
con las migraciones hasta `0012_service_iva_rates` **salvo esta tabla**. La
cadena y la realidad decian cosas distintas, y eso bloqueaba estampar las
instancias para poder meter las migraciones en el deploy.

## Por que `IF EXISTS`

🔑 **Esta migracion corre contra dos mundos distintos.** Sobre una base armada
desde cero por las migraciones, `users` existe (la crea `0001`) y se borra.
Sobre una instancia viva estampada en su revision real, **no existe** --- y un
`op.drop_table()` pelado la haria fallar, abortando el deploy con el paso nuevo
de `cmd_actualizar`. El indice se borra con la tabla, asi que no hace falta
tocarlo aparte.

Revision ID: 0019_sin_users
Revises: 0018_envios_a_contalibra
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_sin_users"
down_revision = "0018_envios_a_contalibra"
branch_labels = None
depends_on = None


def upgrade():
    # `IF EXISTS` y no `op.drop_table`: ver el docstring. Los dos mundos.
    op.execute("DROP TABLE IF EXISTS users")


def downgrade():
    # Se recrea igual que en `0001_users`, para que la cadena siga siendo
    # reversible. Queda vacia: no hay de donde recuperar filas que este
    # producto dejo de escribir hace un mes.
    op.create_table(
        "users",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
