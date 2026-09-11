"""La fila por orden de llegada de un bloque de demanda espontánea.

Pedido del humano: *"posibilidad de armar la agenda por turnos o por demanda
espontánea"*, resuelto como **sin horario, por orden de llegada**.

🔴 **Lo que hay que probar es que la fila no se pueda armar donde no
corresponde.** Guardar y releer una llegada es lo barato; lo caro sería anotar
gente en un bloque que atiende con horarios —dos maneras simultáneas de ocupar
la misma franja, cada una ciega a la otra— o para un día que ese bloque no
trabaja: una fila que nadie va a llamar nunca.
"""
import pytest
from fastapi.testclient import TestClient

#: Lunes, y el martes siguiente. El bloque del fixture atiende los lunes.
LUNES = "2026-07-20"
MARTES = "2026-07-21"
LUNES_SIGUIENTE = "2026-07-27"


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Buenos_Aires",
    })
    client.post("/resources", json={
        "id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1",
    })
    client.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })
    client.post("/services", json={
        "id": "consulta", "name": "Consulta", "duration_minutes": 30,
    })
    for i, nombre in enumerate(["Ana", "Beto", "Carla"], start=1):
        client.post("/patients", json={"id": f"p-{i}", "name": nombre})
    return client


def _bloque(client: TestClient, modality="espontanea", **cambios) -> str:
    cuerpo = {
        "resource_id": "dr-molina", "consultorio_id": "cons-1",
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
        "valid_from": "2026-07-01", "valid_to": None,
        "slot_minutes": 20, "modality": modality,
    }
    cuerpo.update(cambios)
    creado = client.post("/agenda-blocks", json=cuerpo)
    assert creado.status_code == 201, creado.text
    return creado.json()["id"]


def _llega(client: TestClient, block_id: str, paciente="p-1", dia=LUNES):
    return client.post(f"/agenda-blocks/{block_id}/walkins", json={
        "client_id": paciente, "service_id": "consulta", "day": dia,
    })


def _fila(client: TestClient, block_id: str, dia=LUNES, solo_activos=False):
    return client.get(
        f"/agenda-blocks/{block_id}/walkins",
        params={"day": dia, "solo_activos": solo_activos},
    ).json()


# ── El orden de llegada ────────────────────────────────────────────────────

def test_las_llegadas_se_numeran_por_orden(consultorio: TestClient):
    bloque = _bloque(consultorio)
    for paciente in ["p-1", "p-2", "p-3"]:
        assert _llega(consultorio, bloque, paciente).status_code == 201

    fila = _fila(consultorio, bloque)
    assert [(w["arrival_order"], w["client_id"]) for w in fila] == [
        (1, "p-1"), (2, "p-2"), (3, "p-3"),
    ]
    assert {w["status"] for w in fila} == {"waiting"}


def test_cada_dia_arranca_su_propia_fila(consultorio: TestClient):
    """🔴 El número es por (bloque, día). Si fuera global, el primero de mañana
    sería "el cuarto" y el llamador diría cualquier cosa."""
    bloque = _bloque(consultorio)
    _llega(consultorio, bloque, "p-1", dia=LUNES)
    _llega(consultorio, bloque, "p-2", dia=LUNES)
    _llega(consultorio, bloque, "p-3", dia=LUNES_SIGUIENTE)

    assert [w["arrival_order"] for w in _fila(consultorio, bloque, LUNES)] == [1, 2]
    assert [w["arrival_order"] for w in _fila(consultorio, bloque, LUNES_SIGUIENTE)] == [1]


def test_cancelar_no_renumera_a_los_que_siguen(consultorio: TestClient):
    """El orden de llegada es **histórico**: dice en qué momento llegó cada uno.

    Renumerar borraría el único dato que la fila tiene, y haría que dos personas
    distintas hayan sido "la segunda" del mismo día. Quién sigue se calcula
    filtrando por estado, no por el número."""
    bloque = _bloque(consultorio)
    _llega(consultorio, bloque, "p-1")
    segundo = _llega(consultorio, bloque, "p-2").json()
    _llega(consultorio, bloque, "p-3")

    consultorio.post(f"/walkins/{segundo['id']}/cancelar")

    assert [(w["arrival_order"], w["status"]) for w in _fila(consultorio, bloque)] == [
        (1, "waiting"), (2, "cancelled"), (3, "waiting"),
    ]
    # Y el que sigue en la fila de espera es el tercero, no "el segundo".
    activos = _fila(consultorio, bloque, solo_activos=True)
    assert [w["arrival_order"] for w in activos] == [1, 3]


