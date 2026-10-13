"""`app.asgi:app` con la ventana de la carrera ensanchada, para `test_varios_procesos.py`.

Sin el candado de `una_vez_al_arrancar`, la carrera es «el admin no existe» (`repo.list()` vacio) -> «crearlo»: una ventana
de milisegundos que dos workers arrancando juntos casi nunca pisan en una maquina rapida. Eso hace que el test pase aunque
el candado no este, y un test que no se pone rojo sin el arreglo no cuida nada. Aca la ventana dura `VENTANA` segundos
cuando la lista esta vacia (y solo entonces: el que llega segundo, ya con el admin creado, no espera).

Lo que se mide sigue siendo el codigo del producto: esto solo agranda el tiempo entre mirar y escribir.
"""
import time

from libraauth.repository import UserRepository

VENTANA = 3.0

_lista_original = UserRepository.list


def _lista_lenta(self, *args, **kwargs):
    usuarios = _lista_original(self, *args, **kwargs)
    if not usuarios:
        time.sleep(VENTANA)
    return usuarios


UserRepository.list = _lista_lenta

from app.asgi import app  # noqa: E402,F401  (lo consume uvicorn por nombre)
