"""ASGI entrypoint for production/dev containers: `create_app()` takes a
required `database_url` argument, so it can't be used directly as
uvicorn's factory target -- this module reads it from the environment
once at import time and exposes the built `app` instance uvicorn expects
(`uvicorn app.asgi:app`).

Bridges two env var conventions: the `docker-compose.yml` of this repo
(DATABASE_URL/MEDLIBRA_*, set explicitly) for local dev, and the generic
contract `libracore.provisioning` writes for real clients
(DATA_DIR/ADMIN_USER/ADMIN_PASSWORD/ADMIN_NOMBRE -- same names Contalibra/
Restolibra/Gestiolibra already read directly, see
wiki/entities/libracore.md). When DATA_DIR is present it takes precedence
for anything not already set explicitly, so a provisioned client
container needs no MedLibra-specific env vars at all. Mismo patrón
exacto que `app/asgi.py` de Gestiolibra, sin el bloque de servir el
frontend -- MedLibra todavía no tiene uno (ver ROADMAP.md, Fase 4 sin
empezar)."""
import os

DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    database_url = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/medlibra.db")
    os.environ.setdefault(
        "MEDLIBRA_LIBRACORE_DB_PATH", f"{DATA_DIR}/medlibra_libracore.db"
    )
    os.environ.setdefault(
        "MEDLIBRA_DOCUMENTS_DIR", f"{DATA_DIR}/medlibra_documents"
    )
    if os.environ.get("ADMIN_USER"):
        os.environ.setdefault("MEDLIBRA_ADMIN_USERNAME", os.environ["ADMIN_USER"])
    if os.environ.get("ADMIN_PASSWORD"):
        os.environ.setdefault("MEDLIBRA_ADMIN_PASSWORD", os.environ["ADMIN_PASSWORD"])
else:
    database_url = os.environ["DATABASE_URL"]

from .main import create_app  # noqa: E402 -- after env bridging above

app = create_app(database_url)
