"""El provisioning de este producto, atado al código que corre.

Nace el 2026-08-24, de medir los ocho productos de la familia: **seis de ocho**
tenían los dos `configure()` diciendo cosas distintas, siempre en el mismo campo.
Los dos que no divergían eran justamente los dos que ya tenían este archivo.
"""

import importlib
import pathlib
import re

import pytest


def test_los_dos_scripts_configuran_LO_MISMO():
    """El desvío que el comentario de los dos archivos promete que no existe.

    `scripts/nuevo_cliente.py` y `scripts/panel_admin.py` llaman los dos a
    `configure()`, que pisa un `_cfg` **global**, y `libracore.admin.services`
    importa los dos módulos en el mismo proceso. Si dicen cosas distintas, cuál
    gana depende del orden de los imports — o sea que la misma operación sale
    distinta según qué se haya importado antes en ese proceso.

    **Este test nace en rojo.** Al escribirlo, `panel_admin.py` pasaba
    `backup_zip=True` y `nuevo_cliente.py` no.

    Se compara la configuración **entera** con `asdict`, no campo por campo: un
    test que mirara sólo `backup_zip` dejaría pasar el próximo desvío, que va a
    ser en otro campo.
    """
    from dataclasses import asdict

    from libracore.provisioning import get_config

    def config_de(script):
        importlib.reload(importlib.import_module(f"scripts.{script}"))
        return asdict(get_config())

    uno = config_de("nuevo_cliente")
    otro = config_de("panel_admin")

    distintos = {k: (uno[k], otro[k]) for k in uno if uno[k] != otro[k]}
    assert not distintos, f"los dos scripts configuran distinto: {distintos}"


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_el_deploy_declara_las_migraciones_que_este_repo_tiene(script):
    """Un producto con revisiones de Alembic tiene que declararlas.

    **Por qué existe.** El paso lo trae el motor desde LibraCore `v1.48.0`,
    pero `migraciones` es opcional y su default es vacío — así que un producto
    que no la declara no ve ningún paso y su deploy pasa de largo, en silencio.
    Le pasó a LibraCargo el 2026-08-24: la revisión nueva viajó a `main`
    adentro de la imagen, `actualizar` salió con código 0, y las instancias
    quedaron con el código nuevo sobre el esquema viejo.

    🔑 **Ningún chequeo de salud lo agarra.** El proceso arranca perfecto; el
    error recién ocurre cuando alguien consulta la tabla.

    La condición sale **del repo**, no de un literal: si hay revisiones en
    `migrations/versions/`, tiene que haber comandos. Un literal acá sería una
    tercera copia que puede divergir igual que las otras dos.
    """
    from libracore.provisioning import get_config

    raiz = pathlib.Path(__file__).parent.parent
    revisiones = sorted((raiz / "migrations" / "versions").glob("*.py"))

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    declarados = get_config().migraciones

    if not revisiones:
        return  # sin cadena propia no hay nada que correr

    assert declarados, (
        f"este repo tiene {len(revisiones)} revisiones de Alembic y "
        f"scripts/{script}.py no declara `migraciones`: el deploy las va a "
        "saltear en silencio."
    )
    # 🔑 **Acá se aserta lo que el DEPLOY hace con el valor, no el valor.**
    # Comparar `declarados` contra la tupla que uno escribió en el otro archivo
    # se cumple por construcción y no prueba nada. Estas dos líneas son
    # textualmente lo que hace `cmd_actualizar` por cada comando: lo imprime
    # con `" ".join(...)` y lo splatea en el `compose run`. Con la forma plana
    # el `join` revienta acá, que es donde tiene que reventar.
    for comando in declarados:
        assert not isinstance(comando, str), (
            f"scripts/{script}.py declara {declarados!r} en forma PLANA. El "
            "deploy la iteraría carácter por carácter. Anidala: "
            "migraciones=((...),)"
        )
        " ".join(comando)  # lo que hace cmd_actualizar antes de correrlo

    assert any("alembic" in c for c in declarados), (
        f"scripts/{script}.py declara {declarados!r}, que no incluye el "
        "`alembic` de la cadena propia de este repo."
    )


