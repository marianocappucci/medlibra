# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La matriz de roles de lo que el nodo suma, lo que el aprovisionamiento publica y lo que el nodo no hace (ADR-045).

MedLibra no tiene un archivo de matriz de roles: sus rutas declaran el rol en cada router. Lo que este PR monta se fija acá,
**escrito a mano** (no se deriva del código, o no se pondría rojo nunca):

| Rutas | Quién entra |
|---|---|
| `libraedge.sync.api.RUTAS_AUTENTICADAS_POR_NODO` (`/sync/v1/push`, `pull`, `ticket-arca`, `carga-inicial`, `estado-operaciones`) | PÚBLICA, secreto del nodo: ni sesión ni rol |
| `POST /sync/v1/vinculacion` (el canje del código) | PÚBLICA: la llama el instalador |
| `/api/nodos-offline*` («Sucursal sin internet») | ADMIN |
| `GET /turnos-a-revisar` | STAFF |
| `POST /turnos-a-revisar/revisadas` | STAFF, y sólo en el central |
| `POST /appointments/{id}/start`, `/no-show` | STAFF |
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from nodo_apoyo import (
    NODO,
    ejecutar,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    sembrar_consultorio,
)

from app import offline

#: Lo que NO se espeja, cada tabla con su motivo. La suma de esto y de `TABLAS_DE_REFERENCIA` tiene que ser TODA tabla de la
#: base migrada: una tabla nueva que nadie decidió, rompe acá.
EXCLUIDAS = {
    "agenda_node_attendances": "la atención del nodo sube como turno.atendido; el central no la necesita y es del nodo",
    "patient_sequences": "el contador del p-NNN es del central: el nodo da ids provisorios",
    "sent_reminders": "los recordatorios los manda el central (simulados): el nodo no recuerda nada",
    "actividad_log": "el log de actividad es de cada punta (nodo y central llevan el suyo)",
    "auth_log": "el log de accesos es de cada punta",
    "secretos_instancia": "el almacén de claves cifradas (MercadoPago, SMTP) es del central: la clave no sale del VPS",
    "smtp_settings": "la configuración del correo es del central: el nodo no manda mails",
    "avisos_envios": "el registro de avisos es del central: el nodo no manda avisos (libracore ADR-090)",
    "envios_a_libraview": "la costura con LibraView es del central (ADR-050): el envío y el aviso sólo existen allá; el nodo no la espeja",
    "estudios_en_libraview": "idem: el número de acceso de cada ítem lo guarda y lo usa el central",
    "eventos_de_libraview": "idem: la deduplicación de los avisos del webhook es del central",
    "demo_codigos": "los códigos de la demo son del central",
    "password_reset_tokens": "la recuperación de contraseña es del central",
    "libraauth_captcha_usados": "el anti-replay del captcha es de cada punta (el nodo no pide captcha, libraauth ADR-028)",
    "alembic_version": "la versión de la cadena del motor es de cada punta (la compara version_de_alembic)",
    "alembic_version_libragenda": "idem",
    "alembic_version_libraauth": "idem",
    "alembic_version_medlibra": "idem",
    # LibraEdge: las tablas del propio nodo y del central.
    "sync_outbox": "es del nodo", "sync_inbox": "es del central", "sync_changelog": "es del central",
    "node_identity": "es del central", "local_sequences": "es del nodo", "libraedge_canje_fallido": "es del central",
    "libraedge_vinculacion": "es del central",
    "libraedge_mapeo": "lo agrega el aprovisionamiento solo, porque hay altas en el nodo",
    "libraedge_mapeo_texto": "idem (ids de texto, libraedge ADR-026)",
}

