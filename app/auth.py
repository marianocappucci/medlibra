"""Session auth for MedLibra's JSON API.

Reuses libracore.auth.SessionAuth for the cookie/session mechanics (signed
cookie, secret-key resolution with the same fail-closed-in-production
posture) -- that part is already product-agnostic by design (callbacks
instead of an assumed schema, see libracore's auth.py docstring). What we
don't reuse is SessionAuth.require_auth/require_role: those redirect to
"/login" with a 307, which fits Contalibra's server-rendered app but makes
no sense for a JSON API with no such page. These dependencies return plain
401/403 with a JSON body instead. Same pattern already used by Gestiolibra.
"""
from fastapi import Depends, HTTPException, Request
from libracore.auth import SessionAuth

from .services.users import UserRepository


def build_session_auth(users: UserRepository) -> SessionAuth:
    return SessionAuth(
        dev_secret_fallback="medlibra-dev-secret-not-for-prod",
        get_user_by_username=users.get_by_username,
        check_credentials=users.check_credentials,
        cookie_name="ml_session",
    )


def get_session_auth(request: Request) -> SessionAuth:
    return request.app.state.session_auth


def get_current_user(
    request: Request, auth: SessionAuth = Depends(get_session_auth),
) -> dict:
    username = auth.get_current_user(request)
    if username is None:
        raise HTTPException(401, "not authenticated")
    users: UserRepository = request.app.state.users
    user = users.get_by_username(username)
    if user is None or not user["active"]:
        raise HTTPException(401, "not authenticated")
    return user


def require_role(*roles: str):
    """Dependency factory: 403s unless the logged-in user has one of roles."""

    def _dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "forbidden")
        return user

    return _dependency


require_admin = require_role("admin")
require_staff = require_role("admin", "staff")
