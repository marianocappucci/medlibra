"""El consultorio pasa a ser un recurso secundario del turno (ADR-042).

Hasta ahora la sala de un turno vivía en `appointment_rooms` (una tabla de
MedLibra que el motor no conoce) y su choque lo chequeaba `AppointmentService`
**afuera** de la transacción de `reserve()`: dos profesionales que reservaban a
la vez veían los dos la sala libre y entraban los dos. Con la sala como
`Resource` y como recurso secundario del turno (`appointment_resources`, ADR-009
de LibraGenda), el motor la compara y la traba junto con el profesional.

## Qué mueve

1. **Una fila de `resources` por consultorio**, con el mismo `id` (el `Resource`
   es lo que el motor traba; la `ConsultorioRow` queda como extensión del
   vertical). Si ya hay un `Resource` con ese id y es un **profesional** (tiene
   turnos, bloques de agenda o disponibilidad) se corta con el motivo: elegir
   cuál de los dos se renombra es de una persona. Si existe y no es de nadie —un
   resto de una corrida anterior— se lo alinea con el consultorio.
2. **Cada fila de `appointment_rooms` pasa a `appointment_resources`**: el turno
   conserva su sala, ahora como recurso secundario. Se cuentan las filas antes y
   después, y **si no coinciden se corta antes de borrar nada**.
3. **Se borra `appointment_rooms`.**

Las filas de `appointment_rooms` cuyo turno ya no existe (la tabla no tenía FK a
`appointments` a propósito, ver `0015`) no tienen a quién colgarse: se avisan por
el log y se descartan con la tabla. No son datos de nadie.

## Qué NO mueve

Los turnos que **ya están solapados en una misma sala** (el defecto que esta
migración cierra) quedan como estaban: no hay un unique de base que los
rechace, y borrar o mover turnos ajenos no es de una migración. A partir de acá
no entran más.

## Downgrade

Hace el camino inverso: recrea `appointment_rooms`, le devuelve a cada turno su
consultorio, saca los consultorios de `appointment_resources` y **borra los
`Resource` de las salas** (si no, el código viejo los listaría como
profesionales en `/resources`). Se pierde lo que sólo existe en el modelo nuevo:
un bloqueo, una disponibilidad o un horario cargados *sobre la sala como
recurso*, que el código anterior no sabía ni leer.

Probada con datos (subida, bajada, resubida; conteos antes y después) en
`tests/test_migracion_consultorio_recurso.py`.

Revision ID: 0022_consultorio_recurso
Revises: 0021_patient_sequences
Create Date: 2026-10-17
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "0022_consultorio_recurso"
down_revision = "0021_patient_sequences"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

#: Tablas cuya columna `resource_id` es la del PROFESIONAL: si una sala figura ahí,
#: el id está compartido con un profesional y no se puede resolver solo.
_DE_PROFESIONAL = (
    ("appointments", "resource_id"),
    ("agenda_blocks", "resource_id"),
    ("availability", "resource_id"),
)


def _escalar(sql: str) -> int:
    return op.get_bind().execute(sa.text(sql)).scalar() or 0


def _tiene(tabla: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(tabla)


def _ids_compartidos_con_un_profesional() -> list[str]:
    """Consultorios cuyo id ya es el de un `Resource` que trabaja como profesional."""
    bind = op.get_bind()
    compartidos: set[str] = set()
    for tabla, columna in _DE_PROFESIONAL:
        if not _tiene(tabla):
            continue
        filas = bind.execute(sa.text(
            f"SELECT DISTINCT c.id FROM consultorios c "
            f"JOIN {tabla} t ON t.{columna} = c.id"
        )).fetchall()
        compartidos.update(fila[0] for fila in filas)
    return sorted(compartidos)


def upgrade():
    bind = op.get_bind()

    # -- 1. Un `Resource` por consultorio ---------------------------------
    compartidos = _ids_compartidos_con_un_profesional()
    if compartidos:
        raise RuntimeError(
            "no se puede pasar el consultorio a recurso: comparte id con un "
            f"profesional ({', '.join(compartidos)}). Renombrá el consultorio o "
            "el profesional y volvé a correr la migración."
        )
    bind.execute(sa.text(
        "UPDATE resources SET "
        "name = (SELECT c.name FROM consultorios c WHERE c.id = resources.id), "
        "branch_id = (SELECT c.branch_id FROM consultorios c WHERE c.id = resources.id), "
        "active = (SELECT c.active FROM consultorios c WHERE c.id = resources.id) "
        "WHERE id IN (SELECT id FROM consultorios)"
    ))
    bind.execute(sa.text(
        "INSERT INTO resources (id, name, branch_id, active) "
        "SELECT c.id, c.name, c.branch_id, c.active FROM consultorios c "
        "WHERE NOT EXISTS (SELECT 1 FROM resources r WHERE r.id = c.id)"
    ))

    # -- 2. La sala de cada turno, de `appointment_rooms` a `appointment_resources`
    if _tiene("appointment_rooms"):
        con_turno = (
            "FROM appointment_rooms ar "
            "JOIN appointments a ON a.id = ar.appointment_id "
            "JOIN consultorios c ON c.id = ar.consultorio_id"
        )
        total = _escalar("SELECT count(*) FROM appointment_rooms")
        a_mover = _escalar(f"SELECT count(*) {con_turno}")
        if total > a_mover:
            log.warning(
                "appointment_rooms: %s fila(s) sin turno que las sostenga, se descartan",
                total - a_mover,
            )
        bind.execute(sa.text(
            "INSERT INTO appointment_resources (appointment_id, resource_id, position) "
            "SELECT ar.appointment_id, ar.consultorio_id, "
            "COALESCE((SELECT MAX(x.position) + 1 FROM appointment_resources x "
            "          WHERE x.appointment_id = ar.appointment_id), 0) "
            f"{con_turno} "
            "WHERE NOT EXISTS (SELECT 1 FROM appointment_resources y "
            "                  WHERE y.appointment_id = ar.appointment_id "
            "                  AND y.resource_id = ar.consultorio_id)"
        ))
        movidas = _escalar(
            "SELECT count(*) FROM appointment_rooms ar "
            "JOIN appointment_resources x "
            "ON x.appointment_id = ar.appointment_id AND x.resource_id = ar.consultorio_id"
        )
        if movidas != a_mover:
            raise RuntimeError(
                f"la sala de {a_mover} turno(s) tenía que pasar a appointment_resources y "
                f"pasaron {movidas}: se corta antes de borrar appointment_rooms."
            )

        # -- 3. Se va la tabla vieja --------------------------------------
        op.drop_index("ix_appointment_rooms_consultorio_id", table_name="appointment_rooms")
        op.drop_table("appointment_rooms")


def downgrade():
    bind = op.get_bind()

    # -- 1. La tabla vieja, como la dejó `0015` ----------------------------
    if not _tiene("appointment_rooms"):
        op.create_table(
            "appointment_rooms",
            sa.Column("appointment_id", sa.String(100), primary_key=True),
            sa.Column(
                "consultorio_id", sa.String(100), sa.ForeignKey("consultorios.id"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_appointment_rooms_consultorio_id", "appointment_rooms", ["consultorio_id"],
        )

    # -- 2. Cada turno recupera su consultorio ------------------------------
    bind.execute(sa.text(
        "INSERT INTO appointment_rooms (appointment_id, consultorio_id) "
        "SELECT x.appointment_id, MIN(x.resource_id) "
        "FROM appointment_resources x JOIN consultorios c ON c.id = x.resource_id "
        "WHERE NOT EXISTS (SELECT 1 FROM appointment_rooms ar "
        "                  WHERE ar.appointment_id = x.appointment_id) "
        "GROUP BY x.appointment_id"
    ))
    bind.execute(sa.text(
        "DELETE FROM appointment_resources "
        "WHERE resource_id IN (SELECT id FROM consultorios)"
    ))

    # -- 3. Las salas dejan de ser recursos ---------------------------------
    # Todo lo que cuelga de la sala como recurso (bloqueos, disponibilidad,
    # excepciones, política de agenda) existe sólo en el modelo nuevo. Se saca
    # tabla por tabla leyendo las FK, para no depender de una lista a mano que
    # envejezca con el motor. `appointments` y `agenda_blocks` no se tocan: si una
    # sala figurara ahí como profesional, el DELETE de abajo tiene que fallar a
    # los gritos y no llevarse turnos.
    insp = sa.inspect(bind)
    for tabla in insp.get_table_names():
        if tabla in ("appointments", "agenda_blocks"):
            continue
        for fk in insp.get_foreign_keys(tabla):
            if fk["referred_table"] == "resources":
                columna = fk["constrained_columns"][0]
                bind.execute(sa.text(
                    f"DELETE FROM {tabla} "
                    f"WHERE {columna} IN (SELECT id FROM consultorios)"
                ))
    bind.execute(sa.text(
        "DELETE FROM resources WHERE id IN (SELECT id FROM consultorios)"
    ))
