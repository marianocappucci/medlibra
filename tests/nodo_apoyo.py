"""Lo que comparten los tests del nodo sin conexión (ADR-045).

Ninguno levanta el proceso real del nodo (`libraedge-nodo`) ni el transporte: se ejercitan las piezas de MedLibra con las
tablas de LibraEdge creadas por la cadena de migraciones, que es exactamente lo que el producto ve en un nodo. La misma base
hace de nodo y de central **en momentos distintos** (`SyncReceiver` aplica en el central lo que el nodo encoló):

1. *Fase del nodo*: la variable `LIBRAEDGE_NODE_ID` prendida; se opera y el outbox junta las operaciones.
2. `borrar_filas(...)` / `vaciar_lo_del_nodo()` borra lo que el nodo generó: lo que en la vida real no existe en el central
   hasta que sube. Los maestros y los turnos espejados se quedan, como el espejo los deja.
3. *Fase del central*: sin la variable, `aplicar_en_el_central(operaciones)` pasa cada operación por el receptor real.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

NODO = "consultorio-1"


def _url_cruda() -> str:
    import motor_de_test

    return motor_de_test.TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def filas(sql: str, params: tuple = ()) -> list[tuple]:
    """Una consulta directa a la base del test (fuera de la app y de sus transacciones)."""
    import psycopg

    with psycopg.connect(_url_cruda()) as con:
        return con.execute(sql, params).fetchall()


def ejecutar(sql: str, params: tuple = ()) -> None:
    import psycopg

    with psycopg.connect(_url_cruda(), autocommit=True) as con:
        con.execute(sql, params)


def escribir_estado(ruta, en_linea: bool) -> None:
    ruta.write_text(json.dumps({
        "en_linea": en_linea, "ultima_sincronizacion_ok": datetime.now(UTC).isoformat(),
    }), encoding="utf-8")


@pytest.fixture
def nodo_apagado(monkeypatch, tmp_path):
    """Un nodo todavía apagado: la variable del archivo de estado puesta, sin `LIBRAEDGE_NODE_ID`.

    Sirve para preparar lo que el central manda (sedes, turnos, pacientes) antes de `prender()`. Devuelve un objeto con
    `prender()`, `apagar()` y `en_linea(bool)`."""
    estado = tmp_path / "estado-del-nodo.json"
    escribir_estado(estado, False)
    # Los tests que provocan un 500 a propósito (la transacción que se deshace) dejan su línea en `<LIBRA_ERRORES_DIR>/errores.jsonl`:
    # que sea la carpeta del test y no la del repo.
    monkeypatch.setenv("LIBRA_ERRORES_DIR", str(tmp_path / "errores"))
    monkeypatch.setenv("LIBRAEDGE_ESTADO", str(estado))
    monkeypatch.delenv("LIBRAEDGE_NODE_ID", raising=False)
    monkeypatch.delenv("MEDLIBRA_EDGE_NODE_ID", raising=False)
    control = SimpleNamespace(nodo=NODO)

    def prender() -> None:
        monkeypatch.setenv("LIBRAEDGE_NODE_ID", NODO)

    def apagar() -> None:
        monkeypatch.delenv("LIBRAEDGE_NODE_ID", raising=False)

    def en_linea(valor: bool) -> None:
        escribir_estado(estado, valor)

    control.prender, control.apagar, control.en_linea = prender, apagar, en_linea
    return control


@pytest.fixture
def nodo(nodo_apagado):
    """Este proceso es el nodo `consultorio-1`, sin conexión. `nodo.en_linea(True)` la devuelve."""
    nodo_apagado.prender()
    return nodo_apagado


def operaciones() -> list:
    """Las operaciones del outbox del nodo, en el orden en que ocurrieron (una sola secuencia por nodo)."""
    from libracore.db import core as libracore_core
    from libraedge.db.repository import NodeRepository

    with libracore_core.get_connection() as conn:
        return list(NodeRepository(conn).list_pending_operations(limit=1000))


def tipos_encolados() -> list[str]:
    return [op.operation_type for op in operaciones()]


def aplicar_en_el_central(ops: list) -> list[str]:
    """Pasa cada operación por el receptor real del central (con su `sync_inbox`) y devuelve el resultado de cada una:
    `accepted`, `duplicate` o `rejected: <motivo>`."""
    from libracore.db import core as libracore_core
    from libraedge.sync.receiver import SyncReceiver

    from app.routers.sincronizacion_offline import despachador

    resultados = []
    for op in ops:
        with libracore_core.get_connection() as conn:
            r = SyncReceiver(conn, despachador=despachador).accept(op)
            conn.commit()
        resultados.append(r.result if r.error is None else f"{r.result}: {r.error}")
    return resultados


def borrar_filas(tabla: str, ids: list[str], columna: str = "id") -> None:
    """Borra del 'central' lo que el nodo generó: en la vida real, el central no lo tiene hasta que sube."""
    for id_ in ids:
        ejecutar(f"DELETE FROM {tabla} WHERE {columna} = %s", (id_,))


def operacion_de(tipo: str, payload: dict, *, node_id: str = NODO, secuencia: int = 1, schema_version: int = 1,
                 agregado: str = "x", id_local: str = "1"):
    """La `OutboxOperation` que el central recibe del nodo, armada a mano (para los payloads mal formados)."""
    from libraedge.domain.sync import OutboxOperation

    return OutboxOperation(
        operation_id=f"{node_id}:{secuencia}", node_id=node_id, sequence=secuencia, operation_type=tipo,
        aggregate_type=agregado, aggregate_id=f"{node_id}:{agregado}:{id_local}",
        occurred_at="2026-10-25T10:00:00+00:00", schema_version=schema_version, payload=payload,
    )


def sembrar_consultorio(client, *, precio: str | None = "1000.00", paciente: dict | None = None) -> dict:
    """Lo que manda el central: una sede, un profesional, una prestación con su precio, un paciente y un turno confirmado
    (hecho como central, por la API). Devuelve los ids."""
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Dra. Vidal", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    paciente = paciente or {"id": "patient-1", "name": "Ana Pérez", "dni": "30111222"}
    assert client.post("/patients", json=paciente).status_code == 201
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    if precio is not None:
        client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": precio})
    creado = client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1", "client_id": paciente["id"],
        "starts_at": "2099-01-01T10:00:00",
    })
    assert creado.status_code == 201, creado.text
    turno = creado.json()["id"]
    assert client.post(f"/appointments/{turno}/confirm").status_code == 200
    return {"turno": turno, "paciente": paciente["id"], "sede": "branch-1", "profesional": "resource-1",
            "prestacion": "service-1"}
