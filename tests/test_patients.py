from fastapi.testclient import TestClient


def test_patient_crud_round_trip(admin_client: TestClient):
    client = admin_client
    created = client.post("/patients", json={
        "id": "patient-1", "name": "Ana", "phone": "123",
        "dni": "30111222", "birth_date": "1990-05-01",
    })
    assert created.status_code == 201
    assert created.json() == {
        "id": "patient-1", "name": "Ana", "phone": "123", "email": None,
        "active": True, "dni": "30111222", "birth_date": "1990-05-01",
        "cuit": None, "condicion_iva": None,
    }

    fetched = client.get("/patients/patient-1")
    assert fetched.status_code == 200
    assert fetched.json()["dni"] == "30111222"

    assert len(client.get("/patients").json()) == 1

    updated = client.put("/patients/patient-1", json={
        "name": "Ana Renombrada", "dni": "30111222", "birth_date": "1990-05-02",
    })
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ana Renombrada"
    assert updated.json()["birth_date"] == "1990-05-02"

    assert client.delete("/patients/patient-1").status_code == 204
    assert client.get("/patients/patient-1").status_code == 404


def test_patient_dni_and_birth_date_are_optional(admin_client: TestClient):
    created = admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    assert created.status_code == 201
    assert created.json()["dni"] is None
    assert created.json()["birth_date"] is None
    assert created.json()["cuit"] is None
    assert created.json()["condicion_iva"] is None


def test_patient_cuit_and_condicion_iva_round_trip(admin_client: TestClient):
    client = admin_client
    created = client.post("/patients", json={
        "id": "patient-1", "name": "Ana",
        "cuit": "20111222339", "condicion_iva": "Responsable Inscripto",
    })
    assert created.status_code == 201
    assert created.json()["cuit"] == "20111222339"
    assert created.json()["condicion_iva"] == "Responsable Inscripto"

    updated = client.put("/patients/patient-1", json={
        "name": "Ana", "cuit": "20111222339", "condicion_iva": "Monotributista",
    })
    assert updated.status_code == 200
    assert updated.json()["condicion_iva"] == "Monotributista"


def test_patient_not_found_returns_404(admin_client: TestClient):
    assert admin_client.get("/patients/missing").status_code == 404
    assert admin_client.put("/patients/missing", json={"name": "x"}).status_code == 404
    assert admin_client.delete("/patients/missing").status_code == 404


def test_patient_duplicate_id_returns_409(admin_client: TestClient):
    admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    response = admin_client.post("/patients", json={"id": "patient-1", "name": "Otra"})
    assert response.status_code == 409


def test_patient_rejects_invalid_data(admin_client: TestClient):
    response = admin_client.post("/patients", json={"id": "", "name": "Ana"})
    assert response.status_code == 422


def test_staff_can_create_and_read_patients_but_not_delete(staff_client: TestClient):
    created = staff_client.post("/patients", json={"id": "patient-2", "name": "Beto"})
    assert created.status_code == 201
    assert staff_client.get("/patients/patient-2").status_code == 200
    assert staff_client.delete("/patients/patient-2").status_code == 403


# --- Alta sin `id`: el número de paciente se genera solo (ADR-071) -----------------------

def test_alta_sin_id_genera_uno(admin_client: TestClient):
    created = admin_client.post("/patients", json={"name": "Ana", "dni": "30111222"})
    assert created.status_code == 201
    assert created.json()["id"] == "p-001"
    assert admin_client.get("/patients/p-001").json()["name"] == "Ana"


def test_altas_sin_id_son_consecutivas_y_no_chocan(admin_client: TestClient):
    ids = [admin_client.post("/patients", json={"name": f"Paciente {i}"}).json()["id"] for i in range(3)]
    assert ids == ["p-001", "p-002", "p-003"]
    assert len(admin_client.get("/patients").json()) == 3


def test_alta_con_id_sigue_respetandolo(admin_client: TestClient):
    created = admin_client.post("/patients", json={"id": "patient-1", "name": "Ana"})
    assert created.status_code == 201
    assert created.json()["id"] == "patient-1"
    # Un id escrito a mano no mueve el contador: el siguiente generado es el primero de la serie.
    assert admin_client.post("/patients", json={"name": "Beto"}).json()["id"] == "p-001"


def test_alta_sin_id_saltea_un_numero_ocupado_a_mano(admin_client: TestClient):
    admin_client.post("/patients", json={"id": "p-001", "name": "Escrito a mano"})
    admin_client.post("/patients", json={"id": "p-002", "name": "Escrito a mano"})

    created = admin_client.post("/patients", json={"name": "Generado"})

    assert created.status_code == 201
    assert created.json()["id"] == "p-003", "el generado parte del más alto que ya existe"


def test_el_numero_no_se_reutiliza_al_borrar_al_ultimo(admin_client: TestClient):
    """Por eso es un contador y no un `max(id) + 1`: el id de un paciente borrado puede seguir en un turno."""
    admin_client.post("/patients", json={"name": "Ana"})
    ultimo = admin_client.post("/patients", json={"name": "Beto"}).json()["id"]
    assert admin_client.delete(f"/patients/{ultimo}").status_code == 204

    assert admin_client.post("/patients", json={"name": "Carla"}).json()["id"] == "p-003"


def test_id_vacio_explicito_sigue_siendo_invalido(admin_client: TestClient):
    """`id: ""` no es «sin id»: es un dato inválido, como hoy. Sólo la ausencia del campo genera."""
    assert admin_client.post("/patients", json={"id": "", "name": "Ana"}).status_code == 422


def test_altas_simultaneas_sin_id_no_chocan(admin_client: TestClient):
    from concurrent.futures import ThreadPoolExecutor

    def alta(i: int):
        return admin_client.post("/patients", json={"name": f"Paciente {i}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        respuestas = list(pool.map(alta, range(16)))

    assert [r.status_code for r in respuestas] == [201] * 16
    ids = [r.json()["id"] for r in respuestas]
    assert len(set(ids)) == 16
    assert sorted(ids) == [f"p-{n:03d}" for n in range(1, 17)], "sin huecos: ningún número se perdió"


def test_el_contador_nunca_entrega_el_mismo_numero_dos_veces(admin_client: TestClient):
    """El contador solo, sin el reintento por clave primaria que taparía una carrera:
    es el `UPDATE ... RETURNING` atómico lo que garantiza números distintos."""
    from concurrent.futures import ThreadPoolExecutor

    pacientes = admin_client.app.state.patients
    with ThreadPoolExecutor(max_workers=8) as pool:
        numeros = list(pool.map(lambda _: pacientes._next_number(), range(40)))

    assert sorted(numeros) == list(range(1, 41))


def test_alta_sin_id_saltea_un_numero_ocupado_despues_de_empezar_la_serie(admin_client: TestClient):
    """El otro camino: el contador ya existe y un `p-002` escrito a mano le sale al paso."""
    assert admin_client.post("/patients", json={"name": "Ana"}).json()["id"] == "p-001"
    admin_client.post("/patients", json={"id": "p-002", "name": "Escrito a mano"})

    created = admin_client.post("/patients", json={"name": "Beto"})

    assert created.status_code == 201
    assert created.json()["id"] == "p-003"
