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
container needs no MedLibra-specific env vars at all.

Also serves the built frontend SPA if present -- mismo patrón exacto que
`app/asgi.py` de Gestiolibra (ver DECISIONS.md ADR-021 de este repo):
looks in `/opt/frontend-dist` first (donde el Dockerfile hornea el stage
de node), cae a `frontend/dist` relativo al repo para build+preview local
sin Docker. Si no existe ninguno de los dos (API pura sin frontend
buildeado), el mount se salta solo."""
import os

from libracore.db.url_de_instancia import url_de_instancia

from app.frontend_dist import frontend_dist
from app.spa import montar_spa

DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    database_url = url_de_instancia(
        "medlibra", default=f"sqlite:///{DATA_DIR}/medlibra.db"
    )
    # La base de LibraCore ya NO se puentea acá: `Config` (ADR-043) la resuelve sola -- la de `MEDLIBRA_LIBRACORE_DATABASE_URL`
    # si hay una OTRA, y la del dominio si no (una sola base, ADR-044 y ADR-046)--, y el motor (`libracore-migrar`) lee esa
    # misma variable del entorno por su cuenta.
    os.environ.setdefault(
        "MEDLIBRA_DOCUMENTS_DIR", f"{DATA_DIR}/medlibra_documents"
    )
    if os.environ.get("ADMIN_USER"):
        os.environ.setdefault("MEDLIBRA_ADMIN_USERNAME", os.environ["ADMIN_USER"])
    if os.environ.get("ADMIN_PASSWORD"):
        os.environ.setdefault("MEDLIBRA_ADMIN_PASSWORD", os.environ["ADMIN_PASSWORD"])
else:
    database_url = url_de_instancia("medlibra", requerida=True)

from .main import create_app  # noqa: E402 -- after env bridging above

app = create_app(database_url)

FRONTEND_DIST = frontend_dist()
if FRONTEND_DIST.is_dir():
    montar_spa(app, FRONTEND_DIST)
