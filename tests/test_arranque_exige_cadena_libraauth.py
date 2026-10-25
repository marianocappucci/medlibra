"""El arranque exige la cadena de LibraAuth en vez de crear las tablas.

Desde libraauth v0.45.0 (2026-09-17) `create_app()` ya no corre
`AuthBase.metadata.create_all()` sobre la base de LibraCore: llama a
`exigir_schema_al_dia`. Se fija que sin la cadena la app no arranca y el error
nombra el comando de `libraauth-migrar` que corresponde a la instancia (`--base
dominio` con una sola base, la de la suite; `--base core` con dos, ver
`Config.base_de_auth`), con el control de que con la cadena sí arranca (lo hace
toda la suite). El deploy declara `--base core`, que en una sola base va al mismo
lugar (ADR-044): es el mismo comando salvo el valor de `--base`.
"""
import re
from pathlib import Path

import psycopg
import pytest
from libraauth.migrar import TABLA_DE_VERSION, SchemaDesactualizado
from motor_de_test import fresh_database_url, url_libracore

from app.main import create_app

RAIZ = Path(__file__).resolve().parent.parent
#: Lo que dice el error en la suite, que es de una sola base (`Config.base_de_auth == "dominio"`).
COMANDO = "libraauth-migrar upgrade --prefijo medlibra --base dominio"
#: Lo que declara el deploy: `core` resuelve a la base del core si la instancia la tiene (la demo) y, si no, a la
#: del dominio. Ver el comentario de `scripts/panel_admin.py`.
COMANDO_DEL_DEPLOY = "libraauth-migrar upgrade --prefijo medlibra --base core"


def test_sin_la_cadena_la_app_no_arranca_y_dice_el_comando():
    # El fixture autouse ya corrió la cadena sobre la base (la única): se le
    # borra la tabla de versión para simular una base que nunca migró.
    with psycopg.connect(url_libracore(), autocommit=True) as c:
        c.execute(f"DROP TABLE {TABLA_DE_VERSION}")
    with pytest.raises(SchemaDesactualizado) as e:
        create_app(fresh_database_url())
    assert COMANDO in str(e.value)


def test_la_guarda_dice_el_mismo_comando_que_declara_el_deploy():
    fuente = (RAIZ / "scripts" / "panel_admin.py").read_text(encoding="utf-8")
    declarado = re.search(r'\("libraauth-migrar",([^)]*)\)', fuente)
    assert declarado, "scripts/panel_admin.py no declara libraauth-migrar"
    partes = ["libraauth-migrar"] + re.findall(r'"([^"]+)"', declarado.group(1))
    assert " ".join(partes) == COMANDO_DEL_DEPLOY

    def sin_base(comando: str) -> str:
        return re.sub(r" --base \w+", "", comando)

    assert sin_base(COMANDO) == sin_base(COMANDO_DEL_DEPLOY), "la guarda y el deploy hablan de comandos distintos"


def test_control_con_la_cadena_arranca():
    assert create_app(fresh_database_url()) is not None