def test_una_llegada_nueva_no_reusa_el_numero_del_cancelado(consultorio: TestClient):
    """🔴 El control del de arriba, por el otro lado: si `registrar()` mirara
    sólo a los activos para calcular el máximo, el que llega después del
    cancelado se llevaría su número y volvería a haber dos "segundos"."""
    bloque = _bloque(consultorio)
    _llega(consultorio, bloque, "p-1")
    segundo = _llega(consultorio, bloque, "p-2").json()
    consultorio.post(f"/walkins/{segundo['id']}/cancelar")

    nuevo = _llega(consultorio, bloque, "p-3")
    assert nuevo.json()["arrival_order"] == 3


# ── Dónde NO se puede armar una fila ───────────────────────────────────────

def test_un_bloque_de_turnos_no_acepta_llegadas(consultorio: TestClient):
    """🔴 El chequeo que importa. Sobre un bloque con horarios, anotar gente en
    una fila crearía dos maneras simultáneas de ocupar la misma franja, cada una
    ciega a la otra."""
    bloque = _bloque(consultorio, modality="turnos")
    rechazado = _llega(consultorio, bloque)
    assert rechazado.status_code == 409
    assert "turnos con horario" in rechazado.json()["detail"]


def test_un_bloque_espontaneo_si_acepta_llegadas(consultorio: TestClient):
    """🔴 El control: el rechazo de arriba tiene que ser por la modalidad y no
    porque las llegadas no funcionen."""
    assert _llega(consultorio, _bloque(consultorio)).status_code == 201


def test_un_dia_que_el_bloque_no_atiende_se_rechaza(consultorio: TestClient):
    """El bloque atiende los lunes; el martes no hay fila que armar."""
    bloque = _bloque(consultorio, weekday=0)
    rechazado = _llega(consultorio, bloque, dia=MARTES)
    assert rechazado.status_code == 409
    assert "día de la semana" in rechazado.json()["detail"]


def test_fuera_de_la_vigencia_se_rechaza(consultorio: TestClient):
    bloque = _bloque(consultorio, valid_to=LUNES)
    assert _llega(consultorio, bloque, dia=LUNES).status_code == 201
    vencido = _llega(consultorio, bloque, dia=LUNES_SIGUIENTE)
    assert vencido.status_code == 409
    assert "vigente" in vencido.json()["detail"]


def test_un_bloque_inexistente_da_404(consultorio: TestClient):
    assert _llega(consultorio, "no-existe").status_code == 404


# ── La máquina de estados ──────────────────────────────────────────────────

def test_el_camino_completo_esperando_atencion_atendido(consultorio: TestClient):
    bloque = _bloque(consultorio)
    walkin = _llega(consultorio, bloque).json()

    llamado = consultorio.post(f"/walkins/{walkin['id']}/llamar")
    assert llamado.status_code == 200
    assert llamado.json()["status"] == "in_progress"

    atendido = consultorio.post(f"/walkins/{walkin['id']}/completar")
    assert atendido.status_code == 200
    assert atendido.json()["status"] == "completed"


def test_no_se_puede_completar_sin_llamar_primero(consultorio: TestClient):
    """🔴 El control de la máquina de estados: sin esto, "aceptar cualquier
    transición" pasaría el test de arriba igual."""
    bloque = _bloque(consultorio)
    walkin = _llega(consultorio, bloque).json()
    rechazado = consultorio.post(f"/walkins/{walkin['id']}/completar")
    assert rechazado.status_code == 409


def test_un_atendido_no_vuelve_a_la_fila(consultorio: TestClient):
    bloque = _bloque(consultorio)
    walkin = _llega(consultorio, bloque).json()
    consultorio.post(f"/walkins/{walkin['id']}/llamar")
    consultorio.post(f"/walkins/{walkin['id']}/completar")
    assert consultorio.post(f"/walkins/{walkin['id']}/llamar").status_code == 409


def test_una_llegada_inexistente_da_404(consultorio: TestClient):
    assert consultorio.post("/walkins/fantasma/llamar").status_code == 404


def test_solo_activos_deja_afuera_a_los_atendidos(consultorio: TestClient):
    """La pantalla del llamador pide la fila de espera, no el historial del día:
    con los atendidos adentro, el llamador mostraría a gente que ya se fue."""
    bloque = _bloque(consultorio)
    primero = _llega(consultorio, bloque, "p-1").json()
    _llega(consultorio, bloque, "p-2")
    consultorio.post(f"/walkins/{primero['id']}/llamar")
    consultorio.post(f"/walkins/{primero['id']}/completar")

    assert [w["client_id"] for w in _fila(consultorio, bloque, solo_activos=True)] == ["p-2"]
    # 🔴 El control: el historial del día sigue completo.
    assert len(_fila(consultorio, bloque)) == 2


