"""El captcha ALTCHA del login, con la verificacion REAL de libraauth.

El resto de la suite corre con un doble que acepta cualquier solucion (ver
`_captcha_resuelto` en conftest.py). Este archivo vuelve a poner la funcion
original, y es lo unico que se pone rojo si se saca `captcha=True` de
app/routers/auth.py.

Lo que se fija aca es el cableado de ESTE producto; el mecanismo (anti-replay,
vencimiento, firmas) lo prueba libraauth en su `tests/test_captcha.py`.
"""
import json

import pytest
from altcha import Challenge, Payload, solve_challenge
from conftest import CAPTCHA_DE_ORIGINAL, https_client
from libraauth import session_auth
from libraauth.captcha import Captcha
from libraauth.session_auth import CAPTCHA_INVALIDO

from scripts.seed_demo import Api, iniciar_sesion

CREDENCIALES = {"username": "admin", "password": "admin"}


@pytest.fixture
def app(admin_client, monkeypatch):
    """La app de `admin_client` (ya tiene el admin de desarrollo), con el
    captcha real y uno barato: el de produccion tarda del orden de un segundo
    en resolverse."""
    monkeypatch.setattr(session_auth, "_captcha_de", CAPTCHA_DE_ORIGINAL)
    admin_client.app.state.captcha = Captcha(
        "clave-de-prueba", costo=1, contador_min=1, contador_rango=5,
    )
    return admin_client.app


def _resolver(desafio: dict) -> str:
    """Lo que hace el widget del navegador."""
    ch = Challenge.from_dict(desafio)
    return Payload(ch, solve_challenge(ch)).to_base64()


def test_el_desafio_se_emite_y_no_se_cachea(app):
    with https_client(app) as cliente:
        r = cliente.get("/auth/captcha")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert isinstance(cuerpo["parameters"], dict)
    assert isinstance(cuerpo["signature"], str)
    assert r.headers["cache-control"] == "no-store"


def test_sin_captcha_el_login_no_entra_aunque_la_clave_sea_buena(app):
    with https_client(app) as cliente:
        r = cliente.post("/auth/login", json=CREDENCIALES)

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CAPTCHA_INVALIDO


def test_con_el_captcha_resuelto_entra(app):
    with https_client(app) as cliente:
        payload = _resolver(cliente.get("/auth/captcha").json())
        r = cliente.post("/auth/login", json={**CREDENCIALES, "captcha": payload})
        assert r.status_code == 200, r.text
        assert cliente.get("/auth/me").status_code == 200


def test_el_forgot_password_tambien_lo_exige(app):
    with https_client(app) as cliente:
        r = cliente.post("/auth/forgot-password", json={"identificador": "admin"})

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == CAPTCHA_INVALIDO


class _ApiDeTest(Api):
    """El `Api` del seed, hablando con el TestClient."""

    def __init__(self, cliente):
        self.cliente = cliente

    def _pedir(self, metodo, ruta, cuerpo=None):
        r = self.cliente.request(
            metodo, ruta,
            content=json.dumps(cuerpo) if cuerpo is not None else None,
            headers={"Content-Type": "application/json"} if cuerpo is not None else None,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"{metodo} {ruta} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None


def test_el_seed_de_la_demo_resuelve_el_captcha_y_entra(app):
    """El cron de reset de la demo loguea con `iniciar_sesion`: si no
    resolviera el captcha, la demo se quedaria vacia cada noche."""
    with https_client(app) as cliente:
        iniciar_sesion(_ApiDeTest(cliente), "admin", "admin")
        assert cliente.get("/auth/me").status_code == 200
