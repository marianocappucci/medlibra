"""Consultorios, bloques de agenda y la sala de cada turno.

El consultorio pasa a ser una entidad: hasta ahora lo unico que se podia ocupar
era el profesional (el `Resource` de LibraGenda) y la pregunta "estos dos no
estan los dos en el Consultorio 2 a las 10?" no se podia ni formular.

El bloque de agenda agrega sobre la `Availability` del motor las tres cosas que
le faltaban: donde se atiende (consultorio), hasta cuando (vigencia por rango de
fechas) y cuanto dura un turno de esa agenda. Ver app/services/agenda_blocks.py.

Ninguna tabla existente se toca y ninguna fila se migra: las instancias que hoy
estan andando tienen su jornada cargada como `Availability` y siguen dando
turnos por ese camino. Un `upgrade` sobre una base con datos no le cambia el
comportamiento a nadie -- las tablas nuevas nacen vacias y el codigo se degrada
a lo de antes cuando no hay bloque que cubra el horario.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_consultorios_y_bloques"
down_revision = "0014_entidad_id_texto"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consultorios",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("branch_id", sa.String(100), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_consultorios_branch_id", "consultorios", ["branch_id"])

    op.create_table(
        "agenda_blocks",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("resource_id", sa.String(100), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column(
            "consultorio_id", sa.String(100), sa.ForeignKey("consultorios.id"), nullable=False,
        ),
        sa.Column("weekday", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.Time, nullable=False),
        sa.Column("ends_at", sa.Time, nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        # NULL = se repite indefinidamente. Es el caso normal de una agenda
        # estable, asi que no lleva default: quien no lo manda no quiere fin.
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.Column("slot_minutes", sa.Integer, nullable=False),
        sa.Column("modality", sa.String(20), nullable=False, server_default="turnos"),
    )
    op.create_index("ix_agenda_blocks_resource_id", "agenda_blocks", ["resource_id"])
    op.create_index("ix_agenda_blocks_consultorio_id", "agenda_blocks", ["consultorio_id"])

    # En que consultorio ocurre cada turno. Tabla aparte y no una columna de
    # `appointments`: el turno lo modela LibraGenda y agregarle un campo seria
    # cambiar el motor. Mismo patron que `branch_contacts` con la sede.
    #
    # Sin FK a `appointments`: la fila la escribe MedLibra y el turno lo maneja
    # el motor, que no sabe de esta tabla y por lo tanto no la limpiaria en un
    # borrado. Una FK dejaria el borrado del motor fallando por una tabla que
    # no conoce.
    op.create_table(
        "appointment_rooms",
        sa.Column("appointment_id", sa.String(100), primary_key=True),
        sa.Column(
            "consultorio_id", sa.String(100), sa.ForeignKey("consultorios.id"), nullable=False,
        ),
    )
    op.create_index(
        "ix_appointment_rooms_consultorio_id", "appointment_rooms", ["consultorio_id"],
    )


def downgrade():
    op.drop_index("ix_appointment_rooms_consultorio_id", table_name="appointment_rooms")
    op.drop_table("appointment_rooms")
    op.drop_index("ix_agenda_blocks_consultorio_id", table_name="agenda_blocks")
    op.drop_index("ix_agenda_blocks_resource_id", table_name="agenda_blocks")
    op.drop_table("agenda_blocks")
    op.drop_index("ix_consultorios_branch_id", table_name="consultorios")
    op.drop_table("consultorios")
