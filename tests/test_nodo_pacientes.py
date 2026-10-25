# ruff: noqa: F811  -- las fixtures importadas se piden por nombre en cada test
"""Los pacientes que se dan de alta en un nodo sin conexión, y su unión en el central (ADR-045).

Lo que se fija acá:

- el paciente nace con un id provisorio `"-N"` y su operación en UNA transacción (si una falla, no queda ni el otro ni el
  número);
- el central le pone su `p-NNN`, **o lo une a la ficha que ya tenía ese DNI** (decisión del humano), una sola vez;
- las notas del paciente provisorio se traducen, y una nota que llega antes que el alta de su paciente no se pierde;
- **`patients.id` es clave primaria y foránea a la vez**: lo que el ADR-026 de LibraEdge dejó «a verificar» se mide acá contra
  el `MirrorApplier` real de LibraEdge y la ficha real de MedLibra.
"""
from __future__ import annotations

import pytest
from nodo_apoyo import (
    NODO,
    aplicar_en_el_central,
    borrar_filas,
    ejecutar,
    filas,
    nodo,  # noqa: F401  (fixture)
    nodo_apagado,  # noqa: F401  (fixture)
    operacion_de,
    operaciones,
    sembrar_consultorio,
    tipos_encolados,
)

from app import offline


def _alta_por_la_api(client, **datos) -> dict:
    r = client.post("/patients", json={"name": "Juan Pérez", **datos})
    assert r.status_code == 201, r.text
    return r.json()


def _uniones(tabla: str) -> list[tuple]:
    return filas("SELECT id_nodo, id_central FROM libraedge_mapeo_texto WHERE tabla = %s ORDER BY id_nodo", (tabla,))


# ── En el nodo ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_un_paciente_dado_de_alta_en_el_nodo_tiene_id_provisorio_y_su_operacion(admin_client, nodo):
    primero = _alta_por_la_api(admin_client, name="Ana Gómez", dni="28.111.222", phone="11-5555-0001")
    segundo = _alta_por_la_api(admin_client, name="Beto Sosa")

    assert (primero["id"], segundo["id"]) == ("-1", "-2")
    assert filas("SELECT id, name, active FROM agenda_clients ORDER BY id DESC") == [
        ("-2", "Beto Sosa", True), ("-1", "Ana Gómez", True)]
    assert filas("SELECT id, dni FROM patients WHERE id = '-1'") == [("-1", "28.111.222")]
    assert tipos_encolados() == ["paciente.alta", "paciente.alta"]
    op = operaciones()[0]
    assert op.aggregate_id == f"{NODO}:paciente:-1"
    assert op.payload["paciente_id"] == "-1" and op.payload["dni"] == "28.111.222" and op.payload["phone"] == "11-5555-0001"
    assert op.payload["creada_at"].endswith("+00:00")
    # el contador de la web no se toca: el `p-NNN` es del central
    assert filas("SELECT count(*) FROM patient_sequences") == [(0,)]


