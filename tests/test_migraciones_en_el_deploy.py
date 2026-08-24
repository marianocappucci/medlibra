"""Que las dos cadenas de Alembic esten declaradas, y que la imagen las lleve.

🔴 **Tener el mecanismo no es tenerlo invocado.** Hasta el 2026-08-24 ningun
paso del deploy corria las migraciones de este producto: los `alembic upgrade`
del repo estaban en la suite y en los scripts de dev, y el esquema de las
instancias vivas lo armaba `Base.metadata.create_all()` al bootear. La linea de
`app/main.py` que dice *"demo only; deploy uses Alembic"* era, literalmente,
falsa.

Lo que se fija aca es lo que se rompe en silencio:

1. que **los dos** scripts declaren las migraciones —el `panel_admin.py` las
   corre al actualizar y el `nuevo_cliente.py` al dar de alta; que uno solo las
   tenga es peor que ninguno, porque el alta y el deploy dejarian la instancia
   en estados distintos—;
2. que la cadena de **LibraGenda vaya primero** —las revisiones de este producto
   tienen FK contra sus tablas—;
3. y que la imagen lleve con que correrlas.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
ESPERADO = (("libragenda-migrar", "upgrade"), ("alembic", "upgrade", "head"))


def _config_de(script: str):
    """La `ProductConfig` que deja el `configure()` de ese script al importarlo.

    Se importa en un proceso aparte: `configure()` escribe un global del motor y
    los dos scripts lo pisarian entre si, dando un verde que no dice de cual de
    los dos salio.
    """
    codigo = (
        "import json, sys;"
        f"sys.path.insert(0, {str(RAIZ)!r});"
        f"sys.path.insert(0, {str(RAIZ / 'scripts')!r});"
        f"import importlib; importlib.import_module({script!r});"
        "from libracore.provisioning import get_config;"
        "print(json.dumps(get_config().migraciones))"
    )
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                       text=True, cwd=str(RAIZ))
    assert r.returncode == 0, r.stderr[-2000:]
    import json
    return tuple(tuple(c) for c in json.loads(r.stdout))


@pytest.mark.parametrize("script", ["panel_admin", "nuevo_cliente"])
def test_los_dos_scripts_declaran_las_dos_cadenas(script):
    assert _config_de(script) == ESPERADO


def test_la_cadena_de_libragenda_va_primero():
    """Explicito ademas del `==` de arriba: si manana se agrega un comando, el
    `==` se cae por el motivo equivocado y esto dice cual era la afirmacion."""
    comandos = _config_de("panel_admin")
    assert len(comandos) == 2, f"esperaba las dos cadenas, llegaron {comandos}"
    assert comandos[0][0] == "libragenda-migrar"
    assert comandos[-1][:2] == ("alembic", "upgrade")


def test_el_pin_de_libragenda_trae_el_comando_instalable():
    """`libragenda-migrar` es un `[project.scripts]` que aparecio en la v0.10.0.
    Con un pin anterior, el comando no existe en la imagen y el deploy se cae en
    el primer paso --- verificado en los contenedores vivos el 2026-08-24, donde
    con el pin v0.9.0 no estaba."""
    pins = _pins()
    assert _version(pins["libragenda"]) >= (0, 10, 0), pins["libragenda"]


def test_el_pin_de_libracore_acepta_una_secuencia_de_comandos():
    """El campo `migraciones` de la v1.48.0 era UN comando; la v1.51.0 es la que
    acepta varios. Con un pin anterior, `configure()` no sabe que hacer con la
    tupla anidada."""
    pins = _pins()
    assert _version(pins["libracore"]) >= (1, 51, 0), pins["libracore"]


def _pins() -> dict:
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    salida = {}
    for dep in datos["project"]["dependencies"]:
        for motor in ("libracore", "libragenda"):
            if dep.startswith(motor + " @"):
                salida[motor] = dep.rsplit("@", 1)[-1]
    return salida


def _version(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def test_la_imagen_lleva_con_que_correrlas():
    """El `alembic upgrade head` corre DENTRO del contenedor, contra
    `/app/alembic.ini`. Si el `.dockerignore` se llevara `migrations/`, el
    deploy fallaria recien en produccion y con un error de alembic que no nombra
    la causa."""
    assert (RAIZ / "alembic.ini").is_file()
    assert list((RAIZ / "migrations" / "versions").glob("*.py"))

    ignore = RAIZ / ".dockerignore"
    if ignore.is_file():
        lineas = [l.strip() for l in ignore.read_text(encoding="utf-8").splitlines()]
        for prohibido in ("migrations", "migrations/", "alembic.ini"):
            assert prohibido not in lineas, f".dockerignore excluye {prohibido}"
