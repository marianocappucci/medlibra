"""Los secretos de `config.json` viven cifrados, no en el archivo (2026-09-17).

**Estos tests miran el `config.json` CRUDO y la tabla en la base**, no lo que
devuelve `config_manager.load()`. Es a proposito: `load()` devuelve el secreto
en claro por diseño -para que los consumidores no cambien- asi que un assert
sobre `load()` da verde igual con la implementacion vieja, la que escribia el
token en el archivo. Lo unico que distingue una de otra es que quedo en el
disco.

Y se mide a traves del enganche REAL del producto (`app.main.create_app`), no
armando un almacen a mano: lo que este archivo fija es que MedLibra lo haya
enchufado, que es la mitad que LibraCore no puede garantizar.

🔴 A diferencia de Contalibra, en MedLibra `usuarios` -y por lo tanto
`secretos_instancia`- vive en la base de **LibraCore**, no en la del dominio
(ver el comentario largo en `app/main.py::create_app`). Por eso estos tests
leen la tabla a traves de `client.app.state.auth_engine`, que es el engine que
`create_app()` arma contra esa base -no `app.state` del dominio-.
"""
import json
import os

import pytest
from libraauth.secretos import SecretosRepository
from libracore import config_manager
from sqlalchemy import text

TOKEN = "APP_USR-1234567890123456-091712-abcdef0123456789-3392230021"


def _crudo():
    with open(config_manager.CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _escribir_crudo(datos):
    """Escribe el archivo como lo dejaba la version vieja, sin pasar por
    `save()` -que ya enruta al almacen y no dejaria el secreto en el archivo-."""
    with open(config_manager.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f)


def _filas_de_secretos(app):
    with app.state.auth_engine.connect() as c:
        return dict(c.execute(text("select clave, valor_cifrado from secretos_instancia")).all())


@pytest.fixture(autouse=True)
def _sin_config_json():
    """El archivo no existe antes ni despues. La tabla se limpia sola: cada
    `admin_client` arma una base nueva (`fresh_database_url()`)."""
    if os.path.exists(config_manager.CONFIG_PATH):
        os.unlink(config_manager.CONFIG_PATH)
    yield
    if os.path.exists(config_manager.CONFIG_PATH):
        os.unlink(config_manager.CONFIG_PATH)


def test_el_producto_enchufo_el_almacen(admin_client):
    """Sin esto, todo lo demas es la implementacion vieja: `config_manager` sin
    almacen escribe el secreto en el JSON, exactamente como antes."""
    assert isinstance(config_manager.almacen_de_secretos(), SecretosRepository)


def test_guardar_el_token_no_lo_deja_en_el_archivo(admin_client):
    cfg = config_manager.load()
    cfg["mp_access_token"] = TOKEN
    cfg["empresa_nombre"] = "Consultorio de prueba"
    config_manager.save(cfg)

    crudo = _crudo()
    assert crudo["mp_access_token"] == ""
    # Control positivo del mismo barrido: lo que no es secreto si quedo escrito.
    assert crudo["empresa_nombre"] == "Consultorio de prueba"
    # Y para los consumidores no cambio nada.
    assert config_manager.load()["mp_access_token"] == TOKEN


def test_en_la_base_tampoco_esta_en_claro(admin_client):
    cfg = config_manager.load()
    cfg["mp_access_token"] = TOKEN
    config_manager.save(cfg)

    filas = _filas_de_secretos(admin_client.app)
    assert "mp_access_token" in filas
    assert TOKEN not in filas["mp_access_token"]
    assert filas["mp_access_token"].startswith("v1:")


def test_el_arranque_migra_lo_que_la_version_vieja_dejo_en_el_archivo(admin_client):
    """🔑 El caso de las instancias vivas: el archivo tiene los secretos en
    claro, se despliega esta version, y el arranque los mueve solo.

    `admin_client` ya disparo un arranque (el que crea la app de este test) sin
    nada que migrar; acá se simula el escenario real escribiendo el JSON viejo
    y llamando a la migracion de nuevo -misma funcion que corre en cada
    arranque, y es idempotente (ver el test de abajo)-.
    """
    from app.main import migrar_secretos

    _escribir_crudo({
        "empresa_nombre": "Consultorio de prueba",
        "mp_access_token": TOKEN,
        "mp_webhook_secret": "firma-del-webhook",
        "email_smtp_password": "la-contrasena",
    })
    assert _crudo()["mp_access_token"] == TOKEN          # el punto de partida

    informe = migrar_secretos()

    assert sorted(informe["migradas"]) == [
        "email_smtp_password", "mp_access_token", "mp_webhook_secret",
    ]
    crudo = _crudo()
    for clave in config_manager.CLAVES_SECRETAS:
        assert crudo[clave] == "", f"{clave} sigue en el archivo"
    assert crudo["empresa_nombre"] == "Consultorio de prueba"
    assert config_manager.load()["mp_access_token"] == TOKEN
    assert config_manager.load()["mp_webhook_secret"] == "firma-del-webhook"


def test_la_migracion_es_idempotente(admin_client):
    from app.main import migrar_secretos

    _escribir_crudo({"mp_access_token": TOKEN})
    migrar_secretos()
    antes = _filas_de_secretos(admin_client.app)["mp_access_token"]

    informe = migrar_secretos()

    assert informe == {"migradas": [], "ya_estaban": [], "fallaron": {}}
    # No se reescribio: el blob es el mismo, con el mismo nonce.
    assert _filas_de_secretos(admin_client.app)["mp_access_token"] == antes


def test_el_arranque_de_la_app_corre_la_migracion():
    """El enganche en `create_app()` y no solo la funcion: sin la llamada, la
    migracion existe y nadie la corre.

    No usa `admin_client` a proposito: necesita escribir el `config.json`
    viejo ANTES de que `create_app()` corra, y `admin_client` ya crea la app
    en la fixture."""
    from motor_de_test import fresh_database_url

    from app.main import create_app

    _escribir_crudo({"mp_access_token": TOKEN})
    app = create_app(fresh_database_url())
    try:
        assert _crudo()["mp_access_token"] == ""
        assert config_manager.load()["mp_access_token"] == TOKEN
    finally:
        app.state.auth_engine.dispose()