def test_el_alta_y_su_operacion_son_una_sola_transaccion(admin_client, nodo, monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("el outbox no anda")

    original = offline.encolar_operacion
    monkeypatch.setattr(offline, "encolar_operacion", falla)
    with pytest.raises(RuntimeError):
        admin_client.post("/patients", json={"name": "Ana Gómez"})
    assert filas("SELECT count(*) FROM agenda_clients") == [(0,)] and filas("SELECT count(*) FROM patients") == [(0,)]

    monkeypatch.setattr(offline, "encolar_operacion", original)
    # y el número del provisorio también se deshizo con la transacción: el próximo es el -1
    assert _alta_por_la_api(admin_client, name="Ana Gómez")["id"] == "-1"


def test_fuera_de_un_nodo_el_alta_es_la_de_siempre(admin_client, nodo_apagado):
    paciente = _alta_por_la_api(admin_client, name="Ana Gómez")
    assert paciente["id"] == "p-001"
    assert tipos_encolados() == []


def test_en_el_nodo_el_numero_del_paciente_no_se_elige(admin_client, nodo):
    r = admin_client.post("/patients", json={"id": "p-099", "name": "Ana Gómez"})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "solo_en_el_central"
    assert filas("SELECT count(*) FROM agenda_clients") == [(0,)]


def test_editar_o_borrar_un_paciente_es_409_en_el_nodo(admin_client, nodo_apagado):
    admin_client.post("/patients", json={"id": "p-001", "name": "Del Central"})
    nodo_apagado.prender()
    provisorio = _alta_por_la_api(admin_client, name="Provisorio")["id"]
    cuerpo = {"name": "Otro nombre"}

    # el del central, sin conexión: espera a la conexión; con conexión: se hace desde la web
    r = admin_client.put("/patients/p-001", json=cuerpo)
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "sin_conexion")
    r = admin_client.delete("/patients/p-001")
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "sin_conexion")
    nodo_apagado.en_linea(True)
    r = admin_client.put("/patients/p-001", json=cuerpo)
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "solo_en_el_central")

    # el provisorio ya subió con sus datos: tampoco se edita (el cambio se perdería cuando baje el definitivo)
    r = admin_client.put(f"/patients/{provisorio}", json=cuerpo)
    assert (r.status_code, r.json()["detail"]["codigo"]) == (409, "solo_en_el_central")
    assert "web" in r.json()["detail"]["mensaje"]
    assert filas("SELECT name FROM agenda_clients WHERE id = %s", (provisorio,)) == [("Provisorio",)]


def test_el_paciente_provisorio_se_ve_en_la_lista_y_en_la_ficha(admin_client, nodo):
    provisorio = _alta_por_la_api(admin_client, name="Ana Gómez")["id"]
    assert provisorio in [p["id"] for p in admin_client.get("/patients").json()]
    assert admin_client.get(f"/patients/{provisorio}").json()["name"] == "Ana Gómez"


# ── En el central ────────────────────────────────────────────────────────────────────────────────────────────────────


def _alta_en_el_nodo_y_subir(client, nodo_apagado, **datos) -> list:
    """Fase del nodo: el alta por la API. Devuelve las operaciones y deja el proceso como central, **sin** el paciente
    provisorio (en el central no existe hasta que sube)."""
    nodo_apagado.prender()
    _alta_por_la_api(client, **datos)
    ops = operaciones()
    nodo_apagado.apagar()
    borrar_filas("patients", ["-1", "-2"])
    borrar_filas("agenda_clients", ["-1", "-2"])
    return ops


def test_el_central_le_pone_su_numero_y_anota_los_dos_mapeos(admin_client, nodo_apagado):
    admin_client.post("/patients", json={"name": "Anterior"})   # p-001
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana Gómez", dni="28111222", cuit="27281112228",
                                   condicion_iva="Monotributo", birth_date="1990-05-04", email="ana@example.com")

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert filas("SELECT p.id, c.name, c.email, p.dni, p.cuit, p.condicion_iva, p.birth_date::text FROM patients p "
                 "JOIN agenda_clients c ON c.id = p.id WHERE p.dni = '28111222'") == [
        ("p-002", "Ana Gómez", "ana@example.com", "28111222", "27281112228", "Monotributo", "1990-05-04")]
    assert filas("SELECT created_at IS NOT NULL FROM patients WHERE id = 'p-002'") == [(True,)]
    assert _uniones("agenda_clients") == [("-1", "p-002")] and _uniones("patients") == [("-1", "p-002")]
    assert filas("SELECT last FROM patient_sequences") == [(2,)], "avanza el mismo contador que usa la web"
    assert admin_client.post("/patients", json={"name": "Siguiente"}).json()["id"] == "p-003"


def test_la_misma_alta_dos_veces_es_un_solo_paciente(admin_client, nodo_apagado):
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana Gómez", dni="28111222")
    reintento = operacion_de("paciente.alta", ops[0].payload, secuencia=50, agregado="paciente", id_local="-1")

    assert aplicar_en_el_central(ops + ops + [reintento]) == ["accepted", "duplicate", "accepted"]
    assert filas("SELECT count(*) FROM patients WHERE dni = '28111222'") == [(1,)]
    assert filas("SELECT count(*) FROM agenda_clients") == [(1,)]


