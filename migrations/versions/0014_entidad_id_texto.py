"""actividad_log.entidad_id pasa de INTEGER a texto.

🔴 **El tipo declarado nunca describio lo que hay adentro.** La columna se llena
con el id de la entidad auditada, y los ids de este producto son cadenas
(`patient-1`). SQLite lo aceptaba por tipado dinamico -- guarda texto en una
columna INTEGER sin decir nada --, asi que el defecto era invisible: medido en
la demo el 2026-08-09, de 95 filas habia **58 de texto** contra 30 enteras.

Contra PostgreSQL no hay tipado dinamico: el INSERT muere con
`invalid input syntax for type integer: "patient-1"`. Y como el log se escribe
en la MISMA transaccion que la operacion auditada, no se pierde una fila de
auditoria -- **el alta entera devuelve 500**. O sea que sin esta migracion el
producto no puede escribir nada una vez migrado a PostgreSQL.

El modelo esta en `libraauth.auditoria` (compartido por los seis productos);
aca va solo la migracion de la tabla de este.

**Los datos no se pierden ni cambian de significado.** Los valores que ya eran
texto quedan igual; los enteros pasan a su representacion decimal (`36` ->
`"36"`), que es como se muestran en la pantalla de logs de todos modos: la
columna se usa en un solo lugar, serializada, sin filtros ni joins ni orden.

**Los dos motores no se tocan igual**, y por eso va con `batch_alter_table`:
PostgreSQL necesita un `USING` para castear, y SQLite **no soporta**
`ALTER COLUMN ... TYPE` -- ahi Alembic reconstruye la tabla y copia las filas.

> La reconstruccion de SQLite es segura en este caso concreto porque
> `actividad_log` **no es tabla padre de ninguna otra**: ninguna declara una FK
> hacia ella. Vale la aclaracion porque en esta familia ya hubo un incidente por
> lo contrario -- reconstruir una tabla referenciada deja a las hijas apuntando
> a un nombre `_old` que despues se borra.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_entidad_id_texto"
down_revision = "0013_actividad_log"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("actividad_log") as batch:
        batch.alter_column(
            "entidad_id",
            existing_type=sa.Integer(),
            type_=sa.String(100),
            existing_nullable=True,
            postgresql_using="entidad_id::varchar",
        )


def downgrade():
    """Vuelve a INTEGER, y **puede perder datos**: cualquier `entidad_id` que no
    sea un numero no entra. Es inherente al tipo viejo, no un descuido de esta
    migracion -- es exactamente el motivo por el que se cambio.

    El `USING` deja en NULL lo que no sea numerico, en vez de hacer fallar el
    downgrade entero: un rollback que aborta a la mitad es peor que uno que
    pierde un dato que el tipo viejo no podia representar igual.

    > La primera version de esto usaba `nullif(entidad_id, '')::integer`, que
    > solo cubre la cadena vacia, y el downgrade moria con
    > `invalid input syntax for type integer: "patient-1"` -- o sea que el
    > comentario prometia algo que el codigo no hacia. Lo encontro probar el
    > downgrade de verdad contra PostgreSQL con datos mezclados, no leerlo.
    """
    with op.batch_alter_table("actividad_log") as batch:
        batch.alter_column(
            "entidad_id",
            existing_type=sa.String(100),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using=(
                "case when entidad_id ~ '^-?[0-9]+$' "
                "then entidad_id::integer end"
            ),
        )