#: Todo LibraCore: MedLibra no factura, no tiene caja ni ventas (manda la consulta a ContaLibra, ADR-035 y ADR-036).
DE_LIBRACORE = {
    "arca_config", "arca_credenciales_servicio", "caja_movimientos", "cajas", "categorias_egreso", "categorias_producto",
    "cc_asientos", "cc_debitos", "cc_pagos", "cierres_diarios", "cierres_diarios_medios", "cierres_diarios_turnos",
    "clients", "cola_arca", "comprobantes_pendientes", "cuentas_tesoreria", "depositos", "egresos", "egresos_pagos",
    "envios_email", "facturacion_alias", "facturas", "indices_ajuste", "lista_precio_items", "listas_precio", "modulos",
    "movimientos_stock", "movimientos_tesoreria", "mp_movimientos", "mp_pagos", "presupuestos", "productos",
    "proveedores", "recibos", "reintegros_pendientes", "remitos", "turnos_caja", "ventas", "ventas_pagos",
}


def _tablas_de_la_base() -> set[str]:
    return {f[0] for f in filas("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}


# ── Qué se espeja ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_toda_tabla_de_la_base_decidio_su_lugar(admin_client):
    """Una tabla nueva (de una migración de MedLibra o de un motor) tiene que decidir si el nodo la espeja o no. Sin esto,
    la que se olvida deja un agujero en el espejo que recién se ve en el consultorio."""
    decididas = set(offline.TABLAS_DE_REFERENCIA) | set(EXCLUIDAS) | DE_LIBRACORE
    assert _tablas_de_la_base() - decididas == set(), "tablas nuevas sin decidir"
    assert decididas - _tablas_de_la_base() - {"libraedge_mapeo", "libraedge_mapeo_texto"} == set(), "tablas que ya no existen"
    assert set(offline.TABLAS_DE_REFERENCIA) & (set(EXCLUIDAS) | DE_LIBRACORE) == set()


def test_el_aprovisionamiento_no_espeja_lo_excluido():
    espejadas = offline.aprovisionamiento.nombres - {"libraedge_mapeo", "libraedge_mapeo_texto"}
    assert espejadas & (set(EXCLUIDAS) | DE_LIBRACORE) == set()


def test_el_aprovisionamiento_espeja_lo_que_el_nodo_necesita_para_atender():
    necesarias = {"usuarios", "branches", "resources", "services", "appointments", "agenda_clients", "patients", "deposits",
                  "service_prices", "resource_service_prices", "medlibra_modulos", "clinical_notes", "prescriptions",
                  "study_orders", "consents", "clinical_documents", "walkins", "agenda_blocks", "consultorios",
                  "agenda_applied_attendances"}
    assert necesarias <= offline.aprovisionamiento.nombres


def test_los_pacientes_se_dan_de_alta_en_el_nodo_con_id_de_texto():
    """`agenda_clients` y `patients` son dos altas (`patients.id` es clave primaria y foránea a la vez) de ids de texto:
    suman el mapeo de texto al espejo. Lo que las referencia lo encuentra LibraEdge en el catálogo, sin referencias a mano."""
    altas = {a.tabla: a for a in offline.aprovisionamiento.altas}
    assert set(altas) == {"agenda_clients", "patients"}
    assert all(a.id_de_texto and a.referencias == () for a in altas.values())
    assert {"libraedge_mapeo", "libraedge_mapeo_texto"} <= offline.aprovisionamiento.nombres
    assert {"libraedge_mapeo", "libraedge_mapeo_texto"} <= offline.aprovisionamiento.solo_lectura


def test_los_maestros_y_los_turnos_son_de_solo_lectura_y_lo_que_el_nodo_carga_no():
    solo_lectura = offline.aprovisionamiento.solo_lectura
    assert {"appointments", "branches", "resources", "services", "service_prices", "medlibra_modulos", "patients",
            "agenda_clients", "agenda_applied_attendances", "deposits"} <= solo_lectura
    # lo que el nodo escribe: sus notas, recetas, estudios, consentimientos y llegadas (con uuid propio), y el espejo del usuario
    escribe = {"clinical_notes", "prescriptions", "prescription_items", "study_orders", "study_order_items", "consents",
               "walkins", "usuarios", "aceptaciones_terminos"}
    assert not (escribe & solo_lectura)


def test_toda_tabla_de_referencia_existe_y_se_puede_publicar(admin_client):
    """Un nombre mal escrito, o una tabla sin clave primaria, deja un agujero en el espejo que recién se ve en el consultorio."""
    from libracore.db import core as libracore_core
    from libraedge.aprovisionamiento import plan_de_publicacion

    with libracore_core.get_connection() as conn:
        plan = plan_de_publicacion(conn, offline.aprovisionamiento)
    assert plan.faltantes == () and plan.salteadas == ()
    publicadas = dict(plan.publicables)
    assert publicadas["patients"] == ("id",) and "libraedge_mapeo_texto" in publicadas


def test_se_puede_registrar_un_nodo_de_una_sede(admin_client, nodo_apagado):
    """El alta de punta a punta: las sedes salen de `branches`, y las altas en el nodo se publican con su mapeo de texto."""
    from libracore.db import core as libracore_core
    from libraedge.aprovisionamiento import registrar

    sembrar_consultorio(admin_client)
    with libracore_core.get_connection() as conn:
        alta = registrar(conn, offline.aprovisionamiento, NODO, "branch-1", salida=lambda *_: None)
    assert alta.sucursal.nombre == "Consultorio demo"
    assert "libraedge_mapeo_texto" in alta.espejo and "patients" in alta.espejo and "clinical_notes" in alta.espejo
    assert "clinical_notes" not in alta.solo_lectura and "patients" in alta.solo_lectura
    assert set(alta.solo_lectura) >= {"appointments", "branches"}


def test_las_sedes_de_un_nodo_son_las_branches_de_libragenda(admin_client):
    from libracore.db import core as libracore_core

    sembrar_consultorio(admin_client)
    with libracore_core.get_connection() as conn:
        assert offline.listar_sucursales(conn) == [{"id": "branch-1", "nombre": "Consultorio demo", "activa": True}]


# ── Las migraciones ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_la_cadena_de_migraciones_crea_las_tablas_de_libraedge_y_tiene_una_sola_cabeza(admin_client):
    """El central las necesita aunque no tenga nodos (`node_identity` para autenticarlos, `sync_inbox` para deduplicar,
    `libraedge_mapeo_texto` para los pacientes). Y una sola cabeza: dos PR que agregan una revisión se pisan."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = AlembicConfig(os.path.join(raiz, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(raiz, "migrations"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    for tabla in ("node_identity", "sync_inbox", "sync_outbox", "libraedge_mapeo", "libraedge_mapeo_texto",
                  "sync_changelog", "agenda_node_attendances", "agenda_applied_attendances"):
        assert filas("SELECT to_regclass(%s)", (f"public.{tabla}",)) == [(tabla,)], tabla


# ── Las rutas del nodo ───────────────────────────────────────────────────────────────────────────────────────────────

#: Un pedido bien formado para cada ruta del nodo: el 422 de un cuerpo mal armado llega antes que el 401 del secreto.
PEDIDOS_DEL_NODO = {
    ("POST", "/sync/v1/push"): {"json": {
        "operation_id": "x:1", "node_id": "x", "sequence": 1, "operation_type": "nota.alta",
        "aggregate_type": "nota", "aggregate_id": "x:nota:1", "occurred_at": "2026-10-25T00:00:00+00:00",
        "schema_version": 1, "payload": {}}},
    ("GET", "/sync/v1/pull"): {"params": {"node_id": "x"}},
    ("POST", "/sync/v1/ticket-arca"): {"json": {"node_id": "x"}},
    ("GET", "/sync/v1/carga-inicial"): {"params": {"node_id": "x"}},
    ("POST", "/sync/v1/estado-operaciones"): {"json": {"node_id": "x", "operation_ids": ["x:1"]}},
}


@pytest.fixture
def clientes(staff_client):
    admin = staff_client  # `staff_client` arrastra a `admin_client`: la misma app
    return {"anonimo": TestClient(admin.app, base_url="https://medlibra.test"), "staff": staff_client}


def test_los_pedidos_de_la_matriz_son_las_rutas_del_nodo():
    from libraedge.sync.api import RUTAS_AUTENTICADAS_POR_NODO

    assert set(PEDIDOS_DEL_NODO) == set(RUTAS_AUTENTICADAS_POR_NODO)


@pytest.mark.parametrize(("metodo", "ruta"), sorted(PEDIDOS_DEL_NODO))
def test_las_rutas_del_nodo_piden_el_secreto_y_no_la_sesion(admin_client, clientes, metodo, ruta):
    """Sin un nodo registrado no existe ningún secreto válido: 401 a todos, también al admin con sesión. Si alguien las
    montara detrás de un rol, el nodo (que no tiene sesión) no podría sincronizar; si las abriera, cualquiera empujaría
    operaciones al central."""
    for quien, cliente in {**clientes, "admin": admin_client}.items():
        r = cliente.request(metodo, ruta, **PEDIDOS_DEL_NODO[(metodo, ruta)])
        assert r.status_code == 401, (quien, metodo, ruta, r.status_code, r.text)


def test_el_canje_del_codigo_es_publico(admin_client, clientes, monkeypatch):
    """Lo llama el instalador, sin sesión: lo protegen el código (un solo uso) y el límite de intentos. Un código que no
    sirve es 404, y no un 401/403 de rol."""
    monkeypatch.setenv("LIBRAEDGE_CENTRAL_URL", "https://medlibra.example.com")
    for quien, cliente in {**clientes, "admin": admin_client}.items():
        r = cliente.post("/sync/v1/vinculacion", json={"codigo": "AAAA-BBBB", "producto": "medlibra"})
        assert r.status_code == 404, (quien, r.status_code, r.text)


@pytest.mark.parametrize(("metodo", "ruta"), [
    ("GET", "/api/nodos-offline"),
    ("GET", "/api/nodos-offline/menu"),
    ("POST", "/api/nodos-offline"),
    ("POST", "/api/nodos-offline/vinculacion"),
    ("POST", "/api/nodos-offline/inexistente/vinculacion"),
    ("DELETE", "/api/nodos-offline/inexistente/vinculacion"),
    ("POST", "/api/nodos-offline/inexistente/carga"),
    ("DELETE", "/api/nodos-offline/inexistente"),
])
def test_alta_y_baja_de_nodos_es_del_admin(admin_client, clientes, metodo, ruta):
    llamar = lambda c: c.request(metodo, ruta, json={} if metodo != "GET" else None)  # noqa: E731
    assert llamar(clientes["anonimo"]).status_code == 401, ruta
    assert llamar(clientes["staff"]).status_code == 403, ruta
    assert llamar(admin_client).status_code not in (401, 403), ruta


def test_el_admin_ve_la_pantalla_de_sucursal_sin_internet(admin_client):
    sembrar_consultorio(admin_client)
    assert admin_client.get("/api/nodos-offline").status_code == 200


def test_toda_ruta_del_nodo_tiene_una_fila_en_esta_matriz(admin_client):
    """Una ruta nueva de sincronización o de nodo que nadie decidió quién entra, falla acá."""
    from libraedge.sync.api import RUTAS_AUTENTICADAS_POR_NODO

    decididas = {ruta for _, ruta in RUTAS_AUTENTICADAS_POR_NODO} | {
        "/sync/v1/vinculacion", "/sync/v1/salud", "/sync/v1/salud/{node_id}",
        "/api/nodos-offline", "/api/nodos-offline/menu", "/api/nodos-offline/vinculacion",
        "/api/nodos-offline/{node_id}/vinculacion", "/api/nodos-offline/{node_id}/carga", "/api/nodos-offline/{node_id}",
    }
    montadas = {ruta for ruta in admin_client.app.openapi()["paths"] if ruta.startswith(("/sync/", "/api/nodos-offline"))}
    assert montadas - decididas == set(), f"rutas del nodo sin decidir: {sorted(montadas - decididas)}"
    assert decididas - montadas == set(), f"filas de la matriz que ya no existen: {sorted(decididas - montadas)}"


def test_los_turnos_a_revisar_y_atender_son_del_staff(admin_client, clientes):
    ids = sembrar_consultorio(admin_client)
    for metodo, ruta in (("GET", "/turnos-a-revisar"), ("POST", f"/appointments/{ids['turno']}/start"),
                         ("POST", "/turnos-a-revisar/revisadas")):
        cuerpo = {"atenciones": []} if ruta.endswith("revisadas") else None
        assert clientes["anonimo"].request(metodo, ruta, json=cuerpo).status_code == 401, ruta
        assert clientes["staff"].request(metodo, ruta, json=cuerpo).status_code == 200, ruta


# ── Lo que el nodo no hace: 409 `solo_en_el_central` ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), [
    ("POST", "/branches", {"id": "otra", "name": "Otra sede"}),
    ("POST", "/resources", {"id": "r2", "name": "Dr. Otro", "branch_id": "branch-1"}),
    ("POST", "/services", {"id": "s2", "name": "Otra", "duration_minutes": 15}),
    ("PUT", "/services/service-1/prices", {"branch_id": "branch-1", "price": "1500"}),
    ("POST", "/consultorios", {"id": "c1", "name": "Sala", "branch_id": "branch-1"}),
    ("POST", "/resources/resource-1/availability", {"weekday": 0, "starts_at": "09:00:00", "ends_at": "10:00:00"}),
    ("POST", "/facturacion-externa/turno-x/reintentar", None),
    # las señas y los recordatorios (los cobra MercadoPago o se transfiere, y los manda el central): no se tocan en la PC
    ("POST", "/appointments/{t}/deposit", {"amount": "400.00"}),
    ("POST", "/deposits/inexistente/mark-paid", {"medio_pago": "efectivo"}),
    ("POST", "/deposits/inexistente/refund", {}),
    ("POST", "/reminders/dispatch", None),
    # la configuración de avisos (la apikey de Evolution vive en el central) y la prueba de envío: el router del motor lo resuelve solo
    ("PUT", "/api/avisos/config", {"modo": "registro"}),
    ("POST", "/api/avisos/probar", {"canal": "whatsapp", "destino": "11 5555-1234"}),
])
def test_en_un_nodo_lo_que_manda_el_central_se_contesta_409(admin_client, nodo_apagado, metodo, ruta, cuerpo):
    """Los maestros, los precios, la configuración y el reintento a ContaLibra no se escriben en el nodo: su espejo los pisaría
    (o ni siquiera tiene el token)."""
    ids = sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    r = admin_client.request(metodo, ruta.format(t=ids["turno"]), json=cuerpo)
    assert r.status_code == 409, (ruta, r.status_code, r.text)
    assert r.json()["detail"]["codigo"] == "solo_en_el_central"


def test_en_un_nodo_los_maestros_se_leen(admin_client, nodo_apagado):
    sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    for ruta in ("/branches", "/resources", "/services", "/facturacion-externa", "/agenda/catalogo", "/patients"):
        assert admin_client.get(ruta).status_code == 200, ruta


def test_fuera_de_un_nodo_esos_mismos_pedidos_andan(admin_client, nodo_apagado):
    sembrar_consultorio(admin_client)
    assert admin_client.post("/branches", json={"id": "otra", "name": "Otra sede"}).status_code == 201
    assert admin_client.put("/services/service-1/prices", json={"branch_id": "branch-1", "price": "1500"}).status_code == 200


def test_la_barra_del_pie_dice_si_la_pc_ve_al_central(admin_client, nodo_apagado):
    sembrar_consultorio(admin_client)
    nodo_apagado.prender()
    sin = admin_client.get("/api/estado-del-sistema")
    assert sin.status_code == 200, sin.text
    nodo_apagado.en_linea(True)
    con = admin_client.get("/api/estado-del-sistema")
    assert con.json() != sin.json(), "la barra distingue una PC en línea de una sin conexión"


# ── El arranque de un nodo ───────────────────────────────────────────────────────────────────────────────────────────


def test_un_nodo_no_siembra_los_modulos_los_trae_del_central(admin_client, nodo_apagado):
    """`medlibra_modulos` es del espejo (de sólo lectura en el nodo): sembrarla antes de la primera bajada chocaría con la
    guarda de la base. Sin fila, los módulos de plan están habilitados y los add-ons apagados: lo mismo que el central."""
    ejecutar("DELETE FROM medlibra_modulos")
    modulos = admin_client.app.state.modules
    nodo_apagado.prender()
    modulos.ensure_seeded()
    assert filas("SELECT count(*) FROM medlibra_modulos") == [(0,)]
    assert modulos.is_enabled("facturacion") is True and modulos.is_enabled("resguardo_externo") is False
    nodo_apagado.apagar()
    modulos.ensure_seeded()
    assert filas("SELECT count(*) FROM medlibra_modulos")[0][0] > 0


def test_la_app_arranca_siendo_un_nodo(admin_client, nodo_apagado):
    """`create_app()` con `LIBRAEDGE_NODE_ID` puesta (lo que ve el proceso de la PC): sin sembrar módulos ni romper."""
    from motor_de_test import fresh_database_url

    from app.main import create_app

    nodo_apagado.prender()
    app = create_app(fresh_database_url())
    try:
        with TestClient(app, base_url="https://medlibra.test") as c:
            assert c.get("/health").status_code == 200
    finally:
        app.state.auth_engine.dispose()


# ── De punta a punta por HTTP: el nodo registrado empuja al central ──────────────────────────────────────────────────


def _registrar_un_nodo(client) -> str:
    """Registra el nodo de la sede y devuelve su secreto (lo que el instalador guarda en el archivo de entorno de la PC)."""
    from libracore.db import core as libracore_core
    from libraedge.aprovisionamiento import registrar

    with libracore_core.get_connection() as conn:
        alta = registrar(conn, offline.aprovisionamiento, NODO, "branch-1", salida=lambda *_: None)
        conn.commit()
    # Lo que el instalador necesita de MedLibra, tal como lo arma LibraEdge: se lo fija para que el PR 12 parta de acá.
    entorno = dict(linea.split("=", 1) for linea in alta.entorno_del_nodo())
    # `LIBRAEDGE_PREFIJO` es el prefijo de numeración que el central asigna a la sede (no el del producto): MedLibra no numera nada.
    assert entorno["LIBRAEDGE_NODE_ID"] == NODO and entorno["LIBRAEDGE_PREFIJO"]
    assert "patients" in entorno["LIBRAEDGE_TABLAS_ESPEJO"] and "libraedge_mapeo_texto" in entorno["LIBRAEDGE_TABLAS_ESPEJO"]
    assert entorno["LIBRAEDGE_ALTAS_EN_NODO"] == "agenda_clients,patients"
    assert "appointments" in entorno["LIBRAEDGE_TABLAS_SOLO_LECTURA"]
    assert "clinical_notes" not in entorno["LIBRAEDGE_TABLAS_SOLO_LECTURA"]
    return alta.secreto


def _esquema_del_central() -> dict[str, str]:
    """La cabecera con la que el nodo dice en qué esquema está (el central contesta 409 si no coincide con el suyo)."""
    from libracore.db import core as libracore_core
    from libraedge.sync.esquema import CABECERA, version_de_alembic

    with libracore_core.get_connection() as conn:
        return {CABECERA: version_de_alembic(conn)}


def _push(client, secreto: str, operacion) -> dict:
    r = client.post("/sync/v1/push", json=operacion.como_dict(), headers={
        "Authorization": f"Bearer {secreto}", **_esquema_del_central()})
    assert r.status_code == 200, r.text
    return r.json()


def test_el_nodo_registrado_empuja_sus_operaciones_por_http_y_el_central_las_aplica(admin_client, nodo_apagado, monkeypatch):
    """Lo que ninguna prueba de las piezas mide: la ruta `/sync/v1/push` montada en la app, con el secreto del nodo, el control de
    la versión del esquema y el despachador de MedLibra. Un paciente, su nota y un turno atendido, de una PC a la web."""
    from nodo_apoyo import borrar_filas, operaciones

    monkeypatch.setenv("CONTALIBRA_URL", "")   # sin destino: queda `sin_destino`, y no sale a la red
    ids = sembrar_consultorio(admin_client)
    secreto = _registrar_un_nodo(admin_client)
    nodo_apagado.prender()
    paciente = admin_client.post("/patients", json={"name": "Nuevo Paciente", "dni": "33444555"}).json()["id"]
    nota = admin_client.post(f"/patients/{paciente}/notes", json={"author": "Dra. Vidal", "text": "Primera consulta"}).json()
    assert admin_client.post(f"/appointments/{ids['turno']}/complete", json={"medio_pago": "efectivo"}).status_code == 200
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("clinical_notes", [nota["id"]])
    borrar_filas("patients", [paciente])
    borrar_filas("agenda_clients", [paciente])

    assert [op.operation_type for op in ops] == ["paciente.alta", "nota.alta", "turno.atendido"]
    assert [_push(admin_client, secreto, op)["result"] for op in ops] == ["accepted"] * 3
    assert filas("SELECT patient_id FROM clinical_notes WHERE id = %s", (nota["id"],)) == [("p-001",)]
    assert filas("SELECT status FROM appointments WHERE id = %s", (ids["turno"],)) == [("completed",)]
    assert filas("SELECT estado FROM envios_a_contalibra") == [("sin_destino",)]
    # el mismo push otra vez: el central lo reconoce
    assert _push(admin_client, secreto, ops[0])["result"] == "duplicate"


def test_un_esquema_distinto_al_del_central_se_rechaza_con_409(admin_client, nodo_apagado):
    """Un nodo que no migró igual que el central no empuja: sus operaciones esperan en el outbox."""
    sembrar_consultorio(admin_client)
    secreto = _registrar_un_nodo(admin_client)
    r = admin_client.post("/sync/v1/push", headers={"Authorization": f"Bearer {secreto}", "X-LibraEdge-Esquema": "viejo"}, json={
        "operation_id": f"{NODO}:1", "node_id": NODO, "sequence": 1, "operation_type": "nota.alta", "aggregate_type": "nota",
        "aggregate_id": f"{NODO}:nota:1", "occurred_at": "2026-10-25T00:00:00+00:00", "schema_version": 1, "payload": {}})
    assert r.status_code == 409, r.text


def test_una_operacion_que_el_central_no_conoce_va_a_revision_y_no_se_marca_aplicada(admin_client, nodo_apagado):
    from nodo_apoyo import operacion_de

    sembrar_consultorio(admin_client)
    secreto = _registrar_un_nodo(admin_client)
    r = _push(admin_client, secreto, operacion_de("venta.registrada", {}, agregado="venta"))
    assert r["result"] == "rejected" and "sin manejador" in r["error"]


def test_medlibra_no_presta_el_ticket_de_arca(admin_client, nodo_apagado):
    """MedLibra no factura (ADR-036): el nodo no pide el ticket y el central no lo presta. 501 después de autenticar."""
    sembrar_consultorio(admin_client)
    secreto = _registrar_un_nodo(admin_client)
    r = admin_client.post("/sync/v1/ticket-arca", json={"node_id": NODO}, headers={
        "Authorization": f"Bearer {secreto}", **_esquema_del_central()})
    assert r.status_code == 501, r.text


def test_el_cartel_de_conexion_distingue_la_pc_del_central(admin_client, nodo_apagado):
    assert admin_client.get("/api/nodo/conexion").json() == {
        "es_nodo": False, "en_linea": True, "node_id": None, "a_facturar": 0}
    nodo_apagado.prender()
    assert admin_client.get("/api/nodo/conexion").json() == {
        "es_nodo": True, "en_linea": False, "node_id": NODO, "a_facturar": 0}
    nodo_apagado.en_linea(True)
    assert admin_client.get("/api/nodo/conexion").json()["en_linea"] is True


def test_el_cartel_pide_sesion(admin_client, nodo_apagado):
    anonimo = TestClient(admin_client.app, base_url="https://medlibra.test")
    assert anonimo.get("/api/nodo/conexion").status_code == 401