def test_si_ya_existia_con_ese_dni_se_une_a_su_ficha_y_no_se_toca(admin_client, nodo_apagado):
    """Decisión del humano: *si ya existía con ese DNI, se une a su ficha*. Se compara sin puntos ni espacios y el central
    manda: los datos de la ficha existente no cambian."""
    admin_client.post("/patients", json={"id": "p-007", "name": "Ana Gómez", "dni": "28111222", "phone": "11-0000-0000"})
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana G.", dni="28.111.222", phone="11-9999-9999")

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert _uniones("patients") == [("-1", "p-007")] and _uniones("agenda_clients") == [("-1", "p-007")]
    assert filas("SELECT count(*) FROM patients") == [(1,)], "no se creó otro paciente"
    assert filas("SELECT c.name, c.phone FROM agenda_clients c WHERE c.id = 'p-007'") == [("Ana Gómez", "11-0000-0000")]
    assert filas("SELECT count(*) FROM patient_sequences") == [(0,)], "no gastó un número"


def test_se_une_tambien_a_un_paciente_dado_de_baja(admin_client, nodo_apagado):
    admin_client.post("/patients", json={"id": "p-007", "name": "Ana Gómez", "dni": "28111222", "active": False})
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana Gómez", dni="28111222")
    aplicar_en_el_central(ops)
    assert _uniones("patients") == [("-1", "p-007")], "la historia clínica no se parte en dos fichas"


def test_sin_dni_no_se_deduplica(admin_client, nodo_apagado):
    """Dos «Juan Pérez» sin DNI son dos pacientes: un duplicado se junta a mano; una nota atada a otra persona no se nota."""
    admin_client.post("/patients", json={"id": "p-001", "name": "Juan Pérez"})
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Juan Pérez")

    assert aplicar_en_el_central(ops) == ["accepted"]
    assert _uniones("patients") == [("-1", "p-002")]
    assert filas("SELECT count(*) FROM patients") == [(2,)]


def test_un_id_provisorio_reusado_por_otra_persona_va_a_revision_manual(admin_client, nodo_apagado):
    """Una PC reemplazada con el mismo `node_id` que arranca su secuencia de cero reusaría el `-1`: las notas a ese id irían a
    otra persona. El central lo detecta y no pisa nada."""
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana Gómez", dni="28111222")
    aplicar_en_el_central(ops)
    otra = dict(ops[0].payload, name="Otro Paciente", dni="99999999")

    resultado = aplicar_en_el_central([operacion_de("paciente.alta", otra, secuencia=9, agregado="paciente", id_local="-1")])[0]
    assert resultado.startswith("rejected") and "reusó el id provisorio" in resultado
    assert _uniones("patients") == [("-1", "p-001")]


@pytest.mark.parametrize(("cambio", "motivo"), [
    ({"paciente_id": "p-005"}, "id provisorio"),
    ({"paciente_id": "-0"}, "id provisorio"),
    ({"name": ""}, "name"),
    ({"name": "x" * 201}, "200"),
    ({"dni": "1" * 21}, "20"),
    ({"active": "si"}, "booleano"),
    ({"birth_date": "04/05/1990"}, "ISO 8601"),
    ({"creada_at": "2026-10-25T10:00:00"}, "zona"),
    ({"version": 2}, "versión"),
])
def test_un_alta_mal_formada_va_a_revision_manual_y_no_deja_nada(admin_client, nodo_apagado, cambio, motivo):
    ops = _alta_en_el_nodo_y_subir(admin_client, nodo_apagado, name="Ana Gómez", dni="28111222")
    mala = operacion_de("paciente.alta", {**ops[0].payload, **cambio}, secuencia=3, agregado="paciente", id_local="-1")

    resultado = aplicar_en_el_central([mala])[0]
    assert resultado.startswith("rejected") and motivo in resultado, resultado
    assert filas("SELECT count(*) FROM patients") == [(0,)] and _uniones("patients") == []


