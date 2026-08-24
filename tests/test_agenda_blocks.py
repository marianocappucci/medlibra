"""Los bloques de agenda: consultorio, vigencia, duración y modalidad.

Pedido del humano (2026-08-22): *"la agenda del profesional se parametriza en un
consultorio, en un rango horario, en un día o días de la semana y se repite
hasta determinada fecha"*, más *"agregar duración de consulta"* y *"por turnos o
por demanda espontánea"*.

🔴 **Lo que hay que probar acá no es el CRUD.** Guardar y releer una fila es lo
barato; lo que importa es que el bloque **cambie lo que el alta de turnos
acepta**: que habilite donde no había ventana, que deje de habilitar cuando
vence, que la duración del turno salga de él y no de la prestación, y que dos
profesionales no queden en la misma sala a la misma hora. Cada uno de esos
tests tiene su control al lado: sin el control, "rechazar todo" los haría pasar
a todos.

⚠️ **La sede va en UTC-3 explícito.** Con offset cero, un error de terreno
horario da el mismo resultado que la conversión correcta y estos tests no verían
nada (es la lección de ADR-028).
"""
import pytest
from fastapi.testclient import TestClient

#: Lunes y lunes siguiente, para separar "dentro de la vigencia" de "después".
LUNES = "2026-07-20"
LUNES_SIGUIENTE = "2026-07-27"


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
    """Dos profesionales, dos salas, una prestación de 30 minutos.

    **Sin `Availability` semanal cargada**: así, todo turno que entre en estos
    tests entró por un bloque de agenda y no por el camino viejo.
    """
    client = admin_client
    client.post("/branches", json={
        "id": "sede-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Buenos_Aires",
    })
    client.post("/resources", json={
        "id": "dr-molina", "name": "Dr. Molina", "branch_id": "sede-1",
    })
    client.post("/resources", json={
        "id": "dra-vidal", "name": "Dra. Vidal", "branch_id": "sede-1",
    })
    client.post("/consultorios", json={
        "id": "cons-1", "name": "Consultorio 1", "branch_id": "sede-1",
    })
    client.post("/consultorios", json={
        "id": "cons-2", "name": "Consultorio 2", "branch_id": "sede-1",
    })
    client.post("/services", json={
        "id": "consulta", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json={"id": "p-1", "name": "Ana"})
    client.post("/patients", json={"id": "p-2", "name": "Beto"})
    return client


def _bloque(client: TestClient, **cambios):
    cuerpo = {
        "resource_id": "dr-molina", "consultorio_id": "cons-1",
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
        "valid_from": "2026-07-01", "valid_to": None,
        "slot_minutes": 20, "modality": "turnos",
    }
    cuerpo.update(cambios)
    return client.post("/agenda-blocks", json=cuerpo)


def _turno(client: TestClient, hora="10:00", dia=LUNES, profesional="dr-molina",
           paciente="p-1"):
    return client.post("/appointments", json={
        "resource_id": profesional, "service_id": "consulta",
        "client_id": paciente, "starts_at": f"{dia}T{hora}:00",
    })


# ── El CRUD y lo que el bloque no puede ser ────────────────────────────────

def test_bloque_crud_round_trip(consultorio: TestClient):
    client = consultorio
    creado = _bloque(client)
    assert creado.status_code == 201, creado.text
    block_id = creado.json()["id"]
    assert creado.json()["consultorio_id"] == "cons-1"
    assert creado.json()["slot_minutes"] == 20

    assert len(client.get("/agenda-blocks").json()) == 1
    assert len(client.get("/agenda-blocks?resource_id=dra-vidal").json()) == 0

    editado = client.put(f"/agenda-blocks/{block_id}", json={
        "resource_id": "dr-molina", "consultorio_id": "cons-2",
        "weekday": 2, "starts_at": "14:00:00", "ends_at": "18:00:00",
        "valid_from": "2026-07-01", "valid_to": "2026-12-31",
        "slot_minutes": 15, "modality": "turnos",
    })
    assert editado.status_code == 200
    assert editado.json()["consultorio_id"] == "cons-2"
    assert editado.json()["valid_to"] == "2026-12-31"

    assert client.delete(f"/agenda-blocks/{block_id}").status_code == 204
    assert client.get("/agenda-blocks").json() == []


def test_las_opciones_salen_del_backend(consultorio: TestClient):
    """La pantalla no repite la lista: si la repitiera, ofrecería un valor que
    el alta rechaza con 422 en cuanto las dos copias diverjan."""
    opciones = consultorio.get("/agenda-blocks/opciones").json()
    assert opciones["duraciones"] == [10, 15, 20, 25, 30]
    assert opciones["modalidades"] == ["turnos", "espontanea"]


def test_una_duracion_fuera_de_la_lista_se_rechaza(consultorio: TestClient):
    rechazado = _bloque(consultorio, slot_minutes=45)
    assert rechazado.status_code == 422
    assert "duración" in rechazado.json()["detail"]


def test_un_bloque_donde_no_entra_un_turno_se_rechaza(consultorio: TestClient):
    """🔴 De 09:00 a 09:10 con turnos de 15 minutos, el bloque existe, se dibuja
    y la ventana derivada rechaza absolutamente todo: una agenda que se ve
    configurada y no da un solo turno."""
    rechazado = _bloque(consultorio, ends_at="09:10:00", slot_minutes=15)
    assert rechazado.status_code == 422
    assert "no entra" in rechazado.json()["detail"]


def test_una_vigencia_al_reves_se_rechaza(consultorio: TestClient):
    rechazado = _bloque(consultorio, valid_from="2026-08-01", valid_to="2026-07-01")
    assert rechazado.status_code == 422


# ── Lo que el bloque le cambia al alta de turnos ───────────────────────────

def test_sin_bloque_ni_disponibilidad_no_hay_turno(consultorio: TestClient):
    """🔴 El control de todos los que siguen. Este fixture no carga
    `Availability` semanal, así que acá todavía no se puede agendar nada — y
    entonces cualquier turno que entre más abajo entró **por el bloque**."""
    assert _turno(consultorio).status_code == 409


def test_un_bloque_habilita_turnos_donde_no_habia_ventana(consultorio: TestClient):
    _bloque(consultorio)
    creado = _turno(consultorio)
    assert creado.status_code == 201, creado.text


def test_fuera_del_horario_del_bloque_sigue_sin_haber_turno(consultorio: TestClient):
    """🔴 El control de arriba: el bloque habilita **su** franja, no el día."""
    _bloque(consultorio)
    assert _turno(consultorio, hora="16:00").status_code == 409


def test_la_vigencia_corta_la_agenda(consultorio: TestClient):
    """🔴 El *"se repite hasta determinada fecha"* del pedido.

    `Availability` de LibraGenda no sabe expresar una vigencia: cargada, vale
    para siempre. Por eso las ventanas se derivan del bloque **para el día que
    se valida** en vez de guardarse como ventanas."""
    _bloque(consultorio, valid_to=LUNES)
    # Mismo día de la semana, misma hora: lo único distinto es la fecha.
    assert _turno(consultorio, dia=LUNES).status_code == 201
    assert _turno(consultorio, dia=LUNES_SIGUIENTE).status_code == 409


def test_sin_valid_to_la_agenda_no_vence(consultorio: TestClient):
    """🔴 El control: sin fecha de fin los dos lunes tienen que entrar. Sin
    esto, "rechazar siempre el segundo lunes" haría pasar al test de arriba."""
    _bloque(consultorio, valid_to=None)
    assert _turno(consultorio, dia=LUNES).status_code == 201
    assert _turno(consultorio, dia=LUNES_SIGUIENTE).status_code == 201


def test_la_duracion_la_manda_el_bloque_y_no_la_prestacion(consultorio: TestClient):
    """La prestación dura 30 minutos; el bloque dice 20. Gana el bloque
    (decisión del humano, 2026-08-23)."""
    _bloque(consultorio, slot_minutes=20)
    creado = _turno(consultorio, hora="10:00")
    assert creado.status_code == 201, creado.text
    # 10:00 de la sede son las 13:00Z; +20 minutos, no +30.
    assert creado.json()["ends_at"].startswith("2026-07-20T13:20")


def test_sin_bloque_la_duracion_sigue_siendo_la_de_la_prestacion(
    consultorio: TestClient,
):
    """🔴 El control, y además el compromiso de compatibilidad: una instancia
    que tiene su jornada cargada por `/resources/{id}/availability` y ningún
    bloque tiene que seguir funcionando exactamente como antes."""
    client = consultorio
    client.post("/resources/dr-molina/availability", json={
        "weekday": 0, "starts_at": "09:00:00", "ends_at": "13:00:00",
    })
    creado = _turno(client, hora="10:00")
    assert creado.status_code == 201, creado.text
    assert creado.json()["ends_at"].startswith("2026-07-20T13:30")


def test_un_bloque_espontaneo_no_da_turnos_con_hora(consultorio: TestClient):
    """Un bloque por demanda espontánea **no genera ventana**: si la generara, se
    le podrían dar turnos con horario encima de una franja que justamente no
    trabaja con horarios, y las dos formas se pisarían en la misma media hora."""
    _bloque(consultorio, modality="espontanea")
    assert _turno(consultorio).status_code == 409


# ── El choque de sala ──────────────────────────────────────────────────────

def test_dos_profesionales_no_entran_en_el_mismo_consultorio(consultorio: TestClient):
    """🔴 El choque que el motor **no puede ver**.

    LibraGenda asocia el turno a un solo recurso —el profesional— y busca
    conflictos sobre él. Las dos agendas de abajo son impecables por separado:
    cada profesional tiene un turno a las 10 y ninguno se pisa consigo mismo. Se
    pisan en la puerta del Consultorio 1."""
    client = consultorio
    _bloque(client, resource_id="dr-molina", consultorio_id="cons-1")
    _bloque(client, resource_id="dra-vidal", consultorio_id="cons-1")

    assert _turno(client, profesional="dr-molina", paciente="p-1").status_code == 201
    choque = _turno(client, profesional="dra-vidal", paciente="p-2")
    assert choque.status_code == 409
    assert "consultorio" in choque.json()["detail"].lower()


def test_en_consultorios_distintos_los_dos_entran(consultorio: TestClient):
    """🔴 El control. Sin esto, "rechazar el segundo turno siempre" haría pasar
    al de arriba — y sería exactamente el bug que arruina una clínica con dos
    salas."""
    client = consultorio
    _bloque(client, resource_id="dr-molina", consultorio_id="cons-1")
    _bloque(client, resource_id="dra-vidal", consultorio_id="cons-2")

    assert _turno(client, profesional="dr-molina", paciente="p-1").status_code == 201
    assert _turno(client, profesional="dra-vidal", paciente="p-2").status_code == 201


def test_un_turno_cancelado_libera_la_sala(consultorio: TestClient):
    """Mismo criterio que usa el motor para el profesional: cancelado y ausente
    no ocupan. Si la sala dijera otra cosa, el mismo turno estaría ocupado para
    una regla y libre para la otra."""
    client = consultorio
    _bloque(client, resource_id="dr-molina", consultorio_id="cons-1")
    _bloque(client, resource_id="dra-vidal", consultorio_id="cons-1")

    primero = _turno(client, profesional="dr-molina", paciente="p-1")
    client.post(f"/appointments/{primero.json()['id']}/cancel")

    assert _turno(client, profesional="dra-vidal", paciente="p-2").status_code == 201


def test_reprogramar_no_choca_contra_uno_mismo(consultorio: TestClient):
    """🔴 Sin excluirse a sí mismo, todo turno que ya ocupa una sala chocaría
    consigo mismo y no se podría reprogramar nunca."""
    client = consultorio
    _bloque(client, resource_id="dr-molina", consultorio_id="cons-1")
    creado = _turno(client, hora="10:00")
    turno_id = creado.json()["id"]

    movido = client.post(f"/appointments/{turno_id}/reschedule", json={
        "starts_at": f"{LUNES}T11:00:00",
    })
    assert movido.status_code == 200, movido.text


def test_reprogramar_encima_de_otro_de_la_misma_sala_se_rechaza(
    consultorio: TestClient,
):
    """🔴 El control del de arriba: excluirse a sí mismo no puede haber apagado
    el chequeo entero."""
    client = consultorio
    _bloque(client, resource_id="dr-molina", consultorio_id="cons-1")
    _bloque(client, resource_id="dra-vidal", consultorio_id="cons-1")

    client.post("/appointments", json={
        "resource_id": "dr-molina", "service_id": "consulta",
        "client_id": "p-1", "starts_at": f"{LUNES}T10:00:00",
    })
    de_vidal = client.post("/appointments", json={
        "resource_id": "dra-vidal", "service_id": "consulta",
        "client_id": "p-2", "starts_at": f"{LUNES}T11:00:00",
    })
    assert de_vidal.status_code == 201, de_vidal.text

    choque = client.post(f"/appointments/{de_vidal.json()['id']}/reschedule", json={
        "starts_at": f"{LUNES}T10:00:00",
    })
    assert choque.status_code == 409
    assert "consultorio" in choque.json()["detail"].lower()
