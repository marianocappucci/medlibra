"""El arranque con DOS workers de uvicorn de verdad (libracore ADR-044).

Todo el producto sigue corriendo con **un** proceso (`WEB_CONCURRENCY` por defecto, 1), pero el codigo ya esta listo para
mas. Lo unico que un `TestClient` no puede ver es lo que pasa cuando dos procesos arrancan JUNTOS contra las mismas
bases: `create_app()` ES el arranque, y sus «si no existe, crear» (los modulos, el admin) se contestan «no existe» en los
dos workers antes de que ninguno cree, salvo que los serialice `una_vez_al_arrancar`.

Este test deja las dos bases como las deja un deploy (migradas, sin sembrar: la plantilla «armada» de la suite sin las
filas de `modulos` ni de `usuarios`), levanta `uvicorn app_dos_workers:app --workers 2` (`app.asgi` con la ventana de la carrera ensanchada, ver `tests/app_dos_workers.py`) como subproceso, y mira que:

- los dos workers arrancan, sin ningun traceback en el log (los dos loguean «Application startup complete»; uvicorn reinicia a
  un worker que muere, asi que «arrancaron» no alcanza);
- queda UN solo usuario admin y cada modulo UNA vez.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
import pytest
from conftest import _construir_armada
from libracore.testing.varios_procesos import pedir, puerto_libre
from motor_de_test import fresh_database_url, limpiar_entre_tests, url_libracore

from plans import TODOS_LOS_MODULOS

pytestmark = pytest.mark.varios_procesos

RAIZ = Path(__file__).resolve().parent.parent


def _cruda(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _esperar(proceso, log, base, *, arranque=90.0):
    """Hasta que `/health` conteste Y los dos workers hayan terminado su startup (el segundo espera el candado)."""
    limite = time.monotonic() + arranque
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            break
        log.seek(0)
        listos = len(re.findall(r"Application startup complete", log.read().decode(errors="replace")))
        if listos >= 2:
            try:
                if pedir(base + "/health", espera=2)[0] == 200:
                    return
            except OSError:
                pass
        time.sleep(0.2)
    log.seek(0)
    raise AssertionError("los dos workers no terminaron de arrancar:\n" + log.read().decode(errors="replace"))


def test_dos_workers_arrancan_y_el_seed_queda_una_sola_vez(tmp_path):
    # Las dos bases «armadas» (todas las tablas) y sin sembrar: lo que deja un deploy antes del primer arranque.
    limpiar_entre_tests(_construir_armada)
    dominio = fresh_database_url()
    with psycopg.connect(_cruda(dominio), autocommit=True) as c:
        c.execute("DELETE FROM medlibra_modulos")
    with psycopg.connect(_cruda(url_libracore()), autocommit=True) as c:
        c.execute("DELETE FROM usuarios")

    puerto = puerto_libre()
    env = {
        **os.environ, "PYTHONPATH": str(RAIZ / "tests"), "DATA_DIR": str(tmp_path), "MEDLIBRA_DOCUMENTS_DIR": str(tmp_path / "medlibra_documents"),
        "DATABASE_URL": dominio, "MEDLIBRA_LIBRACORE_DB_PATH": url_libracore(),
    }
    with tempfile.TemporaryFile() as log:
        proceso = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app_dos_workers:app", "--host", "127.0.0.1", "--port", str(puerto),
             "--workers", "2", "--log-level", "info"],
            env=env, cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            _esperar(proceso, log, f"http://127.0.0.1:{puerto}")
        finally:
            proceso.terminate()
            try:
                proceso.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proceso.kill()
                proceso.wait()
        # 🔴 uvicorn REINICIA a un worker que muere en el arranque: sin esto, un worker que revienta por la carrera y
        # vuelve a levantar limpio pasaria por «arranco bien». Un arranque sano no deja ningun traceback en el log.
        log.seek(0)
        texto = log.read().decode(errors="replace")
        assert "Traceback" not in texto and "startup failed" not in texto, texto

    with psycopg.connect(_cruda(url_libracore())) as c:
        admins = c.execute("SELECT count(*) FROM usuarios WHERE role = 'admin'").fetchone()[0]
    with psycopg.connect(_cruda(dominio)) as c:
        modulos = c.execute("SELECT count(*), count(DISTINCT modulo) FROM medlibra_modulos").fetchone()
    assert admins == 1, f"{admins} admins: el hook de arranque corrio sin candado en los dos workers"
    assert modulos == (len(TODOS_LOS_MODULOS), len(TODOS_LOS_MODULOS))
