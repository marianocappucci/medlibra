import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def seeded_client(admin_client: TestClient) -> TestClient:
    client = admin_client
    client.post("/branches", json={"id": "branch-1", "name": "Consultorio demo"})
    client.post("/resources", json={"id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1"})
    client.post("/services", json={"id": "service-1", "name": "Consulta", "duration_minutes": 30})
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": "18:00:00",
        })
    return client


def test_agenda_returns_appointments_within_range(seeded_client: TestClient):
    client = seeded_client
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-22T11:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    # 13:00Z y no 10:00Z: la sucursal del fixture esta en UTC-3 (el default
    # de `POST /branches`), asi que "10:00" en el formulario son las diez
    # del reloj del consultorio.
    assert body[0]["starts_at"] == "2026-07-20T13:00:00Z"


def test_agenda_covers_a_full_week_and_is_sorted(seeded_client: TestClient):
    client = seeded_client
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-22T11:00:00",
    })
    client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-26",
    })
    body = response.json()
    assert [item["starts_at"] for item in body] == [
        "2026-07-20T13:00:00Z", "2026-07-22T14:00:00Z",
    ]


def test_agenda_ignores_other_resources(seeded_client: TestClient):
    client = seeded_client
    client.post("/resources", json={"id": "resource-2", "name": "Consultorio 2"})
    for weekday in range(7):
        client.post("/resources/resource-2/availability", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": "18:00:00",
        })
    client.post("/appointments", json={
        "resource_id": "resource-2", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T10:00:00",
    })

    response = client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    })
    assert response.json() == []


def test_agenda_rejects_date_to_before_date_from(seeded_client: TestClient):
    response = seeded_client.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-19",
    })
    assert response.status_code == 422


# ── El terreno horario de la agenda (2026-08-22) ────────────────────────────
#
# 🔴 **Cuál era el defecto ACÁ, que no es el mismo que el de Gestiolibra.**
#
# Gestiolibra ya interpretaba el valor del formulario como hora de pared de la
# sede (su ADR-028) y lo convertía a UTC *antes* de validarlo, así que su
# validación medía las 20:00 UTC contra una ventana cargada 9-19 y rechazaba
# el turno de las 17:00. Ése fue el 409 que reportó el humano allá.
#
# MedLibra nunca tuvo esa conversión: trataba el valor naive como UTC de punta
# a punta. Por eso su validación era **internamente consistente** -- comparaba
# las 17:00 contra 9-19 y aceptaba -- y el defecto salía por el otro lado: el
# turno que la secretaria daba para las 17:00 se **guardaba** como 17:00Z, o
# sea las 14:00 del reloj del consultorio. Tres horas de corrimiento en el
# instante, que es lo que después leen los recordatorios y cualquier consumidor
# que no esté en UTC.
#
# Por eso el guard de ESE defecto son los dos tests de arriba, que asertan el
# instante guardado (`13:00:00Z` para un turno de las 10:00 de pared), y el de
# `starts_at` con offset explícito acá abajo. Medido: contra el código viejo
# esos tres fallan.
#
# Los cinco que siguen NO fallaban contra el código viejo, y quedan dicho eso:
# no reproducen lo que MedLibra tenía roto, cubren lo que la corrección nueva
# podría romper -- son exactamente los síntomas que sí tuvo Gestiolibra, y el
# estado intermedio de un arreglo a medias (mover la conversión y olvidarse del
# filtro, o de los bloqueos) los enciende.
#
# 🔴 **Van dos sedes y no una.** Con una sola abierta de 9 a 23 -- que es lo
# primero que uno escribe, para que entren también los turnos de la noche -- el
# caso de Gestiolibra deja de reproducirse: las 17:00 de UTC-3 son las 20:00
# UTC, que caen adentro de 9-23. Cada síntoma necesita la ventana en la que se
# manifiesta.


def _sembrar_consultorio(client: TestClient, cierra: str) -> TestClient:
    """Un consultorio real: UTC-3, con horario de atención y un profesional
    disponible en esa misma franja. Es la forma en que lo carga cualquier
    cliente desde la pantalla de Configuración."""
    client.post("/branches", json={
        "id": "branch-1", "name": "Consultorio Norte",
        "timezone": "America/Argentina/Buenos_Aires",
    })
    client.post("/resources", json={
        "id": "resource-1", "name": "Dra. Pérez", "branch_id": "branch-1",
    })
    client.post("/services", json={
        "id": "service-1", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    for weekday in range(7):
        client.post("/branches/branch-1/hours", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": cierra,
        })
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "09:00:00", "ends_at": cierra,
        })
    return client


