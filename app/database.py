"""Módulos y add-ons: el contrato que espera el backoffice.

🔴 El backoffice prende/apaga add-ons y lee su estado corriendo un snippet
DENTRO de este contenedor (`libracore.admin.services`), y ese snippet importa
`app.database.get_modulos` / `app.database.set_addon`. Es el contrato que
MedLibra tiene que cumplir desde que declaró `ADDONS = {"resguardo_externo"}` en
`plans.py`.

**Desde ADR-043 (2026-10-25) no delegan en `libracore.db.modulos`**, que lee y
escribe una tabla llamada `modulos`: la tabla de este producto se renombró a
`medlibra_modulos` (migración 0023) porque LibraCore tiene una `modulos` de otra
forma y con una sola base por producto no pueden llamarse igual. Se lee y se
escribe la del producto, la que consulta `ModuleRepository` en cada request, y
con eso el contrato sirve igual con una base o con dos (el motor miraba la base
a la que apuntara `libracore.db.core`, y adentro de la app no era la del
dominio: había que cortar con un error).

El paso a `libracore.db.modulos` —que las filas de `medlibra_modulos` pasen a la
`modulos` del motor y esta función vuelva a delegar— se hace **después de unir
las bases**, no antes (ver ADR-043). Hasta entonces la fuente de verdad es esta
tabla y nadie escribe la del motor.

⚠️ No confundir con `libragenda.database`, que es la engine factory del dominio
(`app/main.py` la importa como `configure`/`get_engine`). Ésta no toca esa
configuración: abre su propio engine, lo usa y lo suelta.
"""
from libracore.db.url_de_instancia import url_de_instancia
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import PREFIJO
from .services.modules import ModuleRepository, ModuleRow


def _con_la_tabla_del_dominio(operacion):
    """Corre `operacion(session_factory)` contra la base del DOMINIO de esta instancia y suelta el engine.

    La URL sale de `url_de_instancia`, el mismo lugar del que la lee `app/asgi.py`: si este contrato
    resolviera la base por su cuenta, podría escribir en una y que la app sirva otra, sin fallar.
    """
    url = url_de_instancia(PREFIJO, requerida=True).replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        return operacion(sessionmaker(engine, expire_on_commit=False))
    finally:
        engine.dispose()


def get_modulos() -> dict[str, bool]:
    """`{modulo: habilitado}` de esta instancia."""
    return _con_la_tabla_del_dominio(lambda sesiones: ModuleRepository(sesiones).get_all())


def set_addon(nombre: str, habilitado: bool) -> None:
    """Prende/apaga un add-on suelto en esta instancia. Efecto inmediato:
    `require_module` pregunta a `ModuleRepository.is_enabled` en cada request,
    y ése lee la fila en cada llamada, sin cache.

    Igual que la del motor: crea la fila con `plan="addon"` si falta y **sólo cambia
    `habilitado`** si existe (nunca la etiqueta de plan). No valida que `nombre` sea
    un add-on: eso lo hace el backoffice contra `plans.ADDONS` antes de llegar acá
    (`libracore.admin.services.set_addon`)."""
    def _escribir(sesiones: sessionmaker) -> None:
        with sesiones.begin() as sesion:
            fila = sesion.get(ModuleRow, nombre)
            if fila is None:
                sesion.add(ModuleRow(modulo=nombre, habilitado=habilitado, plan="addon"))
            else:
                fila.habilitado = habilitado

    _con_la_tabla_del_dominio(_escribir)
