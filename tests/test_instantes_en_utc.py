"""Los instantes salen por la API en UTC, no en la zona de la sesión de la base.

🔴 **De dónde sale esta guarda.** El 2026-08-23 se le puso la zona de Argentina
al contenedor de PostgreSQL, para que el reloj de la base y el del proceso
coincidan. Efecto colateral: un `timestamptz` se renderiza en la zona de la
**sesión del servidor**, así que el mismo turno pasó de `2026-07-20T13:00:00Z` a
`2026-07-20T10:00:00-03:00`. Mismo instante, otro texto — ISO 8601 válido, pero
un formato de salida decidido por una variable de entorno de un contenedor.

Los tests de agenda lo agarraron. El resto **no lo cubría nadie**: habrían
cambiado de formato en silencio.

Por eso hay dos tests y no uno:

  - uno de comportamiento, que serializa de verdad y mira el texto;
  - uno estructural, que recorre los modelos que los routers declaran como
    `response_model` y exige `InstanteUTC`. Ese es el que cubre al endpoint que
    todavía no existe — sin él, la guarda protege "los de entonces" y el próximo
    nace sin cobertura.

**Sólo lo que sale.** Los modelos de ENTRADA quedan afuera a propósito: el
serializador no interviene al parsear, y exigirlo ahí sería pedir una anotación
que no hace nada. La propiedad que importa es qué texto emite la API, así que se
mira lo que las rutas declaran como respuesta, no toda clase que herede de
`BaseModel`.
"""
from __future__ import annotations

import importlib
import pkgutil
import typing
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from app.routers._instantes import InstanteUTC

#: Los campos que vienen de una columna `DateTime(timezone=True)`.
CAMPOS_DE_INSTANTE = {"created_at", "starts_at", "ends_at"}


class _Modelo(BaseModel):
    cuando: InstanteUTC


@pytest.mark.parametrize(
    "valor",
    [
        pytest.param(datetime(2026, 7, 20, 10, 0, tzinfo=timezone(timedelta(hours=-3))),
                     id="como lo devuelve PostgreSQL con la sesion en AR"),
        pytest.param(datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
                     id="como lo devolvia con la sesion en UTC"),
        pytest.param(datetime(2026, 7, 20, 13, 0),
                     id="naive, como lo devuelve SQLite"),
    ],
)
def test_el_mismo_instante_sale_siempre_igual(valor):
    """Los tres son el MISMO momento y tienen que dar el mismo texto.

    El primer caso es el que rompia: sin normalizar salia
    `2026-07-20T10:00:00-03:00`.
    """
    assert _Modelo(cuando=valor).model_dump_json() == '{"cuando":"2026-07-20T13:00:00Z"}'


def _modelos_devueltos():
    """Los `BaseModel` que las rutas declaran como `response_model`.

    Se desenvuelven los genericos (`list[X]`, `X | None`), que es como estan
    declaradas la mitad de las rutas.
    """
    import app.routers as paquete

    vistos = set()
    for info in pkgutil.iter_modules(paquete.__path__):
        modulo = importlib.import_module("app.routers." + info.name)
        router = getattr(modulo, "router", None)
        if router is None:
            continue
        for ruta in getattr(router, "routes", []):
            pendientes = [getattr(ruta, "response_model", None)]
            while pendientes:
                anotacion = pendientes.pop()
                if anotacion is None:
                    continue
                argumentos = typing.get_args(anotacion)
                if argumentos:
                    pendientes.extend(argumentos)
                    continue
                if (isinstance(anotacion, type) and issubclass(anotacion, BaseModel)
                        and anotacion not in vistos):
                    vistos.add(anotacion)
                    yield info.name, anotacion


def _sin_normalizar():
    return [
        "app/routers/%s.py :: %s.%s" % (archivo, modelo.__name__, campo)
        for archivo, modelo in _modelos_devueltos()
        for campo, info in modelo.model_fields.items()
        if campo in CAMPOS_DE_INSTANTE and info.annotation is datetime
        and not any(getattr(m, "func", None) is not None for m in info.metadata)
    ]


def test_hay_modelos_de_respuesta_para_revisar():
    """Un cero esperado necesita un positivo que lo respalde.

    Si `_modelos_devueltos()` dejara de encontrar rutas --- porque cambio la
    forma de declararlas, o porque el import fallo en silencio --- el test de
    abajo pasaria con la lista vacia y no estaria mirando nada.
    """
    conocidos = {modelo.__name__ for _, modelo in _modelos_devueltos()}
    assert len(conocidos) >= 5, conocidos
    assert any(
        campo in CAMPOS_DE_INSTANTE
        for _, modelo in _modelos_devueltos()
        for campo in modelo.model_fields
    ), "ninguno de los modelos de respuesta tiene un campo de instante: el filtro no mide nada"


def test_ningun_modelo_de_respuesta_declara_un_instante_sin_normalizar():
    """La guarda que cubre al endpoint que todavia no se escribio."""
    crudos = _sin_normalizar()
    assert crudos == [], (
        "estos campos salen con la zona de la sesion de PostgreSQL; "
        "declararlos `InstanteUTC` (ver app/routers/_instantes.py): "
        + ", ".join(crudos)
    )