def test_las_notas_del_paciente_provisorio_se_traducen_a_su_numero(admin_client, nodo_apagado):
    nodo_apagado.prender()
    paciente = _alta_por_la_api(admin_client, name="Ana Gómez", dni="28111222")["id"]
    nota = admin_client.post(f"/patients/{paciente}/notes", json={"author": "Dra. Vidal", "text": "Primera consulta"}).json()
    ops = operaciones()
    nodo_apagado.apagar()
    assert [op.operation_type for op in ops] == ["paciente.alta", "nota.alta"]
    borrar_filas("clinical_notes", [nota["id"]])
    borrar_filas("patients", [paciente])
    borrar_filas("agenda_clients", [paciente])

    assert aplicar_en_el_central(ops) == ["accepted", "accepted"]
    assert filas("SELECT patient_id, text, author FROM clinical_notes WHERE id = %s", (nota["id"],)) == [
        ("p-001", "Primera consulta", "Dra. Vidal")]


def test_una_nota_que_llega_antes_que_el_alta_de_su_paciente_no_se_pierde(admin_client, nodo_apagado):
    """El orden lo da el outbox, pero si el alta quedó en revisión manual la nota se rechaza (`SinMapeo`) en vez de quedar
    atada a nadie, y se reintenta al resolverla."""
    nodo_apagado.prender()
    paciente = _alta_por_la_api(admin_client, name="Ana Gómez")["id"]
    nota = admin_client.post(f"/patients/{paciente}/notes", json={"author": "Dra. Vidal", "text": "Primera consulta"}).json()
    alta, nota_op = operaciones()
    nodo_apagado.apagar()
    borrar_filas("clinical_notes", [nota["id"]])
    borrar_filas("patients", [paciente])
    borrar_filas("agenda_clients", [paciente])

    resultado = aplicar_en_el_central([nota_op])[0]
    assert resultado.startswith("rejected") and "no esta mapeado" in resultado
    assert filas("SELECT count(*) FROM clinical_notes") == [(0,)]

    from libracore.db import core as libracore_core
    from libraedge.sync.revision import reintentar

    from app.routers.sincronizacion_offline import despachador

    assert aplicar_en_el_central([alta]) == ["accepted"]
    with libracore_core.get_connection() as conn:
        assert reintentar(conn, nota_op.operation_id, despachador, "admin").result == "accepted"
        conn.commit()
    assert filas("SELECT patient_id FROM clinical_notes WHERE id = %s", (nota["id"],)) == [("p-001",)]


# ── La guarda del espejo: lo del central no se escribe, lo provisorio sí ─────────────────────────────────────────────


def test_la_guarda_deja_pasar_las_fichas_provisorias_y_rechaza_las_del_central(admin_client, nodo_apagado):
    """LibraEdge instala en `agenda_clients` y `patients` (con alta en el nodo y de sólo lectura) un trigger que acepta los
    ids `-N` y rechaza todo lo demás con SQLSTATE `LE001`. Es lo que convierte «editar un paciente del central» en un error
    claro en vez de un cambio que el espejo pisaría."""
    import psycopg
    from libracore.db import core as libracore_core
    from libraedge.db.guarda import instalar_guarda_de_espejo

    sembrar_consultorio(admin_client)   # un paciente del central (`patient-1`) y un turno
    with libracore_core.get_connection() as conn:
        instalar_guarda_de_espejo(conn, offline.TABLAS_SOLO_LECTURA, {a.tabla: "id" for a in offline.ALTAS_EN_EL_NODO})
        conn.commit()

    ejecutar("INSERT INTO agenda_clients (id, name, active) VALUES ('-5', 'Provisorio', true)")
    ejecutar("INSERT INTO patients (id, dni) VALUES ('-5', '2')")
    ejecutar("UPDATE patients SET dni = '3' WHERE id = '-5'")
    for sql in ("UPDATE patients SET dni = '9' WHERE id = 'patient-1'", "DELETE FROM patients WHERE id = 'patient-1'",
                "UPDATE agenda_clients SET name = 'X' WHERE id = 'patient-1'", "UPDATE appointments SET status = 'completed'",
                "INSERT INTO agenda_clients (id, name, active) VALUES ('p-050', 'Inventado', true)"):
        with pytest.raises(psycopg.Error) as error:
            ejecutar(sql)
        assert error.value.sqlstate == "LE001", sql
    # pero las filas que el nodo da con uuid propio sí se escriben: no están entre las de sólo lectura
    ejecutar("INSERT INTO clinical_notes (id, patient_id, created_at, author, text) VALUES ('n1', 'patient-1', now(), 'a', 't')")
    # y lo que sale por el espejo (`libraedge.aplicando`) sí puede escribir el central
    with libracore_core.get_connection() as conn:
        from libraedge.db.guarda import marcar_aplicando
        marcar_aplicando(conn)
        conn.execute("UPDATE patients SET dni = '9' WHERE id = 'patient-1'")
        conn.commit()


