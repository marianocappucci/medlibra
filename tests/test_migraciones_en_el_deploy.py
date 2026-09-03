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
#: Las TRES cadenas, en orden. La del medio entró el 2026-08-25: el schema de
#: LibraCore de este producto vive en `medlibra_core`, una base aparte, y su
#: cadena no la corría nadie porque las migraciones del motor no viajaban en el
#: wheel. `libracore-migrar` la resuelve por la variable de la instancia y NO
#: por `DATABASE_URL`, que apunta al dominio.
ESPERADO = (
    ("libragenda-migrar", "upgrade"),
    ("libracore-migrar", "upgrade", "--prefijo", "medlibra"),
    ("alembic", "upgrade", "head"),
)


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
def test_los_dos_scripts_declaran_LAS_TRES_cadenas(script):
    assert _config_de(script) == ESPERADO


def test_el_orden_de_las_cadenas_es_el_que_importa():
    """Explicito ademas del `==` de arriba: si manana se agrega un comando, el
    `==` se cae por el motivo equivocado y esto dice cual era la afirmacion.

    El orden no es decorativo:

    - **LibraGenda primero** porque las revisiones de este producto tienen FK
      contra sus tablas.
    - **La propia al final**, por lo mismo.
    - **LibraCore en el medio**: corre contra otra base, asi que su posicion es
      libre, pero fijarla evita que el `==` de arriba sea la unica afirmacion.
    """
    comandos = _config_de("panel_admin")
    assert len(comandos) == 3, f"esperaba las tres cadenas, llegaron {comandos}"
    assert comandos[0][0] == "libragenda-migrar"
    assert comandos[1][0] == "libracore-migrar"
    assert comandos[-1][:2] == ("alembic", "upgrade")

    # 🔑 El `--prefijo` es lo que hace que `libracore-migrar` NO tome
    # `DATABASE_URL` --- que en este contenedor apunta al dominio --- sino la
    # variable de la base del core. Sin el, migraria la base equivocada y
    # devolveria exito.
    assert "--prefijo" in comandos[1], (
        "sin `--prefijo`, `libracore-migrar` cae a DATABASE_URL, que aca es la "
        "base del DOMINIO y no la del core")


def test_el_pin_de_libragenda_trae_el_comando_instalable():
    """`libragenda-migrar` es un `[project.scripts]` que aparecio en la v0.9.1.
    Con un pin anterior, el comando no existe en la imagen y el deploy se cae en
    el primer paso --- verificado en los contenedores vivos el 2026-08-24, donde
    con el pin v0.9.0 no estaba."""
    pins = _pins()
    assert _version(pins["libragenda"]) >= (0, 9, 1), pins["libragenda"]


def test_el_adaptador_de_turnos_acompana_el_pin_de_libragenda():
    """Desde `v0.10.0` el scheduler crea con `repository.reserve(...)` (la reserva
    atomica, ADR-013), no con `save`. El adaptador de hora local de este producto
    ---`_TurnosEnHoraLocal`--- tiene que ofrecer `reserve` o todos los altas de
    turno se caen con `AttributeError: ... has no attribute 'reserve'`.

    Reemplaza al guard que frenaba el pin en `< v0.10.0` hasta que estuviera
    implementado: se adapto el 2026-09-03 (el `reserve` traduce hora local <-> UTC
    envolviendo el validador). Este test lo sostiene desde el otro lado --- si el
    metodo se borra, o el pin sube sin el, el CI lo agarra --- y por eso mira el
    codigo real y no solo el numero del pin.
    """
    from app.services.appointments import _TurnosEnHoraLocal

    pins = _pins()
    if _version(pins["libragenda"]) >= (0, 10, 0):
        assert hasattr(_TurnosEnHoraLocal, "reserve"), (
            "el pin de libragenda esta en v0.10.0+, que exige `reserve()` en "
            "`_TurnosEnHoraLocal`; sin el, los altas de turno se caen en runtime")


def test_el_pin_de_libracore_trae_el_comando_que_se_declara():
    """El pin y la declaracion viajan juntos, y el minimo subio dos veces.

    La `v1.48.0` introdujo `migraciones` como UN comando; la `v1.51.0` acepta
    varios --- con un pin anterior, `configure()` no sabe que hacer con la tupla
    anidada ---. Y desde el 2026-08-25 se declara `libracore-migrar`, que es un
    `[project.scripts]` que **aparece en la v1.53.0**: con un pin anterior el
    comando no existe en la imagen y el primer paso del deploy se cae.

    Es el mismo control que `test_el_pin_de_libragenda_trae_el_comando_instalable`
    hace del otro lado.
    """
    pins = _pins()
    assert _version(pins["libracore"]) >= (1, 53, 0), pins["libracore"]


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