def _bloque_del_servicio_de_dev() -> str:
    """El bloque del servicio `*-dev` del compose del repo, como texto.

    Sin `yaml`: no es dependencia de este repo ni de sus tests, y sumar una
    para leer una línea sería peor que recortar el bloque a mano. El corte es
    por indentación —un servicio arranca con dos espacios y su cuerpo tiene
    más—, que es exactamente lo que el archivo garantiza.
    """
    raiz = pathlib.Path(__file__).parent.parent
    lineas = (raiz / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    servicios = [i for i, linea in enumerate(lineas)
                 if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", linea)]
    inicio = next((i for i in servicios
                   if lineas[i].strip().rstrip(":").endswith("-dev")), None)
    assert inicio is not None, (
        "el compose del repo no declara ningún servicio `*-dev`: este test "
        "está mirando un archivo que ya no tiene la forma que supone.")
    fin = next((i for i in servicios if i > inicio), len(lineas))
    return "\n".join(lineas[inicio:fin])


def _comando_de_arranque_de_dev() -> str:
    """El **valor** del `command:` del servicio de dev, y nada más.

    🔴 **La primera versión de este test buscaba en el bloque entero, y eso
    pasaba en verde con el paso de migraciones sacado del `command:` y dejado
    en un comentario.** Medido el 2026-08-25, no supuesto: un comentario que
    menciona `alembic upgrade head` no lo corre. Buscar en el bloque también
    dejaba que un `ports: - "8086:8000"` satisficiera un token del comando de
    arranque, que es la misma clase de falso verde.

    Un comentario no matchea `^\s+command:` porque el `#` va antes de la clave.
    """
    bloque = _bloque_del_servicio_de_dev()
    m = re.search(r"^\s+command:\s*(\S.*)$", bloque, re.MULTILINE)
    assert m, (
        "el servicio de dev del compose no declara `command:`. Si el arranque "
        "pasó a otra forma, este test hay que reescribirlo — no borrarlo.")
    return m.group(1).strip()


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_la_instancia_de_dev_corre_las_mismas_migraciones_que_el_deploy(script):
    """El otro camino, el que `cmd_actualizar` no toca.

    🔴 **La declaración de `migraciones` no cubre `dev`.** El motor corre esos
    comandos al actualizar las instancias de cliente y la demo, que son las que
    el panel administra. La de `dev` la levanta el `docker-compose.yml` de este
    repo, y hasta el 2026-08-25 ahí no había ningún paso de Alembic en ninguno
    de los cinco productos de la familia que usan Alembic. Se descubrió porque
    `libracargo-dev` apareció con la base una revisión atrás del código, con el
    chequeo de salud en 200.

    Lo que se aserta es que las dos puntas digan **lo mismo y en el mismo
    orden**. El modo de fallar de esto no es que alguien borre el `command:`,
    es que agregue una segunda cadena en `scripts/` y se olvide del compose:
    ahí `dev` migraría de menos y el error culparía a la revisión equivocada.

    Se lee el compose como texto y no se compara contra un literal escrito acá:
    un literal sería una tercera copia, con exactamente el mismo problema.
    """
    from libracore.provisioning import get_config

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    declarados = get_config().migraciones
    if not declarados:
        return  # sin cadena declarada no hay nada que exigirle al compose

    arranque = _comando_de_arranque_de_dev()
    cursor = 0
    for comando in declarados:
        texto = " ".join(comando)
        pos = arranque.find(texto, cursor)
        assert pos != -1, (
            f"scripts/{script}.py declara `{texto}` y el servicio de dev del "
            "compose no lo corre" + (" en ese orden" if cursor else "") + ": "
            "la instancia de dev va a quedar con el código nuevo sobre el "
            "esquema viejo, que es lo que le pasó a LibraCargo el 2026-08-25."
        )
        cursor = pos + len(texto)
