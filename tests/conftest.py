import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from motor_de_test import destino_libracore, fresh_database_url

@pytest.fixture(autouse=True)
def _dev_env(monkeypatch, tmp_path):
    # SessionAuth's SECRET_KEY resolution and the admin bootstrap both
    # fail closed unless ENV=development -- see app/auth.py and
    # app/services/users.py::ensure_default_admin.
    monkeypatch.setenv("ENV", "development")
    # Uploaded clinical documents go to a per-test temp dir instead of the
    # repo's default ./data path -- pytest cleans tmp_path up automatically.
    monkeypatch.setenv("MEDLIBRA_DOCUMENTS_DIR", str(tmp_path / "medlibra_documents"))
    # libracore.db is raw sqlite3 (a fresh connection per call, unlike
    # SQLAlchemy's pooled engine) -- ":memory:" would give every call an
    # empty, unrelated database. A real temp file per test is required.
    #
    # 🔴 Y contra PostgreSQL va a SU PROPIA base, no a la del dominio. Hasta el
    # 2026-08-10 esta linea daba un archivo SQLite temporal aunque el resto de
    # la corrida fuera a PostgreSQL: la mitad cruda del producto -- las ~340
    # consultas de LibraCore -- nunca se ejercitaba contra el motor nuevo.
    monkeypatch.setenv(
        "MEDLIBRA_LIBRACORE_DB_PATH",
        destino_libracore(tmp_path / "medlibra_libracore.db"),
    )
    # `libracore.config_manager` resuelve sus rutas AL IMPORTARSE, desde
    # DATA_DIR o -- si no esta -- el cwd, que corriendo pytest es la raiz del
    # repo. Setear la variable de entorno aca ya llega tarde, por eso se
    # parchean los atributos del modulo y no el entorno.
    #
    # Sin esto, `test_config_backup.py` escribe `config.json` y `logos/logo.png`
    # EN EL ARBOL DE TRABAJO: guardar los datos del consultorio deja el nombre
    # y el CUIT del test commiteados, y subir el logo graba en `logo_path` la
    # ruta absoluta de la maquina que corrio la suite -- un valor que no puede
    # ser correcto para ninguna otra. El que corre los tests se lleva un ` M
    # config.json` que es facil que se cuele en un commit o un PR.
    #
    # Es el mismo bug que VentaLibra encontro el 2026-07-28 al agregar la
    # config del ticket (ver su tests/conftest.py); aca llego con la pantalla
    # de Configuracion y quedo sin arreglar hasta el 2026-08-16.
    #
    # `CERTS_DIR` no se parchea a proposito: los certificados ARCA de este
    # producto salen de la config de facturacion en la base
    # (`app/routers/billing.py`), no de `config_manager`.
    from libracore import config_manager
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_manager, "LOGO_DIR", str(tmp_path / "logos"))


def https_client(app) -> TestClient:
    """SessionAuth's cookie is Secure-flagged (see libracore.auth); httpx's
    cookie jar won't send a Secure cookie back over plain http, and
    TestClient defaults to http://testserver. A dotted hostname is required
    too: httpx's cookie jar domain-matching is unreliable for single-label
    hosts like the default "testserver". This part is real and stays.

    CORRECTION (2026-07-25, investigated in VentaLibra/DECISIONS.md
    ADR-006): this comment used to say the intermittent 401 seen in this
    suite was "found and fixed in Gestiolibra's own conftest.py" via this
    dotted hostname -- that was misdiagnosed (see the corrected comment in
    gestiolibra/tests/conftest.py). The dotted hostname does NOT fix it.
    The real cause is this machine's WSL2 clock jumping ~15s
    forward/backward recurrently during a test run, which intermittently
    makes itsdangerous's signature/expiry check on SessionAuth's cookie
    fail even though the cookie is valid -- not a cookie-jar or
    domain-matching problem, and not fixable in application code (it's an
    environment issue, not reproduced outside this WSL2 machine)."""
    return TestClient(app, base_url="https://medlibra.test")


@pytest.fixture
def admin_client():
    """Fresh app + logged in as the dev bootstrap admin (admin/admin).

    Entered as a context manager and kept open for the whole test: outside
    a `with` block, TestClient spins up a brand new anyio portal thread per
    request instead of reusing one (see starlette.testclient.TestClient).
    """
    with https_client(create_app(fresh_database_url())) as client:
        response = client.post("/auth/login", json={"username": "admin", "password": "admin"})
        assert response.status_code == 200, response.text
        yield client


@pytest.fixture
def staff_client(admin_client: TestClient):
    """A second client logged in as a staff user that admin_client just
    created -- same app/database, separate session/cookie."""
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "staff-pass", "role": "staff",
    })
    assert created.status_code == 201, created.text
    with https_client(admin_client.app) as client:
        response = client.post("/auth/login", json={"username": "staff-1", "password": "staff-pass"})
        assert response.status_code == 200, response.text
        yield client
