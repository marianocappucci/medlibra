# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""La historia clínica que se carga sin conexión: notas, recetas, pedidos de estudio y consentimientos (ADR-045).

Decisión del humano (2026-10-25): *se cargan sin conexión*. Son altas, no ediciones, con un uuid propio: el central crea la
misma fila con el mismo id. Y *los documentos adjuntos se ven sólo con internet*: 409.

Lo que se fija acá:

- cada alta sube como su operación **en la misma transacción** que la fila, y fuera de un nodo no encola nada;
- el central la crea **con el mismo id**, una sola vez (aunque la operación llegue dos veces), con sus ítems;
- lo que no se hace en la PC (borrar historia clínica, cargar el resultado de un estudio, subir o ver un archivo) es 409.
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
    sembrar_consultorio,
    tipos_encolados,
)

#: Cada tipo de alta clínica: la ruta, el cuerpo, la operación que sube y las tablas de la fila y sus hijas.
ALTAS = {
    "nota": {
        "ruta": "/patients/patient-1/notes", "cuerpo": {"author": "Dra. Vidal", "text": "Dolor lumbar de 3 días"},
        "tipo": "nota.alta", "tabla": "clinical_notes", "hijas": [],
    },
    "receta": {
        "ruta": "/patients/patient-1/prescriptions",
        "cuerpo": {"author": "Dra. Vidal", "items": [
            {"medication": "Ibuprofeno 400", "dosage": "1 cada 8 hs", "instructions": "con comida"},
            {"medication": "Omeprazol 20", "dosage": "1 por día"},
        ]},
        "tipo": "receta.alta", "tabla": "prescriptions", "hijas": [("prescription_items", "prescription_id")],
    },
    "pedido": {
        "ruta": "/patients/patient-1/study-orders",
        "cuerpo": {"author": "Dra. Vidal", "items": [
            {"study_type": "Análisis de sangre", "reason": "control"}, {"study_type": "Radiografía de tórax"}]},
        "tipo": "pedido_estudio.alta", "tabla": "study_orders", "hijas": [("study_order_items", "order_id")],
    },
    "consentimiento": {
        "ruta": "/patients/patient-1/consents",
        "cuerpo": {"author": "Dra. Vidal", "procedure": "Infiltración", "granted_by": "la paciente",
                   "text": "Se explicaron riesgos y alternativas."},
        "tipo": "consentimiento.alta", "tabla": "consents", "hijas": [],
    },
}


@pytest.fixture
def consultorio(admin_client):
    return sembrar_consultorio(admin_client)   # paciente `patient-1`


def _cargar(client, clave: str) -> dict:
    r = client.post(ALTAS[clave]["ruta"], json=ALTAS[clave]["cuerpo"])
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("clave", list(ALTAS))
def test_cargar_en_el_nodo_deja_la_fila_con_su_uuid_y_la_operacion(admin_client, consultorio, nodo, clave):
    alta = ALTAS[clave]
    creada = _cargar(admin_client, clave)

    assert filas(f"SELECT count(*) FROM {alta['tabla']} WHERE id = %s", (creada["id"],)) == [(1,)]
    assert len(creada["id"]) == 36, "el id es un uuid: el nodo y el central no pueden dar el mismo"
    assert tipos_encolados() == [alta["tipo"]]
    op = operaciones()[0]
    assert op.payload["id"] == creada["id"] and op.payload["fila"]["patient_id"] == "patient-1"
    # Una hora con huso (cualquiera: la sesión de PostgreSQL del CI está en el de Argentina), no una ingenua.
    assert datetime.fromisoformat(op.payload["fila"]["created_at"]).utcoffset() is not None
    for tabla, _ in alta["hijas"]:
        assert len(op.payload["hijas"][tabla]) == 2


@pytest.mark.parametrize("clave", list(ALTAS))
def test_fuera_de_un_nodo_no_se_encola_nada(admin_client, consultorio, nodo_apagado, clave):
    _cargar(admin_client, clave)
    assert tipos_encolados() == []