@pytest.fixture
def consultorio(admin_client: TestClient) -> TestClient:
    """De 9 a 19 — el horario del caso reportado."""
    return _sembrar_consultorio(admin_client, "19:00:00")


@pytest.fixture
def consultorio_nocturno(admin_client: TestClient) -> TestClient:
    """De 9 a 23, para los turnos que en UTC caen del otro lado de la
    medianoche. Con el cierre a las 19 esos turnos se rechazarían por estar
    cerrado, que es un rechazo correcto y no dice nada sobre husos."""
    return _sembrar_consultorio(admin_client, "23:00:00")


def _turno(client: TestClient, hora: str, dia: str = "2026-07-20"):
    return client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": f"{dia}T{hora}:00",
    })


def test_un_starts_at_con_huso_explicito_se_valida_en_hora_local(consultorio: TestClient):
    """Un pedido que trae el huso puesto -- lo que manda una integración o un
    cliente que no sea este formulario -- se valida contra la ventana **en hora
    de la sede**, no comparando su hora UTC.

    `2026-07-20T20:00:00Z` son las 17:00 del consultorio, adentro de 9-19. El
    código viejo comparaba las 20:00 contra esa ventana y devolvía 409: es el
    mismo 409 que reportó el humano en Gestiolibra, y acá se alcanzaba por esta
    puerta. Medido contra el código viejo: falla."""
    creado = consultorio.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": "2026-07-20T20:00:00Z",
    })
    assert creado.status_code == 201, creado.text

    # Y se guarda como el instante que es, sin volver a correrlo.
    agenda = consultorio.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    }).json()
    assert [t["starts_at"] for t in agenda] == ["2026-07-20T20:00:00Z"]


def test_un_turno_de_la_tarde_entra_en_el_horario_de_atencion(consultorio: TestClient):
    """El caso reportado, tal cual. Con el consultorio abierto de 9 a 19 las
    17:00 están adentro; hasta el arreglo daban 409 porque lo que se comparaba
    contra la ventana eran las 20:00 UTC."""
    creado = _turno(consultorio, "17:00")
    assert creado.status_code == 201, creado.text


def test_un_turno_fuera_del_horario_sigue_rechazandose(consultorio: TestClient):
    """🔴 El control. Sin esto, el test de arriba pasaría en verde con la
    validación de horarios apagada del todo, que es la otra forma de "arreglar"
    un 409 molesto.

    Las 08:00, antes de abrir, y no un horario de la noche: un turno de 23:30
    terminaría a las 00:00 del día siguiente y lo rechazaría la regla de
    "empieza y termina el mismo día" del motor -- otro rechazo, con lo cual el
    control estaría mirando una cosa distinta de la que dice mirar."""
    rechazado = _turno(consultorio, "08:00")
    assert rechazado.status_code == 409
    assert "fuera del horario de atenci" in rechazado.json()["detail"]


def test_dos_turnos_a_la_misma_hora_siguen_chocando(consultorio: TestClient):
    """🔴 El control de la traducción del repositorio. `_TurnosEnHoraLocal`
    filtra y traduce los turnos que el motor usa para buscar choques: si
    devolviera de menos, el segundo turno entraría sin quejarse y la agenda
    dejaría de servir para lo único que tiene que hacer."""
    assert _turno(consultorio, "17:00").status_code == 201
    segundo = _turno(consultorio, "17:00")
    assert segundo.status_code == 409
    assert "ocupado" in segundo.json()["detail"]


def test_un_turno_de_la_noche_no_se_cae_por_la_medianoche_utc(
    consultorio_nocturno: TestClient,
):
    """El segundo síntoma del mismo defecto, y el que no dependía de las
    ventanas: `contains()` exige que el turno empiece y termine el MISMO día, y
    en UTC-3 todo lo de 21:00 en adelante cruza la medianoche UTC. Con el
    consultorio abierto hasta las 23, un turno a las 22:00 es legal por el
    reloj de la pared y era irrechazable por el reloj de Greenwich."""
    creado = _turno(consultorio_nocturno, "22:00")
    assert creado.status_code == 201, creado.text


def test_el_turno_de_la_noche_aparece_en_su_dia_local(consultorio_nocturno: TestClient):
    """Y una vez guardado, se lista en el día en que ocurre para quien atiende.

    Un turno de las 21:30 del lunes es 00:30Z del martes: filtrando por la
    fecha del instante no aparecía al pedir el lunes. La agenda se pide por día
    de calendario, y el calendario es el del consultorio."""
    assert _turno(consultorio_nocturno, "21:30", dia="2026-07-20").status_code == 201

    del_lunes = consultorio_nocturno.get("/resources/resource-1/agenda", params={
        "date_from": "2026-07-20", "date_to": "2026-07-20",
    }).json()
    assert len(del_lunes) == 1
