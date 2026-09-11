"""El catálogo que lee la Agenda, para quien la opera (ADR-039).

🔴 **Lo que hay que probar es que el mostrador pueda armar la Agenda SIN que se
le abra la configuración.** Hasta el 2026-09-11 la pantalla pedía `/resources`,
`/branches` y `/services`, los tres `admin_only`: staff recibía 403, el
`Promise.all` de la carga se caía entero y la Agenda decía que no había
profesionales. Arreglarlo abriendo esos routers habría sido lo barato, y le
habría dado a staff también el alta, la edición y el borrado del catálogo.
"""
import pytest
from conftest import https_client
from fastapi.testclient import TestClient
from motor_de_test import fresh_database_url


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
    client = admin_client
    assert client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Cordoba",
        "phone": "011-4444-5555", "address": "Av. Siempreviva 742",
    }).status_code == 201
    assert client.post("/resources", json={
        "id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1",
    }).status_code == 201
    assert client.post("/resources", json={
        "id": "dra-baja", "name": "Dra. De Baja", "branch_id": "sede-1", "active": False,
    }).status_code == 201
    assert client.post("/services", json={
        "id": "consulta", "name": "Consulta", "duration_minutes": 30,
    }).status_code == 201
    assert client.post("/services", json={
        "id": "vieja", "name": "Prestación dada de baja",
        "duration_minutes": 20, "active": False,
    }).status_code == 201
    return client


def test_el_mostrador_lee_el_catalogo_de_la_agenda(
    consultorio: TestClient, staff_client: TestClient,
):
    """🔴 Es para quien existe la lectura: staff arma la Agenda con esto."""
    respuesta = staff_client.get("/agenda/catalogo")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    assert {p["id"]: p for p in cuerpo["profesionales"]}["dr-molina"] == {
        "id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1", "active": True,
    }
    # El huso es lo que la Agenda necesita de la sede: sin él, cada turno cae
    # en el día y la hora del navegador (ADR-028). Córdoba y no el default,
    # para que un huso inventado por el endpoint no pase por casualidad.
    assert cuerpo["sedes"] == [{
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Cordoba",
    }]
    assert {p["id"]: p for p in cuerpo["prestaciones"]}["consulta"] == {
        "id": "consulta", "name": "Consulta", "duration_minutes": 30, "active": True,
    }


def test_la_sede_viaja_recortada(consultorio: TestClient, staff_client: TestClient):
    """Sin teléfono ni dirección: la Agenda no los usa, y una lectura para el
    mostrador no tiene por qué servir más de lo que la pantalla necesita."""
    sede = staff_client.get("/agenda/catalogo").json()["sedes"][0]
    assert set(sede) == {"id", "name", "timezone"}


def test_los_dados_de_baja_vienen_con_su_marca(
    consultorio: TestClient, staff_client: TestClient,
):
    """No se filtran en el backend: un turno viejo con una prestación dada de
    baja tiene que seguir mostrando su nombre. La pantalla filtra los activos
    para ofrecer y para dibujar carriles."""
    cuerpo = staff_client.get("/agenda/catalogo").json()
    profesionales = {p["id"]: p["active"] for p in cuerpo["profesionales"]}
    prestaciones = {p["id"]: p["active"] for p in cuerpo["prestaciones"]}
    assert profesionales == {"dr-molina": True, "dra-baja": False}
    assert prestaciones == {"consulta": True, "vieja": False}


def test_admin_lee_lo_mismo(consultorio: TestClient, staff_client: TestClient):
    de_admin = consultorio.get("/agenda/catalogo")
    assert de_admin.status_code == 200
    assert de_admin.json() == staff_client.get("/agenda/catalogo").json()


@pytest.mark.parametrize("metodo, ruta, cuerpo", [
    ("get", "/resources", None),
    ("get", "/branches", None),
    ("get", "/services", None),
    ("post", "/resources", {"id": "r2", "name": "Otro"}),
    ("post", "/branches", {"id": "s2", "name": "Otra"}),
    ("post", "/services", {"id": "x", "name": "X", "duration_minutes": 10}),
    ("put", "/resources/dr-molina", {"name": "Cambiado"}),
    ("put", "/branches/sede-1", {"name": "Cambiada"}),
    ("put", "/services/consulta", {"name": "Cambiada", "duration_minutes": 10}),
    ("delete", "/resources/dr-molina", None),
    ("delete", "/branches/sede-1", None),
    ("delete", "/services/consulta", None),
])
def test_el_catalogo_sigue_cerrado_para_staff(
    consultorio: TestClient, staff_client: TestClient, metodo, ruta, cuerpo,
):
    """🔴 El control: el arreglo es una lectura nueva, no abrir la
    configuración. Si alguien "arreglara" la Agenda pasando estos routers a
    `staff_or_admin`, esto se pone rojo."""
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    assert getattr(staff_client, metodo)(ruta, **kwargs).status_code == 403


def test_sin_sesion_no_hay_catalogo():
    from app.main import create_app
    client = https_client(create_app(fresh_database_url()))
    assert client.get("/agenda/catalogo").status_code == 401
