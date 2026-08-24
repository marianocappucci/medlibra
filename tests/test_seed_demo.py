"""El seed de la demo pública, corrido contra una base limpia.

**Por qué un test y no una corrida a mano.** El cron de reset borra la base y
vuelve a sembrar, así que lo que hay que garantizar es que el seed funcione
*desde cero*. Probarlo contra una instancia ya sembrada no verifica eso: la
mitad de los pasos cae en la rama "ya estaba".

Lo que fijan estos tests, en orden de lo que se rompe sin que se note:

1. 🔴 **Que el seed corra entero sobre una base vacía.**
2. 🔴 **Que las alícuotas de IVA no queden todas iguales.** La consulta médica
   está exenta y las prácticas no: es la razón de que este producto tenga
   alícuota por prestación, y con todo al 21% esa pantalla no dice nada.
3. 🔴 **Que los datos clínicos sean inventados y genéricos.** Esto se publica:
   cualquiera entra a la demo sin credenciales.
4. Que queden turnos en varios estados, y que correrlo dos veces no duplique.
"""
import json

import pytest

from scripts.seed_demo import Api, sembrar, url_no_productiva


class _ApiDeTest(Api):
    """Habla con el `TestClient` con la misma interfaz que usa `sembrar()`, y
    **serializa igual que el `Api` real** (`default=str`): el seed manda
    `date`, `time` y `Decimal`, que el `json=` de httpx no sabe convertir."""

    def __init__(self, client):
        self.client = client

    def _pedir(self, metodo, ruta, cuerpo=None):
        datos = json.dumps(cuerpo, default=str) if cuerpo is not None else None
        respuesta = self.client.request(
            metodo, ruta, content=datos,
            headers={"Content-Type": "application/json"} if datos else None,
        )
        if respuesta.status_code >= 400:
            raise RuntimeError(f"{metodo} {ruta} -> {respuesta.status_code}: "
                               f"{respuesta.text[:300]}")
        return respuesta.json() if respuesta.content else None


@pytest.fixture
def api(admin_client):
    return _ApiDeTest(admin_client)


# ── 🔴 Desde cero ─────────────────────────────────────────────────────────

def test_el_seed_corre_entero_sobre_una_base_vacia(api, capsys):
    """El escenario del cron de reset."""
    sembrar(api)

    salida = capsys.readouterr().out
    assert "sucursales      2 creados" in salida
    assert "prestaciones    5 creados" in salida
    assert "pacientes       6 creados" in salida


def test_deja_el_catalogo_completo(api):
    sembrar(api)

    assert len(api.get("/branches")) == 2
    assert len(api.get("/services")) == 5
    assert len(api.get("/resources")) == 4
    assert len(api.get("/patients")) == 6


def test_hay_profesionales_y_pacientes_inactivos(api):
    """Las pantallas distinguen activos de inactivos."""
    sembrar(api)

    assert any(not r["active"] for r in api.get("/resources"))
    assert any(not p["active"] for p in api.get("/patients"))


# ── 🔴 El IVA por prestación ──────────────────────────────────────────────

def test_las_alicuotas_no_son_todas_iguales(api):
    """🔴 La consulta médica está exenta y las prácticas no. Es la razón de que
    este producto tenga alícuota por prestación: con todo al 21%, esa pantalla
    no dice nada."""
    sembrar(api)

    alicuotas = {
        s["id"]: float(api.get(f"/services/{s['id']}/iva")["rate"])
        for s in api.get("/services")
    }

    assert len(set(alicuotas.values())) >= 2, f"una sola alícuota: {alicuotas}"
    assert alicuotas["consulta"] == 0, "la consulta médica tiene que ir exenta"
    assert alicuotas["electro"] > 0, "la práctica tiene que ir gravada"


def test_los_precios_difieren_entre_sucursales(api):
    sembrar(api)

    precios = {p["branch_id"]: p["price"] for p in api.get("/services/consulta/prices")}
    assert len(precios) == 2
    assert len(set(precios.values())) == 2, "los dos precios son iguales"


# ── 🔴 Lo que se publica ──────────────────────────────────────────────────

