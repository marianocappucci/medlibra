"""Que `AUDITABLES` no nombre modelos que ya no existen.

La lista blanca de `app/auditoria.py` se indexa **por nombre de clase**, no por
la clase, para no importar los modulos de servicio desde ahi. El precio de esa
decision --que es correcta-- es que una entrada muerta **no rompe nada**: nunca
matchea, no hay `ImportError`, no hay atributo que falte. Se queda ahi diciendo
que algo se audita.

🔴 **Y no es solo un comentario mentiroso: se ve en la pantalla.**
`build_logs_router` de LibraAuth arma el selector de entidades con
`sorted(set(auditables.values()))` y **no** con un `SELECT DISTINCT` sobre el
log --a proposito, para ofrecer entidades que todavia no tuvieron actividad--.
O sea que una entrada muerta aparece como filtro y **no puede devolver nada
nunca**, indistinguible de "todavia no se uso".

**Paso de verdad, en LibraDesk**: la revision `0031` dropeo su tabla
`servicios` el 2026-08-17 y borro el modelo, y la entrada siguio en la lista dos
dias, afirmando que el precio de lista de lo que se cotiza se auditaba. Se
encontro a mano el 2026-08-19; este archivo es el guard que se escribio ahi
mismo, portado a MedLibra el mismo dia.

🔑 **Aca los modelos vienen de dos lados**: diez de LibraGenda (`ClientRow`, `AppointmentRow`, ...) y catorce propios, incluidos los clinicos. Los dos cuelgan
del **mismo** `Base` de `libragenda.sqlalchemy_repository`, asi que un solo
registro los cubre a todos --que es justamente lo que hace que este chequeo sea
barato--.
"""
import sys

from libragenda.sqlalchemy_repository import Base

from app.auditoria import AUDITABLES


def _modelos_vivos() -> set:
    """Los nombres de clase de los modelos mapeados, del producto y del motor.

    Se pide `admin_client` en los tests para que la app este construida: los
    modelos se registran al importarse sus modulos, y `create_app` los importa.
    """
    return {mapper.class_.__name__ for mapper in Base.registry.mappers}


def test_toda_entrada_de_auditables_nombra_un_modelo_que_existe(admin_client):
    muertas = sorted(set(AUDITABLES) - _modelos_vivos())
    assert not muertas, (
        f"`AUDITABLES` nombra {len(muertas)} modelo(s) que ya no existen: "
        f"{muertas}. Una entrada muerta no rompe nada --la lista se indexa por "
        f"nombre de clase-- pero deja su entidad ofrecida como filtro en la "
        f"pantalla de Logs, donde no puede devolver nada nunca. Si se dropeo el "
        f"modelo, o si LibraGenda le cambio el nombre a la clase, saca tambien "
        f"su entrada."
    )


def test_el_guard_puede_fallar(admin_client):
    """Control positivo: sin esto, el test de arriba pasaria igual con la lista
    vacia, con `_modelos_vivos()` devolviendo el universo, o con cualquier bug
    que haga que la resta de siempre vacia."""
    vivos = _modelos_vivos()
    assert "ClientRow" in vivos, "el registro de modelos no se poblo"
    assert sorted({"ModeloQueNoExiste", "ClientRow"} - vivos) == ["ModeloQueNoExiste"]


def test_la_lista_no_quedo_vacia(admin_client):
    """La otra forma de que el guard de arriba pase sin decir nada: que alguien
    vacie `AUDITABLES`. Veinticuatro entidades al 2026-08-19."""
    assert len(AUDITABLES) >= 24, AUDITABLES


def test_el_registro_cubre_las_dos_procedencias(admin_client):
    """Que el `Base` compartido alcance de verdad: si LibraGenda pasara a tener
    un registro propio, `_modelos_vivos()` dejaria de ver sus modelos y el
    primer test se pondria rojo con media lista. Mejor que diga por que."""
    vivos = _modelos_vivos()
    assert "AppointmentRow" in vivos, "no se ven los modelos de LibraGenda"
    assert "PatientRow" in vivos, "no se ven los modelos propios"
    assert sys.modules.get("libragenda.sqlalchemy_repository") is not None