# ── patients.id es clave primaria y foránea a la vez: el reapuntado de LibraEdge, contra la ficha real ───────────────────


def _espejo():
    """Un `MirrorApplier` de LibraEdge con las tablas que espeja un nodo de MedLibra, sobre la base del test."""
    from libracore.db import core as libracore_core
    from libraedge.aprovisionamiento import plan_de_publicacion
    from libraedge.sync.pull import MirrorApplier

    with libracore_core.get_connection() as conn:
        plan = plan_de_publicacion(conn, offline.aprovisionamiento)
    assert plan.faltantes == () and plan.salteadas == ()
    return libracore_core.get_connection(), dict(plan.publicables), MirrorApplier


def _cambio(cursor: int, tabla: str, fila: dict, clave: str = "id"):
    from libraedge.domain.sync import ReferenceChange, ReferenceOperation

    return ReferenceChange(cursor=cursor, table_name=tabla, row_id=str(fila[clave]), operation=ReferenceOperation.UPSERT,
                           payload=fila)


def _mapeos(provisorio: str, definitivo: str, desde: int = 1):
    ahora = "2026-10-25T10:00:00+00:00"
    return [
        _cambio(desde + i, "libraedge_mapeo_texto", {"node_id": NODO, "tabla": tabla, "id_nodo": provisorio,
                                                      "id_central": definitivo, "creado_at": ahora}, clave="id_nodo")
        for i, tabla in enumerate(("agenda_clients", "patients"))
    ]


def _estado_del_nodo() -> dict:
    return {
        "clientes": filas("SELECT id FROM agenda_clients ORDER BY id"),
        "pacientes": filas("SELECT id FROM patients ORDER BY id"),
        "notas": filas("SELECT id, patient_id FROM clinical_notes ORDER BY id"),
    }


def _preparar_ficha_definitiva_ya_bajada(admin_client, nodo_apagado):
    """El nodo con la ficha definitiva `p-007` (bajó por el espejo) y el paciente provisorio `-1` con una nota. Todavía no
    bajó el mapeo ni la nota del central."""
    admin_client.post("/patients", json={"id": "p-007", "name": "Ana Gómez", "dni": "28111222"})
    nodo_apagado.prender()
    paciente = _alta_por_la_api(admin_client, name="Ana G.", dni="28111222")["id"]
    nota = admin_client.post(f"/patients/{paciente}/notes", json={"author": "Dra. Vidal", "text": "Primera consulta"}).json()
    assert paciente == "-1"
    return nota


