"""El feriado de la sucursal cierra la agenda.

🔴 **Hasta este cambio no cerraba nada, y no había forma de notarlo.** La regla
vive en el motor —`_is_branch_holiday()` en `libragenda/scheduling.py`— pero
`AppointmentService._agenda_local()` armaba el `InMemoryScheduler` sin pasarle
`holidays` ni `resources`, y esa función necesita **las dos** listas: busca el
recurso para sacarle la sucursal y recién ahí compara contra los feriados. Con
cualquiera de las dos vacía devuelve `False` siempre.

Como además no había endpoint para dar de alta un feriado, la tabla `holidays`
estaba vacía en toda instalación y el defecto no tenía quien lo reportara.

Los tests ejercitan el **camino real de alta** (HTTP → `AppointmentService`) y
no un `InMemoryScheduler` armado a mano: pasarle `holidays` al motor en el test
sería encodar justo la suposición que fallaba, y daría verde con el defecto
entero puesto.
"""
from fastapi.testclient import TestClient

# 2026-07-20 es lunes; el 21, martes. Las mismas fechas que usa
# `test_branch_hours.py`, para que los dos archivos hablen del mismo calendario.
FERIADO = "2026-07-20"
DIA_HABIL = "2026-07-21"


def _seeded_client(client: TestClient):
    client.post("/branches", json={"id": "branch-1", "name": "Centro"})
    client.post("/resources", json={
        "id": "resource-1", "name": "Consultorio 1", "branch_id": "branch-1",
    })
    client.post("/services", json={
        "id": "service-1", "name": "Consulta", "duration_minutes": 30,
    })
    client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    # Disponibilidad del recurso abierta de par en par: lo único que puede
    # cerrar el día en estos tests es el feriado.
    for weekday in range(7):
        client.post("/resources/resource-1/availability", json={
            "weekday": weekday, "starts_at": "00:00:00", "ends_at": "23:59:00",
        })
    return client


def _feriado(client, dia=FERIADO, sucursal="branch-1", nombre="Día de prueba"):
    return client.post(f"/branches/{sucursal}/holidays", json={"day": dia, "name": nombre})


def _book(client, dia=FERIADO, hour=10):
    return client.post("/appointments", json={
        "resource_id": "resource-1", "service_id": "service-1",
        "client_id": "patient-1", "starts_at": f"{dia}T{hour:02d}:00:00",
    })


# -- la regla ---------------------------------------------------------------

def test_un_feriado_de_la_sucursal_rechaza_el_turno(admin_client: TestClient):
    """El que fallaba antes del arreglo: devolvía 201."""
    client = _seeded_client(admin_client)
    assert _feriado(client).status_code == 201
    assert _book(client).status_code == 409


def test_el_feriado_cierra_su_dia_y_no_el_siguiente(admin_client: TestClient):
    """Control positivo. Sin esto, un arreglo que cerrara la agenda entera
    —o un `False` que pasara a `True` siempre— haría pasar el test de arriba."""
    client = _seeded_client(admin_client)
    _feriado(client)
    assert _book(client, dia=DIA_HABIL).status_code == 201


def test_el_feriado_de_otra_sucursal_no_cierra_esta(admin_client: TestClient):
    """El feriado es por sucursal, no global: `branch-2` no le habla a
    `resource-1`, que es de `branch-1`."""
    client = _seeded_client(admin_client)
    client.post("/branches", json={"id": "branch-2", "name": "Anexo"})
    assert _feriado(client, sucursal="branch-2").status_code == 201
    assert _book(client).status_code == 201


def test_sin_feriados_cargados_nada_cambia(admin_client: TestClient):
    """La tabla vacía es el estado de toda instalación existente: el cambio no
    puede empezar a rechazar turnos que antes entraban."""
    client = _seeded_client(admin_client)
    assert _book(client).status_code == 201


def test_reprogramar_hacia_un_feriado_se_rechaza(admin_client: TestClient):
    """`reschedule()` pasa por el mismo `_agenda_local()`; si la regla se
    conectara sólo en el alta, mover un turno sería la puerta de atrás."""
    client = _seeded_client(admin_client)
    creado = _book(client, dia=DIA_HABIL)
    assert creado.status_code == 201
    _feriado(client)
    movido = client.post(f"/appointments/{creado.json()['id']}/reschedule", json={
        "starts_at": f"{FERIADO}T10:00:00",
    })
    assert movido.status_code == 409


# -- el alta y el listado ---------------------------------------------------

def test_alta_y_listado_de_feriados(admin_client: TestClient):
    client = _seeded_client(admin_client)
    assert _feriado(client, dia="2026-12-25", nombre="Navidad").status_code == 201
    assert _feriado(client, dia="2026-05-01", nombre="Día del Trabajador").status_code == 201
    listado = client.get("/branches/branch-1/holidays").json()
    # Ordenados por día: el listado es para mostrarlo, no para adivinar el orden
    # de inserción.
    assert [item["day"] for item in listado] == ["2026-05-01", "2026-12-25"]
    assert listado[0]["branch_id"] == "branch-1"


def test_el_listado_es_por_sucursal(admin_client: TestClient):
    client = _seeded_client(admin_client)
    client.post("/branches", json={"id": "branch-2", "name": "Anexo"})
    _feriado(client, dia="2026-12-25", nombre="Navidad")
    _feriado(client, dia="2026-05-01", nombre="Trabajador", sucursal="branch-2")
    assert len(client.get("/branches/branch-1/holidays").json()) == 1
    assert len(client.get("/branches/branch-2/holidays").json()) == 1


def test_feriado_en_una_sucursal_inexistente_da_404(admin_client: TestClient):
    client = _seeded_client(admin_client)
    assert _feriado(client, sucursal="no-existe").status_code == 404


def test_feriado_sin_nombre_se_rechaza(admin_client: TestClient):
    """La validación es del dominio (`Holiday.__post_init__`), no de Pydantic:
    un nombre en blanco pasa el schema y lo frena el motor."""
    client = _seeded_client(admin_client)
    assert _feriado(client, nombre="   ").status_code == 422