# ── Lo que la pantalla lee para operar la fila ─────────────────────────────
#
# La pantalla tiene que ofrecer DÓNDE anotar a alguien, y el mostrador no puede
# leer `/agenda-blocks` (es de configuración, admin). Lo que se prueba es que lo
# que se ofrece es exactamente lo que el alta acepta: ni un bloque de turnos, ni
# uno de otro día de la semana, ni uno vencido.

def _bloques(client: TestClient, dia=LUNES) -> list[dict]:
    respuesta = client.get("/walkins/bloques", params={"day": dia})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_los_bloques_del_dia_son_los_espontaneos(consultorio: TestClient):
    """🔴 Un bloque de turnos el mismo día NO se ofrece: anotar gente ahí es
    justamente lo que `registrar_llegada` rechaza con 409."""
    espontaneo = _bloque(consultorio)
    _bloque(consultorio, modality="turnos", starts_at="14:00:00", ends_at="18:00:00")

    bloques = _bloques(consultorio)
    assert [b["id"] for b in bloques] == [espontaneo]
    # Los nombres van resueltos: quien pide esto no puede leer `/resources` ni
    # `/consultorios`. Y el huso es el de la sede, para la hora de llegada.
    assert bloques[0] | {"id": None} == {
        "id": None, "resource_id": "dr-molina", "profesional": "Dr. Molina",
        "consultorio_id": "cons-1", "consultorio": "Consultorio 1",
        "starts_at": "09:00:00", "ends_at": "13:00:00",
        "timezone": "America/Argentina/Buenos_Aires",
    }


def test_un_dia_que_el_bloque_no_atiende_no_ofrece_fila(consultorio: TestClient):
    _bloque(consultorio, weekday=0)
    assert _bloques(consultorio, MARTES) == []
    # 🔴 El control: el lunes sí. Sin esto, "no devolver nunca nada" pasaría.
    assert len(_bloques(consultorio, LUNES)) == 1


def test_fuera_de_la_vigencia_no_se_ofrece(consultorio: TestClient):
    _bloque(consultorio, valid_to=LUNES)
    assert len(_bloques(consultorio, LUNES)) == 1
    assert _bloques(consultorio, LUNES_SIGUIENTE) == []


def test_antes_de_que_empiece_no_se_ofrece(consultorio: TestClient):
    _bloque(consultorio, valid_from=LUNES_SIGUIENTE)
    assert _bloques(consultorio, LUNES) == []
    assert len(_bloques(consultorio, LUNES_SIGUIENTE)) == 1


def test_todo_lo_que_se_ofrece_acepta_una_llegada(consultorio: TestClient):
    """🔴 La propiedad de fondo: la lista y el alta usan el mismo criterio. Si
    divergieran, la secretaria vería una fila en la que anotar da siempre 409."""
    _bloque(consultorio)
    _bloque(consultorio, starts_at="14:00:00", ends_at="18:00:00")
    _bloque(consultorio, modality="turnos", starts_at="19:00:00", ends_at="20:00:00")
    ofrecidos = _bloques(consultorio)
    assert len(ofrecidos) == 2
    for bloque in ofrecidos:
        assert _llega(consultorio, bloque["id"]).status_code == 201


def test_las_prestaciones_de_la_fila_son_las_activas(consultorio: TestClient):
    consultorio.post("/services", json={
        "id": "vieja", "name": "Prestación dada de baja",
        "duration_minutes": 20, "active": False,
    })
    ids = [p["id"] for p in consultorio.get("/walkins/prestaciones").json()]
    assert "consulta" in ids
    assert "vieja" not in ids


def test_el_mostrador_puede_operar_la_fila_entera(
    consultorio: TestClient, staff_client: TestClient,
):
    """🔴 Es para quien existe la pantalla. Staff no lee `/agenda-blocks` ni
    `/services` —y no tiene por qué: son el alta y el borrado de la agenda—, así
    que sin estas dos lecturas la pantalla le quedaría vacía."""
    bloque = _bloque(consultorio)
    # El control: por esto hacen falta las lecturas de acá.
    assert staff_client.get("/agenda-blocks").status_code == 403
    assert staff_client.get("/services").status_code == 403

    assert [b["id"] for b in _bloques(staff_client)] == [bloque]
    assert staff_client.get("/walkins/prestaciones").status_code == 200
    llegada = _llega(staff_client, bloque)
    assert llegada.status_code == 201
    assert staff_client.post(f"/walkins/{llegada.json()['id']}/llamar").status_code == 200