def test_ficha_definitiva_ya_bajada_converge_sin_perder_la_nota(admin_client, nodo_apagado):
    """Lo «a verificar» del ADR-026 de LibraEdge: el nodo ya tiene la ficha `p-007` (el central unió al paciente a una que
    existía) y su propio `patients` `-1`, cuya clave primaria es también foránea a `agenda_clients`.

    Medido contra el `MirrorApplier` real y la ficha real de MedLibra:

    1. `reapuntar` **no mueve** la fila `patients -1` a `p-007` (la clave primaria chocaría): la **borra**, porque la tabla es
       del espejo y la definitiva ya bajó con su contenido;
    2. por eso lo que cuelga de ella desde otra tabla del espejo —la nota— se **borra** también (copia local), y reapuntar
       `agenda_clients` antes que `patients` falla por la clave foránea de la nota: LibraEdge lo deshace (`SAVEPOINT`), lo
       deja en `sin_reconciliar` y lo reintenta en el barrido del final del ciclo;
    3. la nota vuelve por el espejo **con el mismo uuid**, ya en la ficha definitiva, cuando baja el cambio del central.

    Resultado: converge, sin duplicar ni perder la nota. Mientras el central no la aplica, la copia local no se ve, pero la
    operación sigue en el outbox con la nota entera."""
    nota = _preparar_ficha_definitiva_ya_bajada(admin_client, nodo_apagado)
    conn, tablas, MirrorApplier = _espejo()
    with conn:
        espejo = MirrorApplier(conn, tablas, node_id=NODO, altas=offline.ALTAS_EN_EL_NODO)
        for cambio in _mapeos("-1", "p-007"):
            espejo.aplicar(cambio)
        conn.commit()
        # `agenda_clients` va primero y no puede soltar a `patients -1` porque la nota cuelga de él...
        assert "clinical_notes_patient_id_fkey" in espejo.sin_reconciliar[("agenda_clients", "-1")]
        # ...pero `patients` sí se reapuntó: borró la ficha provisoria y, con ella, la copia local de la nota.
        assert ("patients", "-1") not in espejo.sin_reconciliar
        estado = _estado_del_nodo()
        assert estado["pacientes"] == [("p-007",)] and estado["notas"] == []
        assert tipos_encolados() == ["paciente.alta", "nota.alta"], "la nota sigue entera en el outbox"

        # Baja la nota del central: es la misma fila (mismo uuid) ya con su paciente definitivo.
        espejo.aplicar(_cambio(10, "clinical_notes", {"id": nota["id"], "patient_id": "p-007", "created_at": nota["created_at"],
                                                      "author": "Dra. Vidal", "text": "Primera consulta"}))
        conn.commit()
        # Fin del ciclo: el barrido reintenta lo que quedó, y ahora `agenda_clients -1` no tiene de qué colgar.
        assert espejo.reconciliar_pendientes() == 1
    assert espejo.sin_reconciliar == {}
    estado = _estado_del_nodo()
    assert estado["clientes"] == [("p-007",)] and estado["pacientes"] == [("p-007",)]
    assert estado["notas"] == [(nota["id"], "p-007")]


def test_si_la_nota_baja_antes_que_el_mapeo_el_reapuntado_es_directo(admin_client, nodo_apagado):
    nota = _preparar_ficha_definitiva_ya_bajada(admin_client, nodo_apagado)
    conn, tablas, MirrorApplier = _espejo()
    with conn:
        espejo = MirrorApplier(conn, tablas, node_id=NODO, altas=offline.ALTAS_EN_EL_NODO)
        espejo.aplicar(_cambio(10, "clinical_notes", {"id": nota["id"], "patient_id": "p-007", "created_at": nota["created_at"],
                                                      "author": "Dra. Vidal", "text": "Primera consulta"}))
        for cambio in _mapeos("-1", "p-007", desde=11):
            espejo.aplicar(cambio)
        conn.commit()
    assert espejo.sin_reconciliar == {}
    estado = _estado_del_nodo()
    assert estado["clientes"] == [("p-007",)] and estado["pacientes"] == [("p-007",)]
    assert estado["notas"] == [(nota["id"], "p-007")]


def test_sin_deduplicar_la_ficha_nueva_tambien_se_reapunta(admin_client, nodo_apagado):
    """El caso común: el central le dio un `p-NNN` nuevo; la ficha baja con el mapeo y el provisorio se va."""
    nodo_apagado.prender()
    _alta_por_la_api(admin_client, name="Ana Gómez")
    ejecutar("INSERT INTO agenda_clients (id, name, active) VALUES ('p-001', 'Ana Gómez', true)")
    ejecutar("INSERT INTO patients (id) VALUES ('p-001')")
    conn, tablas, MirrorApplier = _espejo()
    with conn:
        espejo = MirrorApplier(conn, tablas, node_id=NODO, altas=offline.ALTAS_EN_EL_NODO)
        for cambio in _mapeos("-1", "p-001"):
            espejo.aplicar(cambio)
        conn.commit()
        espejo.reconciliar_pendientes()
    assert filas("SELECT id FROM agenda_clients") == [("p-001",)] and filas("SELECT id FROM patients") == [("p-001",)]
    assert espejo.sin_reconciliar == {}
