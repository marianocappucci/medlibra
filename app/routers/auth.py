"""Router /auth (login/logout/me/verify) -- shim sobre
libraauth.session_auth.build_json_api_auth_router.

Extraído 2026-07-26 a libracore.auth (era byte-idéntico en Gestiolibra/
MedLibra/VentaLibra, ver wiki/analyses/auditoria-duplicacion-familia-libra.md)
y **migrado el 2026-07-30 a libraauth**, completando la migración: con esto
MedLibra ya no importa nada de `libracore.auth`.

`incluir_verify=True` es obligatorio acá: `POST /auth/verify` es el chequeo
stateless de credenciales que usa el login de `/docs/` de la landing
(server-to-server con `DOCS_AUTH_SECRET`, ver ADR-026). En libraauth el
endpoint es opt-in porque no todo consumidor tiene landing (LibraDesk no la
tenía cuando se creó el paquete); **sin este flag el `/docs/` de la landing
deja de poder validar credenciales**.
"""
import json

from libraauth.session_auth import build_json_api_auth_router
from libracore import config_manager


def _empresa_nombre(_request) -> str | None:
    """El nombre del negocio de esta instancia, para el subtítulo del sidebar (debajo del nombre del producto).

    Es el `empresa_nombre` de la config de LibraCore —la que edita Configuración > Datos de empresa—. Se lee el JSON a
    mano y NO con `config_manager.load()`: ése resuelve además los tres secretos contra la base (una sesión por cada uno)
    en cada login y cada `/auth/me`, y haría fallar la autenticación si el almacén de secretos tiene un error, para leer un
    campo que no es secreto. Sin archivo, ilegible o vacío: `None`, y el sidebar no dibuja un subtítulo en blanco."""
    try:
        with open(config_manager.CONFIG_PATH, encoding="utf-8") as f:
            return (json.load(f).get("empresa_nombre") or "").strip() or None
    except Exception:
        return None


router = build_json_api_auth_router(
    incluir_verify=True, incluir_password_reset=True, incluir_demo=True, captcha=True,
    get_empresa_nombre=_empresa_nombre,
)