def test_los_datos_clinicos_son_genericos(api):
    """🔴 Esto es una demo **pública**: cualquiera entra sin credenciales y ve
    las evoluciones. Ningún texto puede parecerse a la historia clínica de una
    persona concreta."""
    sembrar(api)

    textos = []
    for p in api.get("/patients"):
        textos += [n["text"] for n in (api.get(f"/patients/{p['id']}/notes") or [])]

    assert textos, "no se cargó ninguna evolución"
    prohibido = ("HIV", "VIH", "psiquiátr", "oncológ", "embarazo", "adicci")
    for texto in textos:
        for palabra in prohibido:
            assert palabra.lower() not in texto.lower(), \
                f"la evolución menciona {palabra!r}: {texto}"


def test_hay_evoluciones_y_recetas(api):
    sembrar(api)

    notas = sum(len(api.get(f"/patients/{p['id']}/notes") or [])
                for p in api.get("/patients"))
    recetas = sum(len(api.get(f"/patients/{p['id']}/prescriptions") or [])
                  for p in api.get("/patients"))

    assert notas >= 3
    assert recetas >= 2


def test_no_todos_los_pacientes_tienen_historia(api):
    """Un paciente recién dado de alta y sin evoluciones es un estado real, y
    la ficha vacía es una pantalla que conviene poder mirar."""
    sembrar(api)

    con_notas = [p["id"] for p in api.get("/patients")
                 if api.get(f"/patients/{p['id']}/notes")]

    assert 0 < len(con_notas) < len(api.get("/patients"))


# ── Los turnos ────────────────────────────────────────────────────────────

def _turnos(api):
    """Todos los turnos que sembró la demo.

    🔴 **La ventana se mide en días de CALENDARIO y el plan de la demo está en
    días HÁBILES**, así que tiene que sobrar por los dos lados. Hasta el
    2026-08-24 iba de `hoy - 2` a `hoy + 5`, y un lunes eso dejaba afuera los dos
    turnos de "ayer hábil" — que caen el viernes, tres días de calendario atrás.
    No lo notaba nadie porque el test pedía `>= 7` sobre un plan de 9: el margen
    se comía justo el agujero. Al pasar a una cuenta exacta apareció.
    """
    from datetime import date, timedelta

    desde, hasta = date.today() - timedelta(days=7), date.today() + timedelta(days=10)
    turnos = []
    for r in api.get("/resources"):
        turnos += api.get(f"/resources/{r['id']}/agenda"
                          f"?date_from={desde}&date_to={hasta}") or []
    return turnos


def _estados(api):
    """Los estados de todos los turnos que sembró la demo."""
    return [t["status"] for t in _turnos(api)]


def test_deja_turnos_en_mas_de_un_estado(api):
    """Completar un turno no es un campo: hay que confirmarlo antes. Este test
    también prueba que la cadena de transiciones se hizo bien."""
    sembrar(api)

    estados = _estados(api)
    # 🔴 **Los 11 del PLAN, exactos.** Antes decía `>= 7` sobre un plan de 9, y
    # ese margen es justo el que hace invisible el modo de falla que importa:
    # un turno que el alta rechaza (fuera de horario, sin disponibilidad, huso
    # corrido) no rompe nada — `sembrar()` lo saltea — y la demo queda con
    # menos turnos de los que dice tener, en verde.
    assert len(estados) == 11, f"turnos sembrados: {len(estados)}"
    assert len(set(estados)) >= 3, f"un solo estado o dos: {set(estados)}"


# ── Idempotencia ──────────────────────────────────────────────────────────

def test_correrlo_dos_veces_no_duplica(api, capsys):
    sembrar(api)
    capsys.readouterr()

    sembrar(api)

    salida = capsys.readouterr().out
    assert "pacientes       0 creados, 6 ya estaban" in salida
    assert len(api.get("/patients")) == 6


