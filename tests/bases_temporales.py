"""Bases PostgreSQL descartables, para los tests que arman una instancia entera (ADR-043).

La suite normal trabaja sobre la base del worker (`medlibra_gw0`, una sola desde el ADR-044) y la
restaura entre test y test. Un test que necesita **una base propia** —una instancia con dos bases (la
demo, hasta que se una), la cadena de migraciones completa corrida como la corre el deploy— no puede
usarla: la pisaría el `limpiar_entre_tests` del siguiente. Éstas se crean en el mismo servidor, con un nombre único, y se
borran al terminar (`FORCE`: la app del test deja su pool vivo).
"""
from __future__ import annotations

import contextlib
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
from motor_de_test import TEST_DATABASE_URL
from psycopg import sql


def cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def url_de_otra_base(nombre: str) -> str:
    """`TEST_DATABASE_URL` apuntada a la base `nombre`, en forma SQLAlchemy (`postgresql+psycopg://`)."""
    partes = urlsplit(cruda(TEST_DATABASE_URL))
    return urlunsplit(partes._replace(scheme="postgresql+psycopg", path=f"/{nombre}"))


@contextlib.contextmanager
def base_temporal(etiqueta: str = "t"):
    """Crea una base vacía y devuelve su URL; la borra al salir."""
    nombre = f"medlibra_{etiqueta}_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(cruda(TEST_DATABASE_URL), autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
    try:
        yield url_de_otra_base(nombre)
    finally:
        with psycopg.connect(cruda(TEST_DATABASE_URL), autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nombre)))


def consultar(url: str, sentencia: str, parametros=None):
    """Una sentencia en autocommit; devuelve las filas si las hay."""
    with psycopg.connect(cruda(url), autocommit=True) as c:
        cur = c.execute(sentencia, parametros)
        return cur.fetchall() if cur.description else None


def una(url: str, sentencia: str, parametros=None):
    return consultar(url, sentencia, parametros)[0][0]


# ── la cadena de migraciones del deploy ─────────────────────────────────────

#: En el orden y con los argumentos de `scripts/panel_admin.py` (lo fija `test_migraciones_en_el_deploy.py`).
#: `--base` de `libraauth-migrar` es `core` en el deploy (ver el comentario de ese script) y es lo que se corre
#: acá, con una base y con dos; `base_de_auth` lo cambia para medir qué pasaría con otro valor.
_CADENA = (
    ("libragenda-migrar", "upgrade"),
    ("libraauth-migrar", "upgrade", "--prefijo", "medlibra", "--base", "{auth}"),
    ("libracore-migrar", "upgrade", "--prefijo", "medlibra"),
    ("alembic", "upgrade", "head"),
)


def correr_cadena(dominio: str, core: str | None = None, *, solo: tuple[str, ...] | None = None,
                  base_de_auth: str = "core") -> None:
    """Las cadenas del deploy contra bases descartables, como las corre el compose (subprocesos, no en proceso).

    `core=None` es **una sola base**: sin `MEDLIBRA_LIBRACORE_DATABASE_URL`, como una instancia unida o un alta
    nueva (`medlibra` figura en `_UNA_SOLA_BASE` del motor desde libracore v1.194.0: `libracore-migrar` y
    `libraauth-migrar --base core` caen a la base del dominio). Con `core`, dos bases (la demo, hasta que se una).
    `solo` corre únicamente los comandos con esos nombres, en el orden de siempre. `base_de_auth` es el `--base` de
    `libraauth-migrar`: el del deploy es `core`.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    bin_ = Path(sys.executable).parent
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("MEDLIBRA_LIBRACORE_")}
    entorno.update(DATABASE_URL=dominio, MEDLIBRA_DATABASE_URL=dominio)
    if core:
        entorno["MEDLIBRA_LIBRACORE_DATABASE_URL"] = core
    for comando in (c for c in _CADENA if solo is None or c[0] in solo):
        argumentos = [a.format(auth=base_de_auth) for a in comando]
        r = subprocess.run([str(bin_ / argumentos[0]), *argumentos[1:]], env=entorno, cwd=raiz,
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, f"{' '.join(argumentos)}: {(r.stderr or r.stdout)[-2000:]}"
