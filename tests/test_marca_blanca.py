"""La marca blanca esta cableada: la instancia puede tener nombre, color y logo del revendedor (libracore ADR-092).

Lo que se mide aca es el **cableado** del producto, no el motor: que las rutas esten montadas, que escribir las gatee el rol del producto
(admin o token de servicio del backoffice) y que el mail de recuperacion salga con el nombre de la marca. El comportamiento lo prueba
`libracore`.
"""
import importlib
import sys

import pytest
from conftest import https_client
from libraauth.session_auth import SERVICE_TOKEN_ENV, SERVICE_TOKEN_HEADER
from motor_de_test import fresh_database_url

from app.main import create_app

TOKEN = "token-de-servicio-de-prueba-no-es-real"
MARCA = {"nombre": "Clinica Modelo", "nombre_corto": "Modelo", "color": "#c0392b"}


@pytest.fixture
def anonimo():
    with https_client(create_app(fresh_database_url())) as client:
        yield client


@pytest.fixture
def panel(anonimo, monkeypatch):
    """Sin sesion, con el token de servicio: es como llega el backoffice."""
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)
    anonimo.headers[SERVICE_TOKEN_HEADER] = TOKEN
    return anonimo


def test_sin_marca_la_instancia_es_la_del_producto(anonimo):
    r = anonimo.get("/api/marca")
    assert r.status_code == 200
    assert r.json()["propia"] is False
    assert r.json()["terminos_propios"] is False


def test_el_admin_carga_la_marca_y_cualquiera_la_lee(admin_client):
    assert admin_client.put("/api/marca", json=MARCA).status_code == 200
    leida = https_client(admin_client.app).get("/api/marca").json()  # sin sesion: el login tambien lleva la marca
    assert leida["propia"] is True
    assert leida["nombre"] == "Clinica Modelo"
    assert leida["color"] == "#c0392b"


@pytest.mark.parametrize("metodo", ["put", "delete"])
def test_sin_sesion_no_se_escribe_la_marca(anonimo, metodo):
    r = anonimo.request(metodo, "/api/marca", json=MARCA if metodo == "put" else None)
    assert r.status_code in (401, 403)


def test_el_staff_no_escribe_la_marca(staff_client):
    assert staff_client.put("/api/marca", json=MARCA).status_code == 403


def test_sin_sesion_no_se_escriben_los_terminos_propios(anonimo):
    r = anonimo.put("/api/marca/terminos", json={"version": "r-1.0", "vigente_desde": "01-01-2026", "texto": "x"})
    assert r.status_code in (401, 403)


def test_el_token_de_servicio_del_backoffice_escribe_la_marca(panel):
    r = panel.put("/api/marca", json=MARCA)
    assert r.status_code == 200, r.text
    assert https_client(panel.app).get("/api/marca").json()["nombre"] == "Clinica Modelo"


def test_un_token_equivocado_no_escribe_la_marca(anonimo, monkeypatch):
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)
    assert anonimo.put("/api/marca", json=MARCA, headers={SERVICE_TOKEN_HEADER: "otro"}).status_code == 401


def test_el_mail_de_recuperacion_sale_con_el_nombre_de_la_marca(admin_client):
    reset = admin_client.app.state.password_reset
    assert reset.product_name == "MedLibra"
    admin_client.put("/api/marca", json=MARCA)
    assert reset.product_name == "Clinica Modelo"
    admin_client.delete("/api/marca")
    assert reset.product_name == "MedLibra"


def test_el_manifest_le_gana_al_catch_all_de_la_spa(monkeypatch, tmp_path):
    """🔴 Con un build, `app/asgi.py` contesta `index.html` a cualquier ruta que no conozca. Si la marca se montara despues, el navegador
    leeria HTML como manifest. Se importa el entrypoint real con un build de juguete (`frontend_dist()` apuntado a el)."""
    import app.main as app_main
    from app import frontend_dist as fd

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-de-prueba</html>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name": "MedLibra", "icons": []}', encoding="utf-8")
    monkeypatch.setattr(fd, "_DOCKER_FRONTEND_DIST", tmp_path / "no-existe")
    monkeypatch.setattr(fd, "_LOCAL_FRONTEND_DIST", dist)
    # `app.asgi` arma la app con la base del entorno: aca, una de la suite.
    monkeypatch.setenv("DATABASE_URL", fresh_database_url())
    monkeypatch.setattr(app_main, "create_app", lambda url: create_app(fresh_database_url()))
    previo = sys.modules.pop("app.asgi", None)
    try:
        asgi = importlib.import_module("app.asgi")
        c = https_client(asgi.app)
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200 and r.json()["name"] == "MedLibra", r.text
        assert "manifest" in r.headers["content-type"], r.headers
        assert c.get("/api/marca").json()["propia"] is False
        assert "spa-de-prueba" in c.get("/cualquier/ruta").text
    finally:
        sys.modules.pop("app.asgi", None)
        if previo is not None:
            sys.modules["app.asgi"] = previo