def test_la_segunda_corrida_ve_TODOS_los_turnos(api, capsys):
    """🔴 **La ventana con la que el seed se pregunta "¿ya sembré?" tiene que
    cubrir el plan entero**, y el plan avanza en días HÁBILES mientras que
    cualquier margen fijo se mide en días de CALENDARIO.

    Hasta el 2026-08-24 la cuenta iba de `HOY - 2` a `HOY + 5` y un lunes
    dejaba afuera los dos turnos de "ayer hábil" —que caen el viernes, tres
    días de calendario atrás—: el seed informaba 9 sobre 11. No duplicó nunca
    nada de puro suerte, porque el corte de entonces era 8 y 9 lo pasa igual. Es
    el mismo agujero que ya tapó dos veces el margen en este archivo, así que
    acá se mira el número exacto y no un "alcanza".
    """
    sembrar(api)
    capsys.readouterr()

    sembrar(api)

    salida = capsys.readouterr().out
    assert "(ya hay 11 turnos cargados)" in salida, salida


def test_una_demo_a_medias_no_se_re_siembra(api, capsys):
    """🔴 **Un turno no tiene clave natural.** No hay `obtener_o_crear` que lo
    salve, así que sembrar sobre una demo a medias agrega los 11 **encima** de
    los que ya estaban.

    Es la franja que el corte viejo tapaba: con `>= 8` sobre un plan de 11, una
    demo con 8, 9 o 10 turnos se salteaba en silencio y quedaba incompleta para
    siempre. Subir el corte a `len(PLAN)` **sin** esta rama la haría duplicar,
    que es peor que dejarla corta. Este test fija que no hace ninguna de las
    dos: avisa y no toca nada.

    El estado a medias se arma **por la API**, reprogramando dos turnos fuera de
    la ventana del plan — que es como se llega en la vida real (alguien mueve un
    turno de la demo) y además la única forma disponible: no hay
    `DELETE /appointments`.
    """
    from datetime import date, datetime, time, timedelta

    sembrar(api)
    assert len(_turnos(api)) == 11
    capsys.readouterr()

    lejos = date.today() + timedelta(days=28)
    while lejos.weekday() >= 5:
        lejos += timedelta(days=1)
    movidos = 0
    for turno in _turnos(api):
        if movidos == 2 or turno["status"] != "pending":
            continue
        api.post(f"/appointments/{turno['id']}/reschedule", {
            "starts_at": datetime.combine(lejos, time(9 + movidos)),
            "reason": "Movido a mano, como haría alguien sobre la demo",
        })
        movidos += 1
    assert movidos == 2, f"no se pudieron mover dos turnos: {movidos}"
    assert len(_turnos(api)) == 9, "los turnos movidos siguen dentro de la ventana"

    sembrar(api)

    salida = capsys.readouterr().out
    assert "PARCIAL" in salida, salida
    # 🔴 El mensaje es lo de menos: lo que este test protege es que NO haya
    # sembrado encima. Si lo hiciera, acá habría 9 + 11.
    assert len(_turnos(api)) == 9, "sembró sobre una demo a medias y duplicó"


def test_la_segunda_corrida_no_agrega_evoluciones(api):
    """Las evoluciones son **append-only** —no se editan ni se borran, que es
    lo correcto para una historia clínica—, así que un seed que las duplique
    ensucia sin forma de limpiar."""
    sembrar(api)
    antes = sum(len(api.get(f"/patients/{p['id']}/notes") or [])
                for p in api.get("/patients"))

    sembrar(api)

    despues = sum(len(api.get(f"/patients/{p['id']}/notes") or [])
                  for p in api.get("/patients"))
    assert despues == antes


# ── La guarda ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://demo.medlibra.com.ar",
    "https://prueba.medlibra.com.ar",
    "http://127.0.0.1:8000",
])
def test_donde_si_se_puede_sembrar(url):
    assert url_no_productiva(url) is True


@pytest.mark.parametrize("url", [
    "https://medlibra.com.ar",
    "https://clinica.medlibra.com.ar",
    "https://demoliciones.medlibra.com.ar",
])
def test_donde_NO(url):
    """🔴 Acá la guarda importa más que en ningún otro producto: los datos de
    una instancia real son historias clínicas."""
    assert url_no_productiva(url) is False
