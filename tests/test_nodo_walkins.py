# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La demanda espontánea que se anota sin conexión (ADR-045).

Decisión del humano (2026-10-25): *demanda espontánea, sí*. Lo que se fija acá:

- la llegada anotada en el nodo sube como `walkin.registrado` **en la misma transacción**, con un número de llegada
  **provisorio negativo** (`UNIQUE (block_id, day, arrival_order)` no se puede chocar con lo que se anote en la web);
- el central la crea con el mismo id y **el siguiente número real de la fila**, una sola vez;
- llamarla, completarla o cancelarla en la PC sube como `walkin.estado` y el central aplica las transiciones de la web;
- la fila del nodo se ve en orden: primero lo que ya tenía número, después lo anotado sin conexión.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from nodo_apoyo import (
    aplicar_en_el_central,
    borrar_filas,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    operacion_de,
    operaciones,
    tipos_encolados,
)

LUNES = "2026-07-20"


@pytest.fixture
def consultorio(admin_client):
    c = admin_client
    c.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte", "timezone": "America/Argentina/Buenos_Aires"})
    c.post("/resources", json={"id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1"})
    c.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1"})
    c.post("/services", json={"id": "consulta", "name": "Consulta", "duration_minutes": 30})
    for i, nombre in enumerate(["Ana", "Beto", "Carla"], start=1):
        c.post("/patients", json={"id": f"p-{i}", "name": nombre})
    bloque = c.post("/agenda-blocks", json={
        "resource_id": "dr-molina", "consultorio_id": "cons-1", "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
        "valid_from": "2026-07-01", "valid_to": None, "slot_minutes": 20, "modality": "espontanea",
    })
    assert bloque.status_code == 201, bloque.text
    return bloque.json()["id"]


def _llega(client, bloque: str, paciente: str = "p-1"):
    r = client.post(f"/agenda-blocks/{bloque}/walkins", json={"client_id": paciente, "service_id": "consulta", "day": LUNES})
    assert r.status_code == 201, r.text
    return r.json()


def _fila(client, bloque: str) -> list[dict]:
    return client.get(f"/agenda-blocks/{bloque}/walkins", params={"day": LUNES}).json()


def test_anotar_una_llegada_en_el_nodo_sube_con_numero_provisorio(admin_client, consultorio, nodo_apagado):
    _llega(admin_client, consultorio, "p-1")   # la del central: número 1
    nodo_apagado.prender()
    a = _llega(admin_client, consultorio, "p-2")
    b = _llega(admin_client, consultorio, "p-3")

    assert (a["arrival_order"], b["arrival_order"]) == (-1, -2)
    assert tipos_encolados() == ["walkin.registrado", "walkin.registrado"]
    op = operaciones()[0]
    assert op.aggregate_id.endswith(f":walkin:{a['id']}")
    assert op.payload["block_id"] == consultorio and op.payload["day"] == LUNES and op.payload["client_id"] == "p-2"
    # la fila se ve en orden: lo que ya tenía número, y después lo anotado sin conexión en el orden en que se anotó
    assert [w["client_id"] for w in _fila(admin_client, consultorio)] == ["p-1", "p-2", "p-3"]


def test_fuera_de_un_nodo_la_llegada_es_la_de_siempre(admin_client, consultorio, nodo_apagado):
    assert _llega(admin_client, consultorio)["arrival_order"] == 1
    assert tipos_encolados() == []


def test_la_llegada_y_su_operacion_son_una_sola_transaccion(admin_client, consultorio, nodo, monkeypatch):
    from libragenda import atencion_en_nodo

    def falla(*args, **kwargs):
        raise RuntimeError("el outbox no anda")

    monkeypatch.setattr(atencion_en_nodo, "encolar_en_nodo", falla)
    with pytest.raises(RuntimeError):
        admin_client.post(f"/agenda-blocks/{consultorio}/walkins",
                          json={"client_id": "p-1", "service_id": "consulta", "day": LUNES})
    assert filas("SELECT count(*) FROM walkins") == [(0,)]


