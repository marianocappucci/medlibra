"""Configuración por entorno: la base del dominio y la de LibraCore, que pueden ser una sola o dos (ADR-043).

🔑 **Una sola base es el destino** (decisión del humano, 2026-10-22: una base por producto). `-dev` ya está
unida (ADR-044) y todo alta nueva nace con una; `-demo` sigue con dos —el dominio y `medlibra_core`— hasta que
`libracore-unir-bases` la una, así que el código tiene que andar con las dos formas y no suponer.

Resuelve igual que LibraClub (ADR-020 de ese producto):

- sin `MEDLIBRA_LIBRACORE_DATABASE_URL` (ni el histórico `MEDLIBRA_LIBRACORE_DB_PATH`), o con la misma base
  que el dominio, `libracore_database_url` **es** la URL del dominio y `core_en_la_del_dominio` es verdadero;
- con otra base, todo sigue como hasta hoy.

El motor llama a la segunda variable `..._LIBRACORE_DATABASE_URL` y acepta la vieja
(`libracore.db.url_de_instancia`): se leen las dos por ese camino, no a mano.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from libracore.db.url_de_instancia import url_de_instancia

PREFIJO = "medlibra"

_PREFIJOS_POSTGRES = ("postgresql://", "postgresql+psycopg://")


def es_postgres(url: str) -> bool:
    return url.startswith(_PREFIJOS_POSTGRES)


def misma_base(a: str, b: str) -> bool:
    """Si dos URLs apuntan a la misma base, aunque una diga `+psycopg` y la otra no.

    Compara servidor, usuario y nombre de la base; ignora el driver, los parámetros (`?sslmode=...`) y la
    barra final. No resuelve nombres de host: dos alias del mismo servidor cuentan como distintos, y
    entonces se trata como dos bases (respaldar de más es el error barato; respaldar de menos no).
    """
    def _normal(u: str) -> str:
        return u.replace("postgresql+psycopg://", "postgresql://", 1).split("?", 1)[0].rstrip("/")
    return _normal(a) == _normal(b)


@dataclass(frozen=True)
class Config:
    #: La base del dominio (LibraGenda y las tablas de MedLibra).
    database_url: str
    #: La base de LibraCore: **la misma que la del dominio, o una aparte**. Siempre está resuelta: si no hay
    #: variable (o es la misma base), es la URL del dominio tal cual, un solo valor escrito una sola vez
    #: para que nadie más compare cadenas.
    libracore_database_url: str

    @property
    def core_en_la_del_dominio(self) -> bool:
        """Si el schema de LibraCore (y los usuarios de libraauth) viven en la base del dominio."""
        return misma_base(self.database_url, self.libracore_database_url)

    @property
    def base_de_auth(self) -> str:
        """El valor de `--base` de `libraauth-migrar` para esta instancia: `dominio` o `core`."""
        return "dominio" if self.core_en_la_del_dominio else "core"

    @classmethod
    def desde_entorno(cls, database_url: str | None = None) -> Config:
        """`database_url`, si se pasa (lo hace `create_app(database_url)`), manda sobre el entorno para el dominio."""
        dominio = database_url or url_de_instancia(PREFIJO, requerida=True)
        return cls(database_url=dominio, libracore_database_url=cls._url_del_core(dominio))

    @staticmethod
    def _url_del_core(url_del_dominio: str) -> str:
        """La base de LibraCore: la propia o, si no hay, la del dominio.

        Sin variable, o con la misma base que el dominio, devuelve la URL del dominio tal cual. Con otra base
        (las instancias que todavía no se unieron) devuelve esa.

        Sólo cuando el dominio **no** es PostgreSQL (el modo SQLite se retiró el 2026-08-12; `libracore_setup`
        lo rechaza con un mensaje que lo dice) cae al archivo de siempre, para que el error sea ése y no
        otro más confuso.
        """
        propia = url_de_instancia(PREFIJO, core=True)
        if propia:
            if not es_postgres(propia):
                # Una ruta de archivo no es una base: se deja pasar para que `libracore_setup` la rechace con su mensaje.
                return propia
            return url_del_dominio if misma_base(url_del_dominio, propia) else propia
        if es_postgres(url_del_dominio):
            return url_del_dominio
        return os.path.join(os.environ.get("DATA_DIR", "./data"), "medlibra_libracore.db")
