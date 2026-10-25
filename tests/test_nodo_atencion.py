# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""Atender un turno en un nodo sin conexión, y el envío a ContaLibra desde el central (ADR-045, PR 10 del plan).

Dos fases en la misma base, como en LibraClub: el nodo atiende (y sólo encola), y después `aplicar_en_el_central` pasa cada
operación por el receptor real de LibraEdge con el despachador del producto.

Lo que se fija acá, con lo que costaría que fallara:

- **atender sin conexión** deja la fila propia y la operación en UNA transacción, y no toca el turno del espejo;
- el nodo **no llama a ContaLibra**: lo manda el central al aplicar, y **una sola vez** aunque la operación se entregue
  dos veces, aunque la web ya la haya mandado, o aunque dos entregas lleguen a la vez;
- un turno que en la web se canceló **no pierde lo cobrado** y queda a revisar;
- lo que el nodo no hace (dar, confirmar, mover o cancelar turnos) es 409, no un 500.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal

import pytest
from nodo_apoyo import (
    NODO,
    aplicar_en_el_central,
    ejecutar,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    operacion_de,
    operaciones,
    sembrar_consultorio,
    tipos_encolados,
)


@pytest.fixture
def enviados(monkeypatch):
    """ContaLibra de mentira: junta cada envío. `enviados.falla = True` hace que el siguiente falle (un 5xx)."""
    monkeypatch.setenv("CONTALIBRA_URL", "https://contalibra.example")
    capturados = type("Envios", (list,), {"falla": False, "demora": 0.0})()

    async def falso(**kwargs):
        if capturados.demora:
            time.sleep(capturados.demora)
        if capturados.falla:
            raise RuntimeError("502: ContaLibra no contesta")
        capturados.append(kwargs)
        return {"venta": {"id": 700 + len(capturados)}, "factura": None, "ya_existia": False}

    from app.services import contalibra

    monkeypatch.setattr(contalibra, "enviar_consulta", falso)
    return capturados


def _senar(client, turno: str, monto: str, medio: str) -> None:
    sena = client.post(f"/appointments/{turno}/deposit", json={"amount": monto})
    assert sena.status_code in (200, 201), sena.text
    assert client.post(f"/deposits/{sena.json()['id']}/mark-paid", json={"medio_pago": medio}).status_code == 200


def _agenda(client, ids: dict) -> dict:
    r = client.get(f"/resources/{ids['profesional']}/agenda", params={"date_from": "2098-12-31", "date_to": "2099-01-02"})
    assert r.status_code == 200, r.text
    return {t["id"]: t for t in r.json()}


def _estado_del_turno(turno: str) -> str:
    return filas("SELECT status FROM appointments WHERE id = %s", (turno,))[0][0]


# ── En el nodo: atender ──────────────────────────────────────────────────────────────────────────────────────────────


