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
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.spa import TIPOS_PROPIOS, archivo_publico

DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    database_url = url_de_instancia(
        "medlibra", default=f"sqlite:///{DATA_DIR}/medlibra.db"
    )
    # Puente al nombre NORMALIZADO -- ver el comentario equivalente en
    # gestiolibra/app/asgi.py: se resuelve primero para que un compose con
    # el nombre viejo gane sobre el default de SQLite.
    os.environ.setdefault(
        "MEDLIBRA_LIBRACORE_DATABASE_URL",
        url_de_instancia("medlibra", core=True,
                         default=f"{DATA_DIR}/medlibra_libracore.db"),
    )
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

_DOCKER_FRONTEND_DIST = Path("/opt/frontend-dist")
_LOCAL_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_DIST = (
    _DOCKER_FRONTEND_DIST if _DOCKER_FRONTEND_DIST.is_dir() else _LOCAL_FRONTEND_DIST
)
#: 🔴 **`index.html` no se cachea, y esto no es una optimización: es lo que
#: hace que un deploy se vea.**
#:
#: Vite le pone un hash en el nombre a cada bundle, así que el archivo nuevo
#: nunca pisa al viejo — pero `index.html` **conserva el nombre** y es el único
#: que dice cuál es el bundle de ahora. Sin `Cache-Control`, el navegador aplica
#: caché heurística (una fracción de la antigüedad del `Last-Modified`) y puede
#: servir el `index.html` guardado sin preguntar. El usuario recarga, no ve el
#: cambio, y del lado del servidor está todo bien: el contenedor tiene el código
#: nuevo, el bundle nuevo está publicado, y el navegador sigue pidiendo el viejo
#: — que además existe, porque el nombre lleva hash.
#:
#: Le pasó a LibraCargo el 2026-08-19 con la pantalla de Backup, y estas seis
#: instancias servían el `index.html` sin la cabecera hasta el 2026-08-20 —
#: medido contra los dominios, no leído del compose.
#:
#: `no-cache` **no** es "no guardes": es "guardá, pero revalidá siempre".
SIN_CACHE = "no-cache, must-revalidate"

#: Los assets, al revés: el nombre lleva el hash del contenido, así que **el
#: mismo nombre nunca cambia de contenido** y se pueden cachear para siempre. Un
#: `index.html` que revalida siempre es lo que hace seguro esto: cuando el
#: contenido cambia, el nombre cambia, y el `index.html` fresco pide el nuevo.
PARA_SIEMPRE = "public, max-age=31536000, immutable"


class AssetsInmutables(StaticFiles):
    """`StaticFiles` con la cabecera de caché larga."""

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = PARA_SIEMPRE
        return respuesta


if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets", AssetsInmutables(directory=FRONTEND_DIST / "assets"), name="frontend-assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        archivo = archivo_publico(FRONTEND_DIST, full_path)
        if archivo is not None:
            # Los archivos sueltos del dist (favicon, manifest) tampoco
            # llevan hash en el nombre: mismo criterio que el index.
            return FileResponse(archivo, media_type=TIPOS_PROPIOS.get(archivo.suffix),
                                headers={"Cache-Control": SIN_CACHE})
        return FileResponse(FRONTEND_DIST / "index.html",
                            headers={"Cache-Control": SIN_CACHE})
