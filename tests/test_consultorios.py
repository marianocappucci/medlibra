"""El consultorio como entidad propia.

Hasta el 2026-08-23 lo único que MedLibra sabía ocupar era el profesional. Ver
`app/services/consultorios.py` para por qué un consultorio no es un `Resource`
de LibraGenda.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sembrado(admin_client: TestClient) -> TestClient:
    admin_client.post("/branches", json={"id": "sede-1", "name": "Consultorio Norte"})
    return admin_client


def test_consultorio_crud_round_trip(sembrado: TestClient):
    client = sembrado
    creado = client.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })
    assert creado.status_code == 201, creado.text
    assert creado.json() == {
        "id": "cons-1", "name": "Consultorio 1",
        "branch_id": "sede-1", "active": True,
    }

    assert client.get("/consultorios/cons-1").json()["name"] == "Consultorio 1"
    assert len(client.get("/consultorios").json()) == 1

    editado = client.put("/consultorios/cons-1", json={
        "name": "Consultorio 1 (planta baja)", "branch_id": "sede-1", "active": False,
    })
    assert editado.status_code == 200
    assert editado.json()["name"] == "Consultorio 1 (planta baja)"
    assert editado.json()["active"] is False

    assert client.delete("/consultorios/cons-1").status_code == 204
    assert client.get("/consultorios").json() == []


def test_consultorio_duplicado_da_409(sembrado: TestClient):
    sembrado.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1"})
    repetido = sembrado.post("/consultorios", json={"id": "cons-1", "name": "Otro"})
    assert repetido.status_code == 409


def test_consultorio_inexistente_da_404(sembrado: TestClient):
    client = sembrado
    assert client.get("/consultorios/fantasma").status_code == 404
    assert client.put(
        "/consultorios/fantasma", json={"name": "X", "branch_id": None, "active": True},
    ).status_code == 404
    assert client.delete("/consultorios/fantasma").status_code == 404


def test_consultorio_sin_nombre_da_422(sembrado: TestClient):
    respuesta = sembrado.post("/consultorios", json={"id": "cons-1", "name": "   "})
    assert respuesta.status_code == 422


def test_consultorio_puede_no_tener_sede(admin_client: TestClient):
    """`branch_id` opcional a propósito: un consultorio único no necesita que
    alguien haya cargado la sede primero para poder existir."""
    creado = admin_client.post("/consultorios", json={"id": "cons-1", "name": "Único"})
    assert creado.status_code == 201
    assert creado.json()["branch_id"] is None


# ── El consultorio es un Resource del motor (ADR-042) ──────────────────────
#
# El motor traba y compara recursos, así que cada sala tiene que existir como
# `Resource` con su mismo id. Pero ese recurso **no es un profesional**: si saliera
# en los listados de la agenda, la Dra. Vidal tendría al lado un carril llamado
# "Consultorio 2".

def _recurso(client: TestClient, id_: str):
    return client.app.state.catalog.get_resource(id_)


def test_crear_un_consultorio_crea_su_recurso(sembrado: TestClient):
    sembrado.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })

    recurso = _recurso(sembrado, "cons-1")
    assert recurso is not None
    assert (recurso.name, recurso.branch_id, recurso.active) == ("Consultorio 1", "sede-1", True)


def test_editar_y_borrar_el_consultorio_acompanan_al_recurso(sembrado: TestClient):
    sembrado.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1"})

    sembrado.put("/consultorios/cons-1", json={"name": "Sala A", "branch_id": None, "active": False})
    recurso = _recurso(sembrado, "cons-1")
    assert (recurso.name, recurso.branch_id, recurso.active) == ("Sala A", None, False)

    assert sembrado.delete("/consultorios/cons-1").status_code == 204
    assert _recurso(sembrado, "cons-1") is None


def test_los_consultorios_no_aparecen_como_profesionales(sembrado: TestClient):
    """🔴 Con el control de que el profesional SÍ aparece: sin él, "no listar nada"
    pasaría."""
    sembrado.post("/resources", json={"id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1"})
    sembrado.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1"})

    assert [r["id"] for r in sembrado.get("/resources").json()] == ["dr-molina"]
    catalogo = sembrado.get("/agenda/catalogo").json()
    assert [r["id"] for r in catalogo["profesionales"]] == ["dr-molina"]


def test_un_consultorio_con_el_id_de_un_profesional_da_409_y_no_deja_nada(sembrado: TestClient):
    sembrado.post("/resources", json={"id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1"})

    repetido = sembrado.post("/consultorios", json={"id": "dr-molina", "name": "Sala Molina"})

    assert repetido.status_code == 409
    assert sembrado.get("/consultorios").json() == []
    assert _recurso(sembrado, "dr-molina").name == "Dr. Molina"


def test_un_consultorio_con_turnos_no_se_borra(sembrado: TestClient):
    """El 409 de siempre, ahora porque el turno referencia al recurso de la sala."""
    client = sembrado
    client.post("/resources", json={"id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1"})
    client.post("/consultorios", json={"id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1"})
    client.post("/services", json={"id": "consulta", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "p-1", "name": "Ana"})
    client.post("/agenda-blocks", json={
        "resource_id": "dr-molina", "consultorio_id": "cons-1", "weekday": 0,
        "starts_at": "09:00:00", "ends_at": "13:00:00", "valid_from": "2026-07-01",
        "valid_to": None, "slot_minutes": 20, "modality": "turnos",
    })
    turno = client.post("/appointments", json={
        "resource_id": "dr-molina", "service_id": "consulta", "client_id": "p-1",
        "starts_at": "2026-07-20T10:00:00",
    })
    assert turno.status_code == 201, turno.text
    # Sin turnos el consultorio se borra; con turnos, no.
    client.post("/consultorios", json={"id": "cons-2", "name": "Consultorio 2"})
    assert client.delete("/consultorios/cons-2").status_code == 204

    assert client.delete("/consultorios/cons-1").status_code == 409
    assert client.get("/consultorios/cons-1").status_code == 200
    assert _recurso(client, "cons-1") is not None
