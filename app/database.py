"""Módulos y add-ons: el contrato que espera el backoffice.

🔴 El backoffice prende/apaga add-ons y lee su estado corriendo un snippet
DENTRO de este contenedor (`libracore.admin.services`), y ese snippet importa
`app.database.get_modulos` / `app.database.set_addon`. Es el contrato que
MedLibra tiene que cumplir desde que declaró `ADDONS = {"resguardo_externo"}` en
`plans.py`. Hasta hoy **este módulo no existía**: el `docker exec` habría muerto
con `ModuleNotFoundError`, y el backoffice lo muestra como "no se pudo leer".

Delegan en `libracore.db.modulos`, que es donde vive la implementación única
de la familia. Acá no se copia lógica: se cumple el contrato. Mismo patrón que
`app/database.py` de LibraDesk, con una diferencia que en este producto no es
opcional — ver `_asegurar_core_configurado`.

⚠️ No confundir con `libragenda.database`, que es la engine factory del dominio
(`app/main.py` la importa como `configure`/`get_engine`). Ésta no configura
ningún engine de SQLAlchemy.
"""
from libracore.db import core as libracore_core
from libracore.db.url_de_instancia import url_de_instancia

#: Si el `configure()` del core lo hizo ESTE módulo, contra la base del dominio.
#: Hace falta para distinguir "lo configuré yo" de "lo configuró la app", que en
#: este producto apuntan a bases distintas.
_core_apuntado_al_dominio = False


def _asegurar_core_configurado() -> None:
    """Apunta `libracore.db.core` a la base del DOMINIO de esta instancia.

    🔴 **En MedLibra la tabla `modulos` NO vive en la base de LibraCore.** Son
    dos bases (ver `_instancia_a_respaldar` en `app/main.py`): la del dominio
    (`MEDLIBRA_DATABASE_URL` / `DATABASE_URL`, base `medlibra`), donde está la
    `modulos` que lee `ModuleRepository`, y la de LibraCore
    (`MEDLIBRA_LIBRACORE_DATABASE_URL`, base `medlibra_core`), que tiene su
    propia `modulos` **vacía** — la crea `init_core_schema()` y nadie la lee.

    Por eso el patrón de LibraDesk no alcanza tal cual. Allá "el core ya está
    configurado" significa "apunta a la base correcta"; acá no:

    - Bajo `docker exec python3 -c "from app.database import get_modulos"` —el
      único camino por el que se llama esto— no corrió ningún arranque, el core
      está sin configurar y se lo apunta al dominio. Es el caso que tiene que
      resolverse solo, sin pedirle al backoffice que bootee la app entera.
    - **Dentro de la app**, `create_app()` configura el core contra
      `medlibra_core` (`libracore_setup.configure(libracore_db_path)`), no
      contra el dominio. Delegar ahí leería la tabla vacía y devolvería `{}`:
      el backoffice mostraría el add-on apagado con el add-on prendido. En vez
      de esa mentira, se corta con un error que dice qué usar. Adentro de la
      app el estado de un módulo se pregunta a `app.state.modules`.

    Tampoco se reconfigura el core a ciegas: le pisaría la base de usuarios y
    caja a una app viva.
    """
    global _core_apuntado_al_dominio
    if _core_apuntado_al_dominio:
        return
    if libracore_core.esta_configurado():
        raise RuntimeError(
            "app.database.get_modulos/set_addon son para el backoffice (docker exec), "
            "fuera del arranque de la app. En este proceso libracore.db.core ya apunta "
            "a la base de LibraCore (medlibra_core), y la tabla `modulos` que manda "
            "vive en la del dominio: usar app.state.modules."
        )
    libracore_core.configure(url_de_instancia("medlibra", requerida=True))
    _core_apuntado_al_dominio = True


def get_modulos() -> dict[str, bool]:
    """`{modulo: habilitado}` de esta instancia. Ver `_asegurar_core_configurado`."""
    _asegurar_core_configurado()
    from libracore.db.modulos import get_modulos as _get_modulos

    return _get_modulos()


def set_addon(nombre: str, habilitado: bool) -> None:
    """Prende/apaga un add-on suelto en esta instancia. Efecto inmediato:
    `require_module` pregunta a `ModuleRepository.is_enabled` en cada request,
    y ése lee la fila en cada llamada, sin cache.

    No valida que `nombre` sea un add-on: eso lo hace el backoffice contra
    `plans.ADDONS` antes de llegar acá (`libracore.admin.services.set_addon`)."""
    _asegurar_core_configurado()
    from libracore.db.modulos import set_addon as _set_addon

    _set_addon(nombre, habilitado)