def _anotar_en_el_nodo_y_subir(client, nodo_apagado, bloque: str, *pacientes: str):
    nodo_apagado.prender()
    llegadas = [_llega(client, bloque, p) for p in pacientes]
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("walkins", [w["id"] for w in llegadas])   # en el central no existen hasta que suben
    return llegadas, ops


def test_el_central_le_da_el_siguiente_numero_real_de_la_fila(admin_client, consultorio, nodo_apagado):
    _llega(admin_client, consultorio, "p-1")                      # en la web: 1
    llegadas, ops = _anotar_en_el_nodo_y_subir(admin_client, nodo_apagado, consultorio, "p-2", "p-3")
    _llega(admin_client, consultorio, "p-1")                      # y en la web, mientras tanto: 2

    assert aplicar_en_el_central(ops) == ["accepted", "accepted"]
    fila = admin_client.get(f"/agenda-blocks/{consultorio}/walkins", params={"day": LUNES}).json()
    assert [(w["arrival_order"], w["client_id"]) for w in fila] == [(1, "p-1"), (2, "p-1"), (3, "p-2"), (4, "p-3")]
    assert {w["id"] for w in fila} >= {w["id"] for w in llegadas}, "con el mismo id que le puso la PC"
    assert {w["status"] for w in fila} == {"waiting"}


def test_la_misma_llegada_dos_veces_es_una_sola(admin_client, consultorio, nodo_apagado):
    llegadas, ops = _anotar_en_el_nodo_y_subir(admin_client, nodo_apagado, consultorio, "p-2")
    repetida = operacion_de("walkin.registrado", ops[0].payload, secuencia=40, agregado="walkin")

    assert aplicar_en_el_central(ops + ops + [repetida]) == ["accepted", "duplicate", "accepted"]
    assert filas("SELECT arrival_order FROM walkins") == [(1,)]


def test_llamar_completar_y_cancelar_en_el_nodo_suben_como_estado(admin_client, consultorio, nodo_apagado):
    nodo_apagado.prender()
    a = _llega(admin_client, consultorio, "p-1")
    b = _llega(admin_client, consultorio, "p-2")
    assert admin_client.post(f"/walkins/{a['id']}/llamar").json()["status"] == "in_progress"
    assert admin_client.post(f"/walkins/{a['id']}/completar").json()["status"] == "completed"
    assert admin_client.post(f"/walkins/{b['id']}/cancelar").json()["status"] == "cancelled"
    # una transición inválida no sube nada
    assert admin_client.post(f"/walkins/{a['id']}/cancelar").status_code == 409
    assert tipos_encolados() == ["walkin.registrado"] * 2 + ["walkin.estado"] * 3
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("walkins", [a["id"], b["id"]])

    assert aplicar_en_el_central(ops) == ["accepted"] * 5
    estados = {w["client_id"]: (w["arrival_order"], w["status"]) for w in _fila(admin_client, consultorio)}
    assert estados == {"p-1": (1, "completed"), "p-2": (2, "cancelled")}


def test_la_llamada_hecha_en_la_pc_llega_al_central_con_su_instante(admin_client, consultorio, nodo_apagado):
    """ADR-048: la espera de un atendido sin conexión se mide con la hora en que la PC lo llamó, no con la de cuando subió."""
    nodo_apagado.prender()
    a = _llega(admin_client, consultorio, "p-1")
    b = _llega(admin_client, consultorio, "p-2")
    llamada = admin_client.post(f"/walkins/{a['id']}/llamar").json()
    admin_client.post(f"/walkins/{a['id']}/completar")
    admin_client.post(f"/walkins/{b['id']}/cancelar")
    ops = operaciones()
    nodo_apagado.apagar()

    de_la_pc = next(o for o in ops if o.payload.get("estado") == "in_progress").payload["at"]
    assert llamada["called_at"] is not None
    assert datetime.fromisoformat(de_la_pc) == datetime.fromisoformat(llamada["called_at"]), \
        "la fila de la PC y la operación llevan el mismo instante"
    borrar_filas("walkins", [a["id"], b["id"]])

    assert aplicar_en_el_central(ops) == ["accepted"] * 5
    assert filas("SELECT called_at FROM walkins WHERE client_id = 'p-1'") == [(datetime.fromisoformat(de_la_pc),)]
    # completar no lo pisa, y quien se fue sin que lo llamaran no tiene llamada
    assert filas("SELECT called_at FROM walkins WHERE client_id = 'p-2'") == [(None,)]
    # y la web lo devuelve igual que si lo hubiera llamado ella
    por_cliente = {w["client_id"]: w["called_at"] for w in _fila(admin_client, consultorio)}
    assert datetime.fromisoformat(por_cliente["p-1"]) == datetime.fromisoformat(de_la_pc) and por_cliente["p-2"] is None


