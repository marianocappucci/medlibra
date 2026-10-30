"""Donde esta el build del frontend.

Lo usan `asgi.py` (para servirlo) y `main.py` (el manifest de la marca cae al `manifest.webmanifest` del build).

El dist se hornea fuera de `/app` (`/opt/frontend-dist`) porque el compose de dev monta `./:/app` entero para el `--reload`, y eso taparia
cualquier build copiado adentro. En local cae a `frontend/dist`.
"""
from __future__ import annotations

from pathlib import Path

_DOCKER_FRONTEND_DIST = Path("/opt/frontend-dist")
_LOCAL_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def frontend_dist() -> Path:
    return _DOCKER_FRONTEND_DIST if _DOCKER_FRONTEND_DIST.is_dir() else _LOCAL_FRONTEND_DIST
