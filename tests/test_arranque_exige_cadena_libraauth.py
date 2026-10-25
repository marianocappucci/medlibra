"""El arranque exige la cadena de LibraAuth en vez de crear las tablas.

Desde libraauth v0.45.0 (2026-09-17) `create_app()` ya no corre
`AuthBase.metadata.create_all()` sobre la base de LibraCore: llama a
`exigir_schema_al_dia`. Se fija que sin la cadena la app no arranca y el error
nombra el comando de `libraauth-migrar` que corresponde a la instancia (`--base
dominio` con una sola base, la de la suite y la del deploy desde el ADR-046; `--base
core` si alguien todavía declara la variable del core con otra base, ver
`Config.base_de_auth`), con el control de que con la cadena sí arranca (lo hace
toda la suite).
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


def test_sin_la_cadena_la_app_no_arranca_y_dice_el_comando():
    # El fixture autouse ya corrió la cadena sobre la base (la única): se le
    # borra la tabla de versión para simular una base que nunca migró.
    with psycopg.connect(url_libracore(), autocommit=True) as c:
        c.execute(f"DROP TABLE {TABLA_DE_VERSION}")
    with pytest.raises(SchemaDesactualizado) as e:
        create_app(fresh_database_url())
    assert COMANDO in str(e.value)


def test_la_guarda_dice_el_mismo_comando_que_declara_el_deploy():
    """Lo que dice el error es, palabra por palabra, lo que `scripts/panel_admin.py` corre (`--base dominio`)."""
    fuente = (RAIZ / "scripts" / "panel_admin.py").read_text(encoding="utf-8")
    declarado = re.search(r'\("libraauth-migrar",([^)]*)\)', fuente)
    assert declarado, "scripts/panel_admin.py no declara libraauth-migrar"
    partes = ["libraauth-migrar"] + re.findall(r'"([^"]+)"', declarado.group(1))
    assert " ".join(partes) == COMANDO, "la guarda y el deploy hablan de comandos distintos"


def test_control_con_la_cadena_arranca():
    assert create_app(fresh_database_url()) is not None