def test_un_pase_que_la_web_ya_no_admite_va_a_revision_manual(admin_client, consultorio, nodo_apagado):
    """La llegada se canceló en la web mientras la PC la llamaba: no se pisa, y la operación no se pierde."""
    a = _llega(admin_client, consultorio, "p-1")
    nodo_apagado.prender()
    assert admin_client.post(f"/walkins/{a['id']}/llamar").status_code == 200
    ops = operaciones()
    nodo_apagado.apagar()
    admin_client.post(f"/walkins/{a['id']}/cancelar")

    resultado = aplicar_en_el_central(ops)[0]
    assert resultado.startswith("rejected") and "cancelled" in resultado and "revisar a mano" in resultado
    assert filas("SELECT status FROM walkins") == [("cancelled",)]


def test_el_mismo_estado_otra_vez_no_hace_nada(admin_client, consultorio, nodo_apagado):
    a = _llega(admin_client, consultorio, "p-1")
    nodo_apagado.prender()
    admin_client.post(f"/walkins/{a['id']}/llamar")
    op = operaciones()[0]
    nodo_apagado.apagar()
    repetida = operacion_de("walkin.estado", op.payload, secuencia=41, agregado="walkin")

    assert aplicar_en_el_central([op, repetida]) == ["accepted", "accepted"]
    assert filas("SELECT status FROM walkins") == [("in_progress",)]


def test_una_llegada_de_un_paciente_provisorio_se_traduce(admin_client, consultorio, nodo_apagado):
    """El paciente anotado sin conexión y su llegada suben en orden: el central traduce el `client_id`."""
    nodo_apagado.prender()
    paciente = admin_client.post("/patients", json={"name": "Nuevo Paciente", "dni": "33444555"}).json()["id"]
    llegada = _llega(admin_client, consultorio, paciente)
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("walkins", [llegada["id"]])
    borrar_filas("patients", [paciente])
    borrar_filas("agenda_clients", [paciente])

    assert aplicar_en_el_central(ops) == ["accepted", "accepted"]
    # (los pacientes de la fixture se llaman `p-1` a `p-3`, así que el contador arranca en 3: el próximo es `p-004`)
    assert filas("SELECT w.client_id, p.dni FROM walkins w JOIN patients p ON p.id = w.client_id") == [("p-004", "33444555")]


@pytest.mark.parametrize(("cambio", "motivo"), [
    ({"block_id": "no-existe"}, "bloque de agenda"),
    ({"service_id": "no-existe"}, "prestación"),
    ({"client_id": "p-99"}, "paciente"),
    ({"day": "20/07/2026"}, "ISO 8601"),
    ({"created_at": "2026-07-20T10:00:00"}, "zona"),
    ({"version": 3}, "versión"),
])
def test_una_llegada_mal_formada_va_a_revision_manual(admin_client, consultorio, nodo_apagado, cambio, motivo):
    llegadas, ops = _anotar_en_el_nodo_y_subir(admin_client, nodo_apagado, consultorio, "p-2")
    mala = operacion_de("walkin.registrado", {**ops[0].payload, **cambio}, secuencia=3, agregado="walkin")

    resultado = aplicar_en_el_central([mala])[0]
    assert resultado.startswith("rejected") and motivo in resultado, resultado
    assert filas("SELECT count(*) FROM walkins") == [(0,)]
