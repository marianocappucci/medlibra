"""La guarda de `configure()` contra la carpeta con la contraseña en el nombre.

🔴 **El caso que importa es `postgresql+psycopg://`**, y era justamente el que
la guarda no reconocía. La lista escrita a mano decía `("postgres://",
"postgresql://")`, y `"postgresql+psycopg://".startswith("postgresql://")` es
`False`: la única forma de URL que este producto usa de verdad —la que
`app/main.py` arma para el engine de libraauth— caía del lado del SQLite y
`os.makedirs()` creaba **un directorio con la contraseña en el nombre**.

Donde el repo está bind-mounteado en `/app`, esa carpeta cae dentro del checkout
del VPS y el siguiente `docker build` la mete en la imagen.

Se prueba `os.makedirs` y no el resultado de `configure()` entero porque lo que
hay que verificar es exactamente eso: que no se llame. Llegar hasta la conexión
pediría un PostgreSQL levantado, y el defecto ocurre antes.
"""
import pytest

from app.services import libracore_setup


@pytest.fixture
def carpetas_creadas(monkeypatch):
    """Intercepta `os.makedirs` y aborta antes de tocar la base."""
    creadas = []

    def falso_makedirs(ruta, **kwargs):
        creadas.append(ruta)

    class Corte(RuntimeError):
        pass

    def cortar(_destino):
        raise Corte

    monkeypatch.setattr(libracore_setup.os, "makedirs", falso_makedirs)
    monkeypatch.setattr(libracore_setup.libracore_core, "configure", cortar)
    return creadas, Corte


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://medlibra:una-clave@db:5432/medlibra",
    "postgresql://medlibra:una-clave@db:5432/medlibra",
])
def test_una_url_de_postgres_no_crea_ninguna_carpeta(url, carpetas_creadas):
    creadas, Corte = carpetas_creadas
    with pytest.raises(Corte):
        libracore_setup.configure(url)
    assert creadas == [], f"se creó {creadas} — con la contraseña adentro"


def test_una_ruta_de_archivo_se_RECHAZA(carpetas_creadas):
    """🔴 El control, con el invariante nuevo.

    Hasta el 2026-08-25 este test exigía lo contrario: que una ruta de archivo
    creara su carpeta, porque el producto todavía podía arrancar sobre SQLite.
    Ya no puede — `configure()` rechaza cualquier destino que no sea una URL de
    PostgreSQL, y el modo SQLite se retiró el 2026-08-12.

    Sigue siendo el control del test de arriba y por el mismo motivo: sin él,
    una `configure()` que rechazara **todo** —incluida la URL— pasaría aquel
    igual, porque tampoco dejaría carpetas.
    """
    creadas, _ = carpetas_creadas
    with pytest.raises(RuntimeError, match="solo sobre PostgreSQL"):
        libracore_setup.configure("./data/medlibra_libracore.db")
    assert creadas == [], "rechazó, pero antes creó la carpeta"


def test_un_nombre_suelto_tambien_se_rechaza(carpetas_creadas):
    """Antes esto probaba que `makedirs("")` no se llamara —
    `os.path.dirname("medlibra.db")` es `""` y revienta—. Sin ruta de archivo
    posible ese camino no existe; lo que queda por exigir es que un nombre
    suelto se rechace igual que una ruta, y no se cuele por parecer otra cosa.
    """
    creadas, _ = carpetas_creadas
    with pytest.raises(RuntimeError, match="solo sobre PostgreSQL"):
        libracore_setup.configure("medlibra.db")
    assert creadas == []