@pytest.mark.parametrize("clave", list(ALTAS))
def test_la_fila_y_su_operacion_son_una_sola_transaccion(admin_client, consultorio, nodo, monkeypatch, clave):
    from app import offline

    def falla(*args, **kwargs):
        raise RuntimeError("el outbox no anda")

    monkeypatch.setattr(offline, "encolar_operacion", falla)
    with pytest.raises(RuntimeError):
        admin_client.post(ALTAS[clave]["ruta"], json=ALTAS[clave]["cuerpo"])
    assert filas(f"SELECT count(*) FROM {ALTAS[clave]['tabla']}") == [(0,)]


@pytest.mark.parametrize("clave", list(ALTAS))
def test_el_central_crea_la_misma_fila_con_el_mismo_id_y_una_sola_vez(admin_client, consultorio, nodo_apagado, clave):
    alta = ALTAS[clave]
    nodo_apagado.prender()
    creada = _cargar(admin_client, clave)
    ops = operaciones()
    nodo_apagado.apagar()
    antes = filas(f"SELECT * FROM {alta['tabla']} WHERE id = %s", (creada["id"],))
    hijas_antes = {t: filas(f"SELECT * FROM {t} ORDER BY position") for t, _ in alta["hijas"]}
    # en el central no existe hasta que sube
    for tabla, _ in alta["hijas"]:
        filas_hijas = filas(f"SELECT id FROM {tabla}")
        borrar_filas(tabla, [f[0] for f in filas_hijas])
    borrar_filas(alta["tabla"], [creada["id"]])

    repetida = operacion_de(alta["tipo"], ops[0].payload, secuencia=60, agregado=clave, id_local=creada["id"])
    assert aplicar_en_el_central(ops + ops + [repetida]) == ["accepted", "duplicate", "accepted"]

    assert filas(f"SELECT * FROM {alta['tabla']} WHERE id = %s", (creada["id"],)) == antes, "idéntica, hasta el instante"
    for tabla, columna in alta["hijas"]:
        assert filas(f"SELECT * FROM {tabla} ORDER BY position") == hijas_antes[tabla]
        assert filas(f"SELECT DISTINCT {columna} FROM {tabla}") == [(creada["id"],)]


def test_el_central_rechaza_una_nota_de_un_paciente_que_no_existe(admin_client, consultorio, nodo_apagado):
    nodo_apagado.prender()
    creada = _cargar(admin_client, "nota")
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("clinical_notes", [creada["id"]])
    borrar_filas("patients", ["patient-1"])

    resultado = aplicar_en_el_central(ops)[0]
    assert resultado.startswith("rejected") and "no existe en el central" in resultado
    assert filas("SELECT count(*) FROM clinical_notes") == [(0,)]


@pytest.mark.parametrize(("clave", "cambio", "motivo"), [
    ("nota", {"fila": {"text": ""}}, "text"),
    ("nota", {"fila": {"author": "x" * 201}}, "200"),
    ("nota", {"fila": {"created_at": "2026-10-25T10:00:00"}}, "zona"),
    ("nota", {"fila": {"created_at": "ayer"}}, "ISO 8601"),
    ("nota", {"version": 2}, "versión"),
    ("nota", {"fila": None}, "no trae sus datos"),
    ("receta", {"hijas": {}}, "prescription_items"),
    ("receta", {"hijas": {"prescription_items": []}}, "prescription_items"),
    ("pedido", {"hijas": {"study_order_items": [{"id": "i", "position": "0", "study_type": "x", "reason": None}]}}, "entero"),
    ("consentimiento", {"fila": {"procedure": None}}, "procedure"),
])
def test_una_alta_mal_formada_va_a_revision_manual_y_no_deja_nada(admin_client, consultorio, nodo_apagado, clave, cambio, motivo):
    alta = ALTAS[clave]
    nodo_apagado.prender()
    creada = _cargar(admin_client, clave)
    op = operaciones()[0]
    nodo_apagado.apagar()
    for tabla, _ in alta["hijas"]:
        borrar_filas(tabla, [f[0] for f in filas(f"SELECT id FROM {tabla}")])
    borrar_filas(alta["tabla"], [creada["id"]])
    payload = dict(op.payload)
    for campo, valor in cambio.items():
        payload[campo] = {**payload[campo], **valor} if isinstance(valor, dict) and valor and isinstance(payload.get(campo), dict) else valor

    resultado = aplicar_en_el_central([operacion_de(alta["tipo"], payload, secuencia=5, agregado=clave)])[0]
    assert resultado.startswith("rejected") and motivo in resultado, resultado
    assert filas(f"SELECT count(*) FROM {alta['tabla']}") == [(0,)]


