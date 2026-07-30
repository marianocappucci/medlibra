"""Mueve la tabla `usuarios` de la base de LibraCore a la base propia del producto.

Contexto: hasta el 2026-07-30 el auth de MedLibra venia de
`libracore.db.usuarios`, que escribe con sqlite3 crudo en una base separada
(`medlibra_libracore.db`, junto a facturacion/caja/ARCA). Ahora lo provee
`libraauth` sobre SQLAlchemy, contra la MISMA base que el dominio
(`medlibra.db`). Este script mueve las filas existentes.

Por que se puede mover sin tocar las contrasenas: las columnas son identicas
en los dos schemas y el hashing tambien (PBKDF2-SHA256, 260k iteraciones,
mismo formato de salt) — `libraauth.hashing` se porto a proposito sin cambiar
el algoritmo. Verificado end-to-end antes de escribir esto.

Idempotente: si un username ya existe en el destino no lo duplica ni lo pisa.
No borra nada del origen — la tabla vieja queda como esta, por si hay que
volver atras. Limpiarla es una decision aparte.

⚠️ EL ORDEN IMPORTA: correr esto ANTES de levantar la app con el codigo nuevo.

Si la app arranca primero, encuentra `usuarios` vacia y
`ensure_default_admin()` crea un admin con `MEDLIBRA_ADMIN_PASSWORD`. Al
migrar despues, ese username ya existe y se saltea — o sea que **la
contrasena del admin real quedaria silenciosamente reemplazada por la del env
var**, sin ningun error visible. Por eso el script sabe crear la tabla destino
el mismo (`--crear-tabla`): asi se migra primero, la app arranca con la tabla
ya poblada y `ensure_default_admin` no hace nada.

Uso:
    # 1. dry run
    python scripts/migrar_usuarios_a_libraauth.py ORIGEN.db DESTINO.db
    # 2. migrar (creando la tabla destino si hace falta), ANTES del deploy
    python scripts/migrar_usuarios_a_libraauth.py ORIGEN.db DESTINO.db \
        --crear-tabla --aplicar
"""
import argparse
import sqlite3
import sys

COLUMNAS = ("username", "nombre", "email", "password_hash", "role", "activo", "created_at")

# Equivalente al `CREATE TABLE` que emite `AuthBase.metadata.create_all()` de
# libraauth. Se escribe a mano para poder crear la tabla desde el host del VPS,
# donde libraauth no esta instalado (solo vive dentro del contenedor), y asi
# migrar ANTES de que arranque la app. `create_all()` es no-op si ya existe.
DDL_DESTINO = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    username      VARCHAR(100) NOT NULL UNIQUE,
    nombre        VARCHAR(200) NOT NULL,
    email         VARCHAR(200) NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    role          VARCHAR(20) NOT NULL,
    activo        BOOLEAN NOT NULL,
    created_at    DATETIME DEFAULT (CURRENT_TIMESTAMP)
);
"""


def leer_origen(path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'"
    ).fetchone():
        raise SystemExit(f"ERROR: {path} no tiene tabla `usuarios`.")
    filas = [dict(r) for r in con.execute(
        "SELECT %s FROM usuarios ORDER BY id" % ", ".join(COLUMNAS)
    )]
    con.close()
    return filas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("origen", help="base de libracore (medlibra_libracore.db)")
    ap.add_argument("destino", help="base del producto (medlibra.db)")
    ap.add_argument("--aplicar", action="store_true", help="escribir de verdad")
    ap.add_argument("--crear-tabla", action="store_true",
                    help="crear `usuarios` en el destino si no existe, para poder "
                         "migrar ANTES de levantar la app (ver docstring)")
    args = ap.parse_args()

    filas = leer_origen(args.origen)
    print(f"origen : {args.origen}  ({len(filas)} usuario(s))")
    print(f"destino: {args.destino}")

    con = sqlite3.connect(args.destino)
    con.row_factory = sqlite3.Row
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'"
    ).fetchone():
        if not args.crear_tabla:
            raise SystemExit(
                "ERROR: el destino no tiene tabla `usuarios`. Correr con "
                "--crear-tabla para crearla aca y migrar ANTES del deploy (lo "
                "recomendado, ver docstring), o levantar la app una vez para "
                "que la cree ella — pero ojo con el admin por defecto."
            )
        if args.aplicar:
            with con:
                con.executescript(DDL_DESTINO)
            print("         (tabla `usuarios` creada en el destino)")
        else:
            print("         (el destino no tiene la tabla; se crearia con --aplicar)")
            print()
            print("DRY RUN: se insertarian %d usuario(s) en una tabla nueva. "
                  "Volver a correr con --crear-tabla --aplicar." % len(filas))
            return 0

    existentes = {r["username"] for r in con.execute("SELECT username FROM usuarios")}
    print(f"         ({len(existentes)} usuario(s) ya en destino)")
    print()

    a_insertar = [f for f in filas if f["username"] not in existentes]
    for f in filas:
        estado = "ya existe, se saltea" if f["username"] in existentes else "SE INSERTA"
        print(f"  {f['username']:<20} role={f['role']:<8} activo={f['activo']}  {estado}")

    print()
    if not a_insertar:
        print("Nada que hacer: todos los usuarios ya estan en el destino.")
        return 0

    if not args.aplicar:
        print(f"DRY RUN: se insertarian {len(a_insertar)} usuario(s). "
              "Volver a correr con --aplicar.")
        return 0

    # Una sola transaccion: o entran todos o ninguno.
    marcadores = ", ".join("?" * len(COLUMNAS))
    with con:
        con.executemany(
            f"INSERT INTO usuarios ({', '.join(COLUMNAS)}) VALUES ({marcadores})",
            [tuple(f[c] for c in COLUMNAS) for f in a_insertar],
        )

    final = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    print(f"OK: {len(a_insertar)} insertado(s). Total en destino: {final}")

    # Verificacion: los hashes viajaron intactos (si no, nadie puede entrar).
    origen_por_user = {f["username"]: f["password_hash"] for f in filas}
    malos = [
        r["username"]
        for r in con.execute("SELECT username, password_hash FROM usuarios")
        if r["username"] in origen_por_user
        and r["password_hash"] != origen_por_user[r["username"]]
    ]
    if malos:
        print(f"ERROR: hash distinto al del origen en {malos}", file=sys.stderr)
        return 1
    print("Verificado: los password_hash del destino son identicos a los del origen.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
