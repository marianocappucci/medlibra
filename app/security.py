"""Password hashing for MedLibra's own users table.

Same PBKDF2 construction as libracore.db.usuarios (260k iterations,
per-password salt, constant-time compare) -- that module can't be imported
directly because it's coupled to SQLite via libracore.db.core.get_connection,
while MedLibra is PostgreSQL/SQLAlchemy. This is the same algorithm
applied to MedLibra's own storage, not a different security posture. Same
copy already used by Gestiolibra (see wiki/entities/gestiolibra.md ADR-005
in that repo's DECISIONS.md).
"""
import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_hex(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:{salt}:{dk.hex()}"


def verify_password(stored: str, provided: str) -> bool:
    try:
        _, algo, salt, stored_hash = stored.split(":")
        dk = hashlib.pbkdf2_hmac(algo, provided.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(dk.hex(), stored_hash)
    except Exception:
        return False


# Same cost as a real hash, verified when a username doesn't exist so
# check_credentials() takes the same time either way (no timing side
# channel for username enumeration). Built once at import.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_hex(16))
