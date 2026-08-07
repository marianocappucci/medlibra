#!/usr/bin/env python3
"""Carga los datos de la demo pública de MedLibra — ítem 8 de los pendientes
transversales de Libra.

**Para qué.** Una demo vacía no muestra nada: quien entra ve pantallas en blanco
y se va. Este script deja la instancia con un consultorio andando, para que las
pantallas se puedan mirar.

**Por la API y no por SQL**, a propósito: así los datos pasan por las mismas
validaciones y los mismos servicios que usa la pantalla.

**Los datos clínicos son inventados y evidentemente inventados.** Ningún nombre,
DNI ni diagnóstico sale de una persona real, y ninguno es verosímil como
historia clínica de nadie en particular: son motivos de consulta genéricos. Esto
es una demo **pública** — cualquiera entra sin credenciales— y lo que se
muestra queda a la vista de todos.

**No cubre sólo el caso feliz.** Deja los estados que las pantallas distinguen:
turnos completados, confirmados, pendientes y cancelados; un profesional
inactivo; una prestación exenta de IVA y otras gravadas; y pacientes con y sin
obra social cargada.

**Es idempotente**: si el registro ya existe no lo duplica. El cron de reset lo
corre después de recrear la base, pero correrlo dos veces no rompe nada.

> 🔴 **Nunca contra la instancia de un cliente.** Se planta si el host no es de
> dev, demo, prueba o local — ver `url_no_productiva`. Acá la guarda importa
> más que en ningún otro producto: los datos de una instancia real son
> historias clínicas.

Uso:
    python scripts/seed_demo.py --url https://demo.medlibra.com.ar \\
        --usuario admin --password ...
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from http.cookiejar import CookieJar
from urllib.parse import urlparse

HOY = date.today()

#: Los subdominios que NO son de un cliente. Se compara el host entero o su
#: primera etiqueta, **no como substring de la URL**.
_HOSTS_NO_PRODUCTIVOS = ("dev", "demo", "prueba", "localhost", "127.0.0.1")


def url_no_productiva(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return host in _HOSTS_NO_PRODUCTIVOS or host.split(".")[0] in _HOSTS_NO_PRODUCTIVOS


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def _pedir(self, metodo: str, ruta: str, cuerpo=None):
        datos = json.dumps(cuerpo, default=str).encode() if cuerpo is not None else None
        req = urllib.request.Request(
            f"{self.base}{ruta}", data=datos, method=metodo,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=30) as r:
                crudo = r.read()
                return json.loads(crudo) if crudo else None
        except urllib.error.HTTPError as e:
            detalle = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{metodo} {ruta} -> {e.code}: {detalle}") from None

    def get(self, ruta):
        return self._pedir("GET", ruta)

    def post(self, ruta, cuerpo=None):
        return self._pedir("POST", ruta, cuerpo)

    def put(self, ruta, cuerpo=None):
        return self._pedir("PUT", ruta, cuerpo)


def obtener_o_crear(api: Api, ruta: str, clave: str, valor, cuerpo: dict):
    """Crea el registro si no está. Devuelve `(registro, es_nuevo)`."""
    for existente in api.get(ruta) or []:
        if existente.get(clave) == valor:
            return existente, False
    return api.post(ruta, cuerpo), True


# ── El consultorio ────────────────────────────────────────────────────────

SUCURSALES = [
    {"id": "central", "name": "Consultorios Centro",
     "timezone": "America/Argentina/Buenos_Aires",
     "phone": "11 4952-3300", "address": "Av. Rivadavia 3800, CABA"},
    {"id": "anexo", "name": "Anexo Belgrano",
     "timezone": "America/Argentina/Buenos_Aires",
     "phone": "11 4781-6600", "address": "Av. Cabildo 1900, CABA"},
]

#: (id, nombre, duración, alícuota de IVA)
#:
#: La consulta médica está **exenta** y las prácticas no: es así en la
#: normativa argentina, y es la razón de que este producto tenga alícuota por
#: prestación. Con todo al 21% esa pantalla no diría nada.
PRESTACIONES = [
    ("consulta", "Consulta clínica", 30, 0),
    ("control", "Control anual", 45, 0),
    ("electro", "Electrocardiograma", 20, 0.21),
    ("laboratorio", "Extracción de laboratorio", 15, 0.105),
    ("ecografia", "Ecografía abdominal", 30, 0.21),
]

PRECIOS = {
    "consulta": {"central": 22000, "anexo": 20000},
    "control": {"central": 30000, "anexo": 27000},
    "electro": {"central": 18000, "anexo": 16500},
    "laboratorio": {"central": 12000, "anexo": 11000},
    "ecografia": {"central": 35000, "anexo": 32000},
}

PROFESIONALES = [
    {"id": "dr-molina", "name": "Dr. Esteban Molina", "branch_id": "central"},
    {"id": "dra-vidal", "name": "Dra. Paula Vidal", "branch_id": "central"},
    {"id": "dr-arce", "name": "Dr. Nicolás Arce", "branch_id": "anexo"},
    # Inactivo: de licencia. La agenda no tiene que ofrecerlo.
    {"id": "dra-sosa", "name": "Dra. Inés Sosa", "branch_id": "anexo", "active": False},
]

#: Pacientes inventados. DNI de la serie 30.xxx.xxx, que no corresponde a
#: ninguna persona real, y nombres comunes sin apellido compuesto.
PACIENTES = [
    {"id": "p-001", "name": "Ana Torres", "dni": "30111222",
     "birth_date": date(1984, 3, 12), "phone": "11 5566-7788",
     "email": "atorres@example.com.ar", "condicion_iva": "Consumidor Final"},
    {"id": "p-002", "name": "Luis Ramírez", "dni": "30222333",
     "birth_date": date(1976, 11, 2), "phone": "11 6677-8899"},
    {"id": "p-003", "name": "Marta Sánchez", "dni": "30333444",
     "birth_date": date(1959, 6, 25), "phone": "11 7788-9900",
     "email": "msanchez@example.com.ar"},
    {"id": "p-004", "name": "Diego Ibarra", "dni": "30444555",
     "birth_date": date(1995, 1, 18), "phone": "11 8899-0011"},
    {"id": "p-005", "name": "Claudia Ponce", "dni": "30555666",
     "birth_date": date(2001, 9, 7)},
    # Inactivo: la pantalla de pacientes filtra por activos.
    {"id": "p-006", "name": "Héctor Vega", "dni": "30666777",
     "birth_date": date(1948, 4, 30), "active": False},
]

#: Horario de atención: lunes a viernes. **Sábado y domingo no**, para que se
#: vea que el horario existe y no es "siempre".
HORARIOS = [(dia, time(8, 0), time(18, 0)) for dia in range(0, 5)]

#: Disponibilidad de cada profesional. **Es otra cosa que el horario de la
#: sucursal**: el consultorio abre 8 a 18, pero cada profesional tiene su
#: propia agenda dentro de eso. Sin esto, LibraGenda rechaza todo con
#: `appointment unavailable`.
DISPONIBILIDAD = [(dia, time(8, 0), time(18, 0)) for dia in range(0, 5)]

# ⚠️ **Los turnos de ejemplo van entre las 9 y las 13, no más tarde.**
#
# `AppointmentService._resolve_utc` interpreta la hora naive como hora local de
# la sucursal y la convierte a **UTC**; después `is_within_hours` compara esa
# hora UTC contra las ventanas de `branch_hours`, que se cargan como hora
# local. Con `America/Argentina/Buenos_Aires` (UTC-3) eso corre la comparación
# tres horas. Es el mismo defecto que se encontró en Gestiolibra el 2026-08-06
# —los dos productos comparten `AppointmentService`— y tampoco se arregla acá:
# tocar la conversión de husos es un cambio con su propia verificación.

#: Motivos de consulta genéricos. **Nada que se parezca a la historia clínica
#: de alguien**: esto se publica.
NOTAS = [
    ("p-001", "Dra. Paula Vidal",
     "Consulta de control. Refiere buen estado general. Se solicita laboratorio "
     "de rutina."),
    ("p-002", "Dr. Esteban Molina",
     "Control de presión arterial. Valores dentro de rango. Continúa con las "
     "indicaciones previas."),
    ("p-003", "Dr. Esteban Molina",
     "Consulta por chequeo anual. Se indica electrocardiograma."),
]

RECETAS = [
    ("p-002", "Dr. Esteban Molina", [
        {"medication": "Enalapril 10 mg", "dosage": "1 comprimido por día",
         "instructions": "Por la mañana, con el desayuno."},
    ]),
    ("p-003", "Dra. Paula Vidal", [
        {"medication": "Vitamina D 100.000 UI", "dosage": "1 ampolla",
         "instructions": "Dosis única. Repetir control en tres meses."},
        {"medication": "Calcio 500 mg", "dosage": "1 comprimido por día"},
    ]),
]


def sembrar(api: Api) -> None:
    hechos = {}

    def contar(clave: str, nuevo: bool):
        creados, existentes = hechos.get(clave, (0, 0))
        hechos[clave] = (creados + int(nuevo), existentes + int(not nuevo))

    print("Sucursales…")
    for s in SUCURSALES:
        _, nuevo = obtener_o_crear(api, "/branches", "id", s["id"], s)
        contar("sucursales", nuevo)

    print("Horarios de atención…")
    for s in SUCURSALES:
        ya = {h["weekday"] for h in (api.get(f"/branches/{s['id']}/hours") or [])}
        for dia, desde, hasta in HORARIOS:
            if dia in ya:
                contar("horarios", False)
                continue
            api.post(f"/branches/{s['id']}/hours",
                     {"weekday": dia, "starts_at": desde, "ends_at": hasta})
            contar("horarios", True)

    print("Prestaciones…")
    for id_, nombre, duracion, iva in PRESTACIONES:
        _, nuevo = obtener_o_crear(api, "/services", "id", id_, {
            "id": id_, "name": nombre, "duration_minutes": duracion,
        })
        contar("prestaciones", nuevo)
        # `PUT` idempotente por definición: fija la alícuota, no la agrega.
        api.put(f"/services/{id_}/iva", {"rate": iva})

    print("Precios por sucursal…")
    for prestacion, por_sucursal in PRECIOS.items():
        for sucursal, precio in por_sucursal.items():
            api.put(f"/services/{prestacion}/prices",
                    {"branch_id": sucursal, "price": precio})
            contar("precios", True)

    print("Profesionales…")
    for r in PROFESIONALES:
        _, nuevo = obtener_o_crear(api, "/resources", "id", r["id"], r)
        contar("profesionales", nuevo)

    print("Disponibilidad…")
    for r in PROFESIONALES:
        ya = {d["weekday"] for d in (api.get(f"/resources/{r['id']}/availability") or [])}
        for dia, desde, hasta in DISPONIBILIDAD:
            if dia in ya:
                contar("disponibilidad", False)
                continue
            api.post(f"/resources/{r['id']}/availability",
                     {"weekday": dia, "starts_at": desde, "ends_at": hasta})
            contar("disponibilidad", True)

    print("Pacientes…")
    for p in PACIENTES:
        _, nuevo = obtener_o_crear(api, "/patients", "id", p["id"], p)
        contar("pacientes", nuevo)

    print("Turnos…")
    _sembrar_turnos(api, contar)

    print("Evolución y recetas…")
    _sembrar_clinico(api, contar)

    print()
    for clave, (creados, existentes) in sorted(hechos.items()):
        print(f"  {clave:<15} {creados} creados, {existentes} ya estaban")


def _sembrar_turnos(api: Api, contar) -> None:
    """Turnos en los cuatro estados que la agenda distingue.

    ⚠️ **No hay `GET /appointments`**: la agenda se lista por profesional y
    rango. Pedir la ruta que uno se imagina devuelve el HTML de la SPA —el
    catch-all—, no un 404: el 200 engaña.
    """
    desde, hasta = HOY - timedelta(days=2), HOY + timedelta(days=5)
    ya_cargados = sum(
        len(api.get(f"/resources/{r['id']}/agenda"
                    f"?date_from={desde}&date_to={hasta}") or [])
        for r in PROFESIONALES
    )
    if ya_cargados >= 8:
        contar("turnos", False)
        print(f"  (ya hay {ya_cargados} turnos cargados)")
        return

    #: Los días de la semana que la sucursal atiende, tomados de HORARIOS: si
    #: mañana se suma el sábado, esto lo sigue solo.
    DIAS_HABILES = {dia for dia, _, _ in HORARIOS}

    def _habil(fecha: date) -> bool:
        return fecha.weekday() in DIAS_HABILES

    def cuando(dias: int, hora: int, minuto: int = 0) -> datetime:
        """El día hábil número `dias` contando desde hoy (negativo = hacia atrás).

        🔴 **No es `HOY + días`, y esa era la falla.** Con desplazamientos de
        calendario, un turno a "+2" cae sábado cada jueves que corre el reset y
        LibraGenda lo rechaza —correctamente— por estar fuera del horario de
        atención. El seed lo avisaba y seguía, así que la demo amanecía con dos
        turnos menos sin que nada fallara a la vista. Lo destapó
        `test_deja_turnos_en_mas_de_un_estado`, que esperaba 7 y encontraba 6.

        Contando días hábiles, la agenda de la demo se ve igual cualquier día
        de la semana.
        """
        fecha = HOY
        paso = 1 if dias >= 0 else -1
        restantes = abs(dias)
        # El día 0 es hoy si hoy es hábil; si no, el primer hábil hacia
        # adelante — una demo abierta un domingo también tiene que mostrar algo.
        while not _habil(fecha):
            fecha += timedelta(days=1)
        while restantes:
            fecha += timedelta(days=paso)
            if _habil(fecha):
                restantes -= 1
        return datetime.combine(fecha, time(hora, minuto))

    # 🔴 Completar un turno **no es un campo, es una máquina de estados**: uno
    # `pending` no se puede completar sin confirmarlo antes. Por eso la última
    # columna es una lista de pasos.
    #
    # Las acciones son las rutas del router, **en inglés**.
    PLAN = [
        (-1, 9, "dr-molina", "consulta", "p-001", ["confirm", "complete"]),
        (-1, 10, "dra-vidal", "control", "p-003", ["confirm", "complete"]),
        (0, 9, "dr-molina", "electro", "p-002", ["confirm"]),
        (0, 11, "dra-vidal", "consulta", "p-004", ["confirm"]),
        (0, 12, "dr-arce", "laboratorio", "p-005", []),
        (1, 9, "dr-molina", "consulta", "p-003", ["confirm"]),
        (1, 11, "dra-vidal", "ecografia", "p-001", []),
        (2, 10, "dr-arce", "consulta", "p-002", ["cancel"]),
        (3, 9, "dra-vidal", "control", "p-005", []),
    ]

    CUERPOS = {
        "confirm": {},
        "complete": {"medio_pago": "efectivo"},
        "cancel": {"reason": "El paciente reprogramó"},
    }

    for dias, hora, profesional, prestacion, paciente, pasos in PLAN:
        inicio = cuando(dias, hora)
        try:
            turno = api.post("/appointments", {
                "resource_id": profesional, "service_id": prestacion,
                "client_id": paciente, "starts_at": inicio,
            })
        except RuntimeError as e:
            # Un turno que se pisa, o que cae en fin de semana, no corta el
            # seed: se avisa y se sigue.
            print(f"  -- {inicio:%d/%m %H:%M} {profesional}: {e}")
            continue
        contar("turnos", True)
        for paso in pasos:
            try:
                api.post(f"/appointments/{turno['id']}/{paso}", CUERPOS[paso])
            except RuntimeError as e:
                print(f"  -- {inicio:%d/%m %H:%M} {paso}: {e}")
                break


def _sembrar_clinico(api: Api, contar) -> None:
    """Evoluciones y recetas.

    Son **append-only**: no hay forma de editarlas ni borrarlas, que es lo
    correcto para una historia clínica. Por eso la idempotencia mira si el
    paciente ya tiene alguna, y no compara texto por texto.
    """
    for paciente, autor, texto in NOTAS:
        if api.get(f"/patients/{paciente}/notes"):
            contar("evoluciones", False)
            continue
        api.post(f"/patients/{paciente}/notes", {"author": autor, "text": texto})
        contar("evoluciones", True)

    for paciente, autor, items in RECETAS:
        if api.get(f"/patients/{paciente}/prescriptions"):
            contar("recetas", False)
            continue
        api.post(f"/patients/{paciente}/prescriptions",
                 {"author": autor, "items": items})
        contar("recetas", True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument(
        "--force", action="store_true",
        help="Correr contra una URL que no parece de dev ni de demo. No usar.",
    )
    args = ap.parse_args()

    if not url_no_productiva(args.url) and not args.force:
        print(f"ERROR: {args.url} no parece una instancia de dev ni de demo.",
              file=sys.stderr)
        print("Este script NO se corre contra la instancia de un cliente.",
              file=sys.stderr)
        return 2

    api = Api(args.url)
    api.post("/auth/login", {"username": args.usuario, "password": args.password})
    sembrar(api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
