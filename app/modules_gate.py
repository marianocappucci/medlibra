"""Dependency factory gating whole routers behind a plan module (see
`plans.py` en la raíz del repo). Mismo criterio de "403 plano, sin
redirect" que `app/auth.py` -- API JSON pura, sin página de upsell."""
from fastapi import Depends, HTTPException, Request

from .services.modules import ModuleRepository


def get_module_repository(request: Request) -> ModuleRepository:
    return request.app.state.modules


def require_module(modulo: str):
    """Dependency factory: 403 si el módulo no está habilitado para esta
    instancia (plan asignado por `nuevo_cliente.py`/`panel_admin.py`)."""

    def _dependency(modules: ModuleRepository = Depends(get_module_repository)) -> None:
        if not modules.is_enabled(modulo):
            raise HTTPException(403, f"modulo '{modulo}' no incluido en el plan actual")

    return _dependency