# ── Lo que el nodo no hace con la historia clínica ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("clave", list(ALTAS))
def test_borrar_historia_clinica_es_del_central(admin_client, consultorio, nodo_apagado, clave):
    alta = ALTAS[clave]
    creada = _cargar(admin_client, clave)
    nodo_apagado.prender()

    r = admin_client.delete(f"{alta['ruta']}/{creada['id']}")
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central"
    assert filas(f"SELECT count(*) FROM {alta['tabla']}") == [(1,)]
    nodo_apagado.apagar()
    assert admin_client.delete(f"{alta['ruta']}/{creada['id']}").status_code == 204


def test_la_guarda_de_rol_va_antes_que_el_409(staff_client, nodo_apagado):
    """Quien no es admin recibe su 403 y no se entera de si el servidor es un nodo."""
    staff_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    creada = staff_client.post("/patients/patient-1/notes", json={"author": "a", "text": "t"}).json()
    nodo_apagado.prender()
    assert staff_client.delete(f"/patients/patient-1/notes/{creada['id']}").status_code == 403


def test_el_resultado_de_un_estudio_se_carga_desde_la_web(admin_client, consultorio, nodo_apagado):
    pedido = _cargar(admin_client, "pedido")
    item = pedido["items"][0]["id"]
    nodo_apagado.prender()
    r = admin_client.post(f"/patients/patient-1/study-orders/{pedido['id']}/items/{item}/results",
                          json={"author": "Lab", "text": "Normal"})
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "sin_conexion")
    nodo_apagado.en_linea(True)
    r = admin_client.post(f"/patients/patient-1/study-orders/{pedido['id']}/items/{item}/results",
                          json={"author": "Lab", "text": "Normal"})
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "solo_en_el_central")
    assert filas("SELECT count(*) FROM study_results") == [(0,)]
    assert tipos_encolados() == []


def _subir(client):
    return client.post("/patients/patient-1/documents", data={"author": "Dra. Vidal", "title": "Informe"},
                       files={"file": ("informe.pdf", b"%PDF-1.4 prueba", "application/pdf")})


def test_los_documentos_adjuntos_se_ven_y_se_suben_solo_con_internet(admin_client, consultorio, nodo_apagado):
    """Son archivos del disco del central: LibraEdge espeja filas, no archivos. 409 `sin_conexion` sin conexión (decisión
    del humano) y `solo_en_el_central` con ella: la PC tampoco tiene el archivo. La lista (las filas) sí se lee."""
    documento = _subir(admin_client).json()
    ruta = f"/patients/patient-1/documents/{documento['id']}"
    nodo_apagado.prender()

    assert [d["id"] for d in admin_client.get("/patients/patient-1/documents").json()] == [documento["id"]]
    assert admin_client.get(ruta).json()["title"] == "Informe"
    for metodo, url, kw in (("POST", "/patients/patient-1/documents", {"data": {"author": "a", "title": "t"},
                                                                    "files": {"file": ("x.pdf", b"x", "application/pdf")}}),
                            ("GET", f"{ruta}/file", {}), ("DELETE", ruta, {})):
        r = admin_client.request(metodo, url, **kw)
        assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "sin_conexion"), (metodo, url)
        assert "internet" in r.json()["detail"]["mensaje"]
    nodo_apagado.en_linea(True)
    r = admin_client.get(f"{ruta}/file")
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "solo_en_el_central")
    nodo_apagado.apagar()
    assert admin_client.get(f"{ruta}/file").status_code == 200


def test_las_notas_se_leen_en_el_nodo_sin_pedir_nada_al_central(admin_client, consultorio, nodo_apagado):
    nota = _cargar(admin_client, "nota")
    nodo_apagado.prender()
    assert [n["id"] for n in admin_client.get("/patients/patient-1/notes").json()] == [nota["id"]]
    assert admin_client.get(f"/patients/patient-1/notes/{nota['id']}").json()["text"] == "Dolor lumbar de 3 días"