def test_atender_en_el_nodo_deja_la_fila_propia_y_la_operacion_y_no_toca_el_turno(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()

    r = admin_client.post(f"/appointments/{ids['turno']}/start")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": ids["turno"], "status": "in_progress", "contalibra": None, "atendido_sin_conexion": True}

    assert tipos_encolados() == ["turno.atendido"]
    assert filas("SELECT count(*) FROM agenda_node_attendances WHERE appointment_id = %s", (ids["turno"],)) == [(1,)]
    # El turno del espejo no se escribe (la guarda de LibraEdge lo impide en un nodo real): la atención es una fila aparte.
    assert _estado_del_turno(ids["turno"]) == "confirmed"
    operacion = operaciones()[0]
    assert operacion.payload["estado"] == "in_progress" and operacion.payload["turno_id"] == ids["turno"]


def test_la_agenda_del_nodo_muestra_la_atencion_encima_del_espejo(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    assert _agenda(admin_client, ids)[ids["turno"]]["status"] == "confirmed"
    nodo_apagado.prender()
    admin_client.post(f"/appointments/{ids['turno']}/start")

    turno = _agenda(admin_client, ids)[ids["turno"]]
    assert turno["status"] == "in_progress"
    assert turno["atendido_en_la_pc"] is True and turno["a_revisar"] is False


def test_completar_en_el_nodo_lleva_la_consulta_y_los_pagos_y_no_llama_a_contalibra(admin_client, nodo_apagado, enviados):
    """El nodo no guarda el token de ContaLibra y no manda nada: la consulta viaja en `extra` (la plata, como texto)."""
    ids = sembrar_consultorio(admin_client)
    _senar(admin_client, ids["turno"], "400.00", "mercadopago")
    nodo_apagado.prender()

    r = admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["contalibra"] is None
    assert enviados == [], "el nodo no llama a ContaLibra"

    consulta = operaciones()[0].payload["extra"]["consulta"]
    assert consulta["importe"] == "1000.00" and consulta["descripcion"] == "service-1"
    assert consulta["fecha"] == "2099-01-01" and consulta["medio_del_saldo"] == "efectivo"
    assert consulta["pagos"] == [
        {"medio": "mercadopago", "monto": "400.00", "referencia": "Seña"},
        {"medio": "efectivo", "monto": "600.00", "referencia": ""},
    ]
    assert operaciones()[0].payload["actor"] == "admin"


def test_completar_en_el_nodo_sigue_pidiendo_el_medio_del_saldo(admin_client, nodo_apagado):
    """La validación corre igual que en la web: lo que sube tiene que ser cobrable. Y no deja ni fila ni operación."""
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()

    assert admin_client.post(f"/appointments/{ids['turno']}/complete").status_code == 422
    assert tipos_encolados() == []
    assert filas("SELECT count(*) FROM agenda_node_attendances") == [(0,)]


def test_completar_sin_precio_no_lleva_consulta(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client, precio=None)
    nodo_apagado.prender()

    assert admin_client.post(f"/appointments/{ids['turno']}/complete").status_code == 200
    assert operaciones()[0].payload["extra"] is None


def test_completar_sin_el_modulo_de_facturacion_no_lleva_consulta(admin_client, nodo_apagado):
    """Completar el turno nunca se bloquea por el plan: sin el módulo, se atiende y no se manda nada (como en la web)."""
    ids = sembrar_consultorio(admin_client)
    admin_client.app.state.modules.set_enabled("facturacion", False)
    nodo_apagado.prender()

    assert admin_client.post(f"/appointments/{ids['turno']}/complete").status_code == 200
    assert operaciones()[0].payload["extra"] is None


def test_no_vino_en_el_nodo(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()

    r = admin_client.post(f"/appointments/{ids['turno']}/no-show")
    assert r.status_code == 200 and r.json()["status"] == "no_show"
    assert operaciones()[0].payload["estado"] == "no_show"
    # Un turno que no vino no se atiende después: la misma máquina de estados que la web.
    assert admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"}).status_code == 409
    assert tipos_encolados() == ["turno.atendido"]


def test_en_curso_y_despues_completado_son_dos_atenciones_y_empezar_dos_veces_se_rechaza(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()

    assert admin_client.post(f"/appointments/{ids['turno']}/start").status_code == 200
    assert admin_client.post(f"/appointments/{ids['turno']}/start").status_code == 409
    assert admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"}).status_code == 200
    assert [op.payload["estado"] for op in operaciones()] == ["in_progress", "completed"]


def test_un_turno_que_no_existe_es_404(admin_client, nodo_apagado):
    sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    assert admin_client.post("/appointments/no-existe/start").status_code == 404


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), [
    ("POST", "/appointments", {"resource_id": "resource-1", "service_id": "service-1", "client_id": "patient-1",
                               "starts_at": "2099-01-02T10:00:00"}),
    ("POST", "/appointments/{t}/confirm", None),
    ("POST", "/appointments/{t}/cancel", {}),
    ("POST", "/appointments/{t}/reschedule", {"starts_at": "2099-01-03T10:00:00"}),
])
def test_dar_confirmar_cancelar_y_mover_turnos_es_409_en_el_nodo(admin_client, nodo_apagado, metodo, ruta, cuerpo):
    """Decisión del humano: la agenda del nodo es de sólo consulta. Sin conexión: `sin_conexion`; con conexión el nodo
    tampoco lo hace (no tiene cómo subirlo): `solo_en_el_central`, que se hace desde la web."""
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    url = ruta.format(t=ids["turno"])

    r = admin_client.request(metodo, url, json=cuerpo)
    assert r.status_code == 409, (url, r.text)
    assert r.json()["detail"]["codigo"] == "sin_conexion"

    nodo_apagado.en_linea(True)
    r = admin_client.request(metodo, url, json=cuerpo)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central"
    assert tipos_encolados() == []


def test_fuera_de_un_nodo_los_turnos_andan_como_siempre(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    assert admin_client.post(f"/appointments/{ids['turno']}/start").status_code == 200
    assert _estado_del_turno(ids["turno"]) == "in_progress"
    assert filas("SELECT count(*) FROM agenda_node_attendances") == [(0,)]
    assert admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"}).status_code == 200
    # `no-show` desde `completed` no se puede, pero otro turno confirmado sí:
    nuevo = admin_client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1", "client_id": "patient-1", "starts_at": "2099-01-01T12:00:00",
    }).json()["id"]
    admin_client.post(f"/appointments/{nuevo}/confirm")
    assert admin_client.post(f"/appointments/{nuevo}/no-show").json()["status"] == "no_show"
    assert _estado_del_turno(nuevo) == "no_show"


# ── En el central: aplicar y mandar a ContaLibra ─────────────────────────────────────────────────────────────────────


def _atender_y_subir(client, nodo, ids, *, medio="efectivo", sena: tuple[str, str] | None = None) -> list:
    """Fase del nodo (completar con la plata) y devuelve las operaciones; deja el proceso como central."""
    if sena:
        _senar(client, ids["turno"], *sena)
    nodo.prender()
    assert client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": medio}).status_code == 200
    ops = operaciones()
    nodo.apagar()
    return ops


def test_el_central_aplica_la_atencion_y_manda_la_consulta_una_vez(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids, sena=("400.00", "mercadopago"))
    ejecutar("DELETE FROM agenda_node_attendances")   # el central no tiene la fila propia del nodo

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert _estado_del_turno(ids["turno"]) == "completed"
    assert len(enviados) == 1
    envio = enviados[0]
    assert envio["appointment_id"] == ids["turno"] and envio["fecha"] == "2099-01-01"
    assert envio["importe"] == Decimal("1000.00") and envio["iva_rate"] is not None
    assert envio["pagos"] == [
        {"medio": "mercadopago", "monto": Decimal("400.00"), "referencia": "Seña"},
        {"medio": "efectivo", "monto": Decimal("600.00"), "referencia": ""},
    ]
    assert envio["paciente"]["name"] == "Ana Pérez"
    fila = filas("SELECT estado, venta_id, intentos, medio_del_saldo FROM envios_a_contalibra")
    assert fila == [("enviado", 701, 1, "efectivo")]
    assert admin_client.get("/turnos-a-revisar").json() == []


def test_la_misma_operacion_dos_veces_no_manda_dos_veces(admin_client, nodo_apagado, enviados):
    """El outbox entrega al menos una vez: el receptor la deduplica por `operation_id`..."""
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert aplicar_en_el_central(ops) == ["duplicate"]
    assert len(enviados) == 1


def test_la_misma_atencion_con_otro_operation_id_tampoco_manda_dos_veces(admin_client, nodo_apagado, enviados):
    """...y aunque llegara con otro `operation_id` (un reintento tras perder la respuesta), la `atencion_id` es la clave de
    idempotencia de LibraGenda y el envío es uno por turno."""
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    repetida = operacion_de("turno.atendido", ops[0].payload, secuencia=77, agregado="turno", id_local=ids["turno"])

    assert aplicar_en_el_central(ops + [repetida]) == ["accepted", "accepted"]
    assert len(enviados) == 1
    assert filas("SELECT intentos FROM envios_a_contalibra") == [(1,)]
    assert filas("SELECT count(*) FROM agenda_applied_attendances") == [(1,)]


def test_dos_entregas_a_la_vez_mandan_una_sola_vez(admin_client, nodo_apagado, enviados):
    """El central reclama la fila `pendiente` con un `UPDATE ... WHERE intentos = 0`: de dos hilos, uno solo manda."""
    from app.services import atencion_nodo

    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    # Aplica sin mandar (como si el proceso se hubiera ido después de confirmar) y manda desde dos hilos a la vez.
    original = atencion_nodo.enviar_pendiente
    atencion_nodo.enviar_pendiente = lambda turno_id: None
    try:
        aplicar_en_el_central(ops)
    finally:
        atencion_nodo.enviar_pendiente = original
    assert filas("SELECT estado, intentos FROM envios_a_contalibra") == [("pendiente", 0)]
    enviados.demora = 0.3

    hilos = [threading.Thread(target=original, args=(ids["turno"],)) for _ in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert len(enviados) == 1
    assert filas("SELECT estado, intentos FROM envios_a_contalibra") == [("enviado", 1)]


def test_si_el_proceso_murio_entre_confirmar_y_mandar_la_entrega_siguiente_lo_manda(admin_client, nodo_apagado, enviados):
    from app.services import atencion_nodo

    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    original = atencion_nodo.enviar_pendiente
    atencion_nodo.enviar_pendiente = lambda turno_id: None   # murió antes de mandar
    try:
        aplicar_en_el_central(ops)
    finally:
        atencion_nodo.enviar_pendiente = original
    assert enviados == []

    repetida = operacion_de("turno.atendido", ops[0].payload, secuencia=78, agregado="turno", id_local=ids["turno"])
    assert aplicar_en_el_central([repetida]) == ["accepted"]
    assert len(enviados) == 1 and filas("SELECT estado FROM envios_a_contalibra") == [("enviado",)]


def test_un_fallo_de_contalibra_no_rechaza_la_atencion_y_se_reintenta_desde_la_pantalla(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    enviados.falla = True

    assert aplicar_en_el_central(ops) == ["accepted"], "la atención ya ocurrió: un fallo de ContaLibra no la rechaza"
    assert _estado_del_turno(ids["turno"]) == "completed"
    fila = filas("SELECT estado, intentos, error, medio_del_saldo FROM envios_a_contalibra")[0]
    assert fila[0] == "error" and fila[1] == 1 and "502" in fila[2] and fila[3] == "efectivo"
    assert [e["estado"] for e in admin_client.get("/facturacion-externa", params={"solo_pendientes": True}).json()["envios"]] == [
        "error"]

    enviados.falla = False
    r = admin_client.post(f"/facturacion-externa/{ids['turno']}/reintentar")
    assert r.status_code == 200 and r.json()["estado"] == "enviado"
    assert len(enviados) == 1
    # el medio del saldo es un hecho del pasado: viaja el que se anotó en el nodo
    assert enviados[0]["pagos"][-1]["medio"] == "efectivo"


def test_sin_contalibra_configurado_queda_sin_destino_como_en_la_web(admin_client, nodo_apagado, monkeypatch):
    monkeypatch.delenv("CONTALIBRA_URL", raising=False)
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)

    assert aplicar_en_el_central(ops) == ["accepted"]
    fila = filas("SELECT estado, intentos, error FROM envios_a_contalibra")[0]
    assert fila[0] == "sin_destino" and fila[1] == 1 and "CONTALIBRA_URL" in fila[2]


def test_sin_precio_el_central_no_manda_nada(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client, precio=None)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert enviados == [] and filas("SELECT count(*) FROM envios_a_contalibra") == [(0,)]


def test_en_curso_no_manda_nada_y_completado_manda_una_vez(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    admin_client.post(f"/appointments/{ids['turno']}/start")
    admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"})
    ops = operaciones()
    nodo_apagado.apagar()

    assert aplicar_en_el_central(ops) == ["accepted", "accepted"]
    assert _estado_del_turno(ids["turno"]) == "completed"
    assert len(enviados) == 1


# ── Los conflictos con la web: a revisar, y lo cobrado se conserva ───────────────────────────────────────────────────


def test_un_turno_cancelado_en_la_web_queda_a_revisar_y_lo_cobrado_igual_se_manda(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    assert admin_client.post(f"/appointments/{ids['turno']}/cancel", json={"reason": "llamó"}).status_code == 200

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert _estado_del_turno(ids["turno"]) == "cancelled", "la atención no pisa lo que se decidió en la web"
    assert len(enviados) == 1, "lo cobrado se conserva siempre: sube a ContaLibra"

    a_revisar = admin_client.get("/turnos-a-revisar").json()
    assert len(a_revisar) == 1
    fila = a_revisar[0]
    assert fila["appointment_id"] == ids["turno"] and fila["motivo"] == "cancelado" and fila["estado"] == "completed"
    assert fila["paciente"] == "Ana Pérez" and fila["servicio"] == "Consulta" and fila["resultado"] == "a_revisar"
    assert fila["estado_despues"] == "cancelled"
    assert _agenda(admin_client, ids)[ids["turno"]]["a_revisar"] is True
    assert _agenda(admin_client, ids)[ids["turno"]]["motivo"] == "cancelado"

    r = admin_client.post("/turnos-a-revisar/revisadas", json={"atenciones": [fila["atencion_id"]]})
    assert r.status_code == 200 and r.json() == {"revisadas": 1}
    assert admin_client.get("/turnos-a-revisar").json() == []
    assert _agenda(admin_client, ids)[ids["turno"]]["a_revisar"] is False


def test_un_turno_movido_en_la_web_se_atiende_y_queda_a_revisar(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    assert admin_client.post(f"/appointments/{ids['turno']}/reschedule", json={"starts_at": "2099-01-01T15:00:00"}).status_code == 200

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert _estado_del_turno(ids["turno"]) == "completed"
    assert [f["motivo"] for f in admin_client.get("/turnos-a-revisar").json()] == ["movido"]
    assert len(enviados) == 1


def test_si_la_web_ya_lo_mando_no_sale_un_segundo_envio(admin_client, nodo_apagado, enviados):
    """El turno se completó (y se mandó) en la web mientras la PC lo atendía sin conexión: puede haberse cobrado dos veces.
    No sale un segundo envío —es uno por turno—, y queda a revisar para que lo mire una persona."""
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    assert admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"}).status_code == 200
    assert len(enviados) == 1

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert len(enviados) == 1, "el mismo turno no se manda dos veces"
    assert [f["motivo"] for f in admin_client.get("/turnos-a-revisar").json()] == ["ya_atendido"]


def test_marcar_revisada_es_del_central(admin_client, nodo_apagado, enviados):
    ids = sembrar_consultorio(admin_client)
    ops = _atender_y_subir(admin_client, nodo_apagado, ids)
    admin_client.post(f"/appointments/{ids['turno']}/cancel", json={})
    aplicar_en_el_central(ops)
    atencion = admin_client.get("/turnos-a-revisar").json()[0]["atencion_id"]

    nodo_apagado.prender()
    assert len(admin_client.get("/turnos-a-revisar").json()) == 1, "la lista se ve en la PC también"
    r = admin_client.post("/turnos-a-revisar/revisadas", json={"atenciones": [atencion]})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central"
    nodo_apagado.apagar()
    assert admin_client.post("/turnos-a-revisar/revisadas", json={"atenciones": ["no-existe"]}).status_code == 404


def test_una_atencion_mal_formada_va_a_revision_manual_y_no_se_pierde(admin_client, nodo_apagado):
    sembrar_consultorio(admin_client)
    mala = operacion_de("turno.atendido", {"version": 1, "atencion_id": "a" * 36, "turno_id": "x", "estado": "cancelled",
                                           "at": "2026-10-25T10:00:00+00:00"}, agregado="turno")
    resultado = aplicar_en_el_central([mala])[0]
    assert resultado.startswith("rejected")
    assert filas("SELECT status FROM sync_inbox WHERE operation_id = %s", (mala.operation_id,)) == [("manual_review",)]


def test_el_central_conoce_todas_las_operaciones_del_nodo():
    from app.routers.sincronizacion_offline import despachador

    assert set(despachador.tipos()) == {
        "turno.atendido", "paciente.alta", "nota.alta", "receta.alta", "pedido_estudio.alta", "consentimiento.alta",
        "walkin.registrado", "walkin.estado",
    }


def test_la_operacion_del_nodo_dice_de_que_nodo_viene(admin_client, nodo_apagado):
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    admin_client.post(f"/appointments/{ids['turno']}/start")
    op = operaciones()[0]
    assert op.node_id == NODO and op.operation_id.startswith(f"{NODO}:") and op.aggregate_id == f"{NODO}:turno:{ids['turno']}"
