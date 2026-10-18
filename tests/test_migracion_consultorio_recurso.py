"""La migración `0022`: la sala de cada turno pasa a recurso secundario del motor.

Se ensaya con **datos**, que es lo que una migración de datos no puede saltear:
subida, bajada y resubida, con los conteos de cada tabla antes y después. Las
tablas de LibraGenda salen de `create_all()` (la cadena de LibraGenda la corre
el CI aparte y las revisiones de acá tienen FK contra ella) y `appointment_rooms`,
que ya no es un modelo, se crea a mano como la dejó `0015`. Después se estampa
la revisión anterior y se sube **sólo esta**, igual que `test_migracion_sin_users`.

El caso que importa está sembrado a propósito: **dos turnos de profesionales
distintos en el mismo consultorio y la misma hora**, que es el defecto que cierra
el cambio. La migración no puede ni esconderlo ni rechazarlo: lo conserva tal
cual, y el motor corta los nuevos.
"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from motor_de_test import TEST_DATABASE_URL

PREVIA = "0021_patient_sequences"
NUEVA = "0022_consultorio_recurso"


def _cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _sql(sentencia: str, parametros=None):
    import psycopg

    with psycopg.connect(_cruda(TEST_DATABASE_URL), autocommit=True) as c:
        cur = c.execute(sentencia, parametros)
        return cur.fetchall() if cur.description else None


def _una(sentencia: str):
    return _sql(sentencia)[0][0]


@pytest.fixture
def base_con_datos(monkeypatch):
    """La base como la deja la `0021`, con una clínica sembrada."""
    from libragenda.sqlalchemy_repository import Base
    from sqlalchemy import create_engine

    from app.services import agenda_blocks, consultorios  # noqa: F401 - registran sus modelos

    monkeypatch.setenv("MEDLIBRA_DATABASE_URL", TEST_DATABASE_URL)
    _sql("DROP SCHEMA public CASCADE")
    _sql("CREATE SCHEMA public")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    # Como la dejó `0015`: sin FK a `appointments`, a propósito.
    _sql("""
        CREATE TABLE appointment_rooms (
            appointment_id VARCHAR(100) PRIMARY KEY,
            consultorio_id VARCHAR(100) NOT NULL REFERENCES consultorios (id)
        )
    """)
    _sql("CREATE INDEX ix_appointment_rooms_consultorio_id ON appointment_rooms (consultorio_id)")

    _sql("INSERT INTO branches (id, name, active, timezone) VALUES ('b1', 'Sede', true, 'UTC')")
    _sql("INSERT INTO clients (id, name, active) VALUES ('c1', 'Paciente', true)")
    _sql("INSERT INTO services (id, name, duration_seconds, active) VALUES ('s1', 'Consulta', 1800, true)")
    for rid, nombre in (("dr-molina", "Dr. Molina"), ("dra-vidal", "Dra. Vidal"), ("equipo-1", "Ecógrafo")):
        _sql("INSERT INTO resources (id, name, branch_id, active) VALUES (%s, %s, 'b1', true)", (rid, nombre))
    for cid, nombre, activo in (("cons-1", "Consultorio 1", True), ("cons-2", "Consultorio 2", True),
                                ("cons-3", "Consultorio 3 (sin turnos)", False)):
        _sql("INSERT INTO consultorios (id, name, branch_id, active) VALUES (%s, %s, 'b1', %s)",
             (cid, nombre, activo))
    # (id, profesional, hora, estado)
    for tid, prof, hora, estado in (
        ("t1", "dr-molina", "10:00", "confirmed"),
        ("t2", "dra-vidal", "10:00", "pending"),      # 🔴 el MISMO consultorio y hora que t1
        ("t3", "dra-vidal", "11:00", "cancelled"),
        ("t4", "dr-molina", "12:00", "pending"),      # dado por la disponibilidad vieja: sin sala
    ):
        _sql(
            "INSERT INTO appointments (id, resource_id, service_id, client_id, starts_at, duration_seconds, "
            "status, branch_id, overbooked) VALUES (%s, %s, 's1', 'c1', %s, 1800, %s, 'b1', false)",
            (tid, prof, f"2026-07-20 {hora}+00", estado),
        )
    # t1 ya ocupaba otro recurso secundario: la sala tiene que ir DESPUÉS.
    _sql("INSERT INTO appointment_resources (appointment_id, resource_id, position) VALUES ('t1', 'equipo-1', 0)")
    for tid, cid in (("t1", "cons-1"), ("t2", "cons-1"), ("t3", "cons-2"), ("fantasma", "cons-1")):
        _sql("INSERT INTO appointment_rooms (appointment_id, consultorio_id) VALUES (%s, %s)", (tid, cid))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.stamp(cfg, PREVIA)
    return cfg


def _hay(tabla: str) -> bool:
    return _una(
        "SELECT count(*) FROM information_schema.tables "
        f"WHERE table_schema = 'public' AND table_name = '{tabla}'"
    ) == 1


def _foto() -> dict:
    """Los conteos y el contenido que la migración tiene que mover o conservar."""
    return {
        "turnos": _una("SELECT count(*) FROM appointments"),
        "consultorios": _una("SELECT count(*) FROM consultorios"),
        "recursos": _una("SELECT count(*) FROM resources"),
        "recursos_de_salas": _una("SELECT count(*) FROM resources WHERE id IN (SELECT id FROM consultorios)"),
        "secundarios": _sql(
            "SELECT appointment_id, resource_id, position FROM appointment_resources "
            "ORDER BY appointment_id, position"
        ),
        "salas": (
            _sql("SELECT appointment_id, consultorio_id FROM appointment_rooms ORDER BY 1")
            if _hay("appointment_rooms") else None
        ),
    }


def test_sube_baja_y_resube_con_datos(base_con_datos):
    cfg = base_con_datos
    antes = _foto()
    # Los controles de lo sembrado: sin esto, una base vacía pasaría todo.
    assert antes["turnos"] == 4
    assert antes["recursos_de_salas"] == 0
    assert len(antes["salas"]) == 4
    assert antes["secundarios"] == [("t1", "equipo-1", 0)]

    command.upgrade(cfg, NUEVA)
    arriba = _foto()

    assert arriba["turnos"] == antes["turnos"], "la migración no toca turnos"
    assert arriba["consultorios"] == antes["consultorios"]
    # Un Resource por consultorio, con el mismo id y los mismos datos.
    assert arriba["recursos"] == antes["recursos"] + 3
    assert _sql(
        "SELECT r.id, r.name, r.branch_id, r.active FROM resources r "
        "WHERE r.id IN (SELECT id FROM consultorios) ORDER BY r.id"
    ) == [("cons-1", "Consultorio 1", "b1", True), ("cons-2", "Consultorio 2", "b1", True),
          ("cons-3", "Consultorio 3 (sin turnos)", "b1", False)]
    # Cada sala pasó a recurso secundario de su turno; la que ya tenía otro va segunda.
    assert arriba["secundarios"] == [
        ("t1", "equipo-1", 0), ("t1", "cons-1", 1), ("t2", "cons-1", 0), ("t3", "cons-2", 0),
    ]
    # El turno sin sala (t4) y la fila huérfana (`fantasma`) no generan nada.
    assert not _hay("appointment_rooms")

    command.downgrade(cfg, PREVIA)
    abajo = _foto()

    assert abajo["turnos"] == antes["turnos"]
    assert abajo["recursos"] == antes["recursos"], "el código viejo listaría las salas como profesionales"
    assert abajo["recursos_de_salas"] == 0
    assert abajo["secundarios"] == antes["secundarios"]
    # Cada turno recupera su consultorio. La huérfana no vuelve: no tenía turno.
    assert abajo["salas"] == [("t1", "cons-1"), ("t2", "cons-1"), ("t3", "cons-2")]

    command.upgrade(cfg, NUEVA)
    assert _foto() == arriba, "la resubida tiene que dejar exactamente lo mismo que la primera subida"


def test_el_solapamiento_que_ya_existia_se_conserva(base_con_datos):
    """t1 y t2: profesionales distintos, misma sala, misma hora. No se esconde."""
    command.upgrade(base_con_datos, NUEVA)

    comparten = _sql(
        "SELECT appointment_id FROM appointment_resources WHERE resource_id = 'cons-1' ORDER BY 1"
    )
    assert comparten == [("t1",), ("t2",)]


def test_un_resource_suelto_con_el_id_de_la_sala_se_alinea(base_con_datos):
    """Una corrida a medias (o un `Resource` que quedó): no es de nadie, se alinea."""
    _sql("INSERT INTO resources (id, name, branch_id, active) VALUES ('cons-1', 'viejo', NULL, false)")

    command.upgrade(base_con_datos, NUEVA)

    assert _sql("SELECT name, branch_id, active FROM resources WHERE id = 'cons-1'") == [
        ("Consultorio 1", "b1", True),
    ]
    assert _una("SELECT count(*) FROM resources WHERE id = 'cons-1'") == 1


def test_una_sala_con_el_id_de_un_profesional_corta_y_no_deja_nada_a_medias(base_con_datos):
    """🔴 El control del anterior: si el id es de un profesional, no se resuelve solo."""
    _sql("INSERT INTO consultorios (id, name, branch_id, active) VALUES ('dr-molina', 'Molina', 'b1', true)")

    with pytest.raises(RuntimeError, match="dr-molina"):
        command.upgrade(base_con_datos, NUEVA)

    # DDL transaccional: no quedó ni la tabla borrada ni recursos de más.
    assert _hay("appointment_rooms")
    assert _una("SELECT count(*) FROM appointment_rooms") == 4
    assert _una("SELECT count(*) FROM resources WHERE id IN ('cons-1', 'cons-2', 'cons-3')") == 0


def test_la_migracion_corre_sobre_una_base_sin_turnos(base_con_datos):
    """La demo recién reseteada: consultorios y nada más."""
    _sql("DELETE FROM appointment_rooms")
    _sql("DELETE FROM appointment_resources")
    _sql("DELETE FROM appointments")

    command.upgrade(base_con_datos, NUEVA)
    assert _una("SELECT count(*) FROM resources WHERE id IN (SELECT id FROM consultorios)") == 3
    assert _una("SELECT count(*) FROM appointment_resources") == 0
    command.downgrade(base_con_datos, PREVIA)
    assert _una("SELECT count(*) FROM resources WHERE id IN (SELECT id FROM consultorios)") == 0
