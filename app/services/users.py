"""Users: MedLibra's own table (not part of LibraGenda's domain -- auth
and roles are explicitly out of scope for the engine, see MODULES.md).

Registered on LibraGenda's declarative Base so it's created alongside the
rest of the schema by Base.metadata.create_all() during the demo/test
bootstrap in app.main.create_app(). Real deploys still only run that
bootstrap (MedLibra has no Alembic of its own yet -- see TASKS.md).
"""
import os

from sqlalchemy import Boolean, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base

from .. import security

ROLES = ("admin", "staff")


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


def _to_dict(row: UserRow) -> dict:
    return {
        "id": row.id, "username": row.username, "name": row.name,
        "role": row.role, "active": row.active,
    }


class UserRepository:
    """SQLAlchemy-backed users, with PBKDF2 password hashing at the edge."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, id: str, username: str, name: str, password: str, role: str) -> dict:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role!r} (expected one of {ROLES})")
        row = UserRow(
            id=id, username=username, name=name,
            password_hash=security.hash_password(password), role=role,
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return _to_dict(row)

    def get_by_id(self, user_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(UserRow, user_id)
            return _to_dict(row) if row else None

    def get_by_username(self, username: str) -> dict | None:
        with self.session_factory() as session:
            row = session.scalar(select(UserRow).where(UserRow.username == username))
            return _to_dict(row) if row else None

    def list(self) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(select(UserRow).order_by(UserRow.username)).all()
            return [_to_dict(row) for row in rows]

    def update(self, user_id: str, name: str, role: str, active: bool) -> dict:
        if role not in ROLES:
            raise ValueError(f"invalid role: {role!r} (expected one of {ROLES})")
        with self.session_factory.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError(user_id)
            row.name, row.role, row.active = name, role, active
            updated = _to_dict(row)
        return updated

    def update_password(self, user_id: str, new_password: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError(user_id)
            row.password_hash = security.hash_password(new_password)

    def delete(self, user_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError(user_id)
            session.delete(row)

    def check_credentials(self, username: str, password: str) -> dict | None:
        """Return the user dict if credentials are valid and active, else None.

        Always runs verify_password (against DUMMY_PASSWORD_HASH when the
        username doesn't exist or is inactive) so response time doesn't leak
        whether a username exists.
        """
        with self.session_factory() as session:
            row = session.scalar(select(UserRow).where(UserRow.username == username))
        active = row is not None and row.active
        stored_hash = row.password_hash if active else security.DUMMY_PASSWORD_HASH
        password_ok = security.verify_password(stored_hash, password)
        return _to_dict(row) if (active and password_ok) else None


def ensure_default_admin(repo: UserRepository) -> None:
    """Create the bootstrap admin if the users table is still empty.

    Mirrors libracore.db.usuarios.ensure_admin_user's role in Contalibra
    (and the same helper in Gestiolibra): without at least one admin,
    nobody could ever create the rest of the accounts through the (now
    role-gated) /users API. Same fail-closed posture as libracore.auth's
    SECRET_KEY resolution: no admin password configured means the app
    refuses to boot, unless ENV=development.
    """
    if repo.list():
        return
    username = os.environ.get("MEDLIBRA_ADMIN_USERNAME", "admin")
    password = os.environ.get("MEDLIBRA_ADMIN_PASSWORD", "")
    if not password:
        if os.environ.get("ENV", "production") != "development":
            raise RuntimeError(
                "MEDLIBRA_ADMIN_PASSWORD no esta seteado. No se levanta la "
                "app sin una contrasena de admin inicial (setear ENV=development "
                "para desarrollo local)."
            )
        password = "admin"
    repo.create(id=username, username=username, name="Administrador", password=password, role="admin")
