"""
Logs: actividad del sistema y accesos, admin-only.

El mecanismo es de `libraauth.auditoria` y tiene sus propios tests en el motor.
Lo que se prueba **acá** es lo que es de este producto y nadie más puede
verificar:

1. Que la auditoría esté enganchada al session_factory del **dominio** —el de
   LibraGenda—, que es el que usan los repositorios. Cableada al engine
   equivocado no falla: simplemente no registra nada, y un log vacío se ve
   igual que un sistema donde nadie hizo nada.
2. 🔴 Que **el contenido clínico no quede escrito en el log**. Es lo propio de
   este producto y la razón por la que `app/auditoria.py` existe. Hay dos
   defensas —el diff y la descripción— y acá se ejercitan las dos por
   separado, porque tapar una sola deja pasar el dato por la otra.
3. Que la lista blanca cubra las entidades de ESTE dominio, y que las tablas
   que ya son historial no entren.
4. Que la pantalla sea admin-only.
"""

# El texto clínico de los tests: cadenas que no aparecen en ningún otro lado
# del sistema, para que buscarlas en el log entero sea una prueba concluyente y
# no una coincidencia.
TEXTO_NOTA = "refiere cefalea occipital desde hace tres semanas"
MEDICACION = "carbamazepina"
DOSIS = "200mg cada 12 horas"
DNI_PACIENTE = "28444555"
# El título de un documento clínico ya dice algo del paciente. Es el único
# campo clínico que se escribe en la DESCRIPCIÓN y no en el diff — ver
# `test_el_titulo_de_un_documento_clinico_no_queda_en_la_descripcion`.
TITULO_DOCUMENTO = "Interconsulta cardiologia por arritmia"


def _logs(client, **params) -> dict:
    r = client.get("/logs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _paciente(client, pid="pac-1", nombre="Ana Pérez", **extra) -> dict:
    cuerpo = {"id": pid, "name": nombre, **extra}
    r = client.post("/patients", json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


def _nota(client, patient_id, texto=TEXTO_NOTA) -> dict:
    r = client.post(
        f"/patients/{patient_id}/notes", json={"author": "Dr. Perez", "text": texto},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _receta(client, patient_id) -> dict:
    r = client.post(f"/patients/{patient_id}/prescriptions", json={
        "author": "Dr. Perez",
        "items": [{"medication": MEDICACION, "dosage": DOSIS, "instructions": "con las comidas"}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _documento(client, patient_id, titulo=TITULO_DOCUMENTO) -> dict:
    r = client.post(
        f"/patients/{patient_id}/documents",
        data={"author": "Dr. Perez", "title": titulo, "description": "control"},
        files={"file": ("informe.pdf", b"%PDF-1.4 contenido", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Que registre, y que lo haga contra la base del dominio ────────────────

def test_crear_un_paciente_queda_registrado(admin_client):
    """Los repositorios no llaman a nada de auditoría: el registro cuelga del
    flush del session_factory de LibraGenda. Si el cableado apuntara al engine
    de auth, esto quedaría vacío sin dar ningún error."""
    _paciente(admin_client)

    filas = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "ficha"]
    assert filas, "el alta de un paciente no dejó ninguna fila en el log"
    assert filas[0]["accion"] == "crear"
    assert filas[0]["usuario"] == "admin"


def test_tambien_registra_las_entidades_de_libragenda(admin_client):
    """La mayoría de los modelos de este producto son del motor de agenda, no
    propios: si la lista blanca se indexara por otra cosa que el nombre de
    clase, esto no entraría."""
    r = admin_client.post("/branches", json={
        "id": "centro", "name": "Sede Centro", "address": "Suipacha 123",
    })
    assert r.status_code == 201, r.text
    assert "sede" in {f["entidad"] for f in _logs(admin_client)["actividad"]}


def test_el_id_de_la_entidad_sobrevive_aunque_no_sea_un_numero(admin_client):
    """`actividad_log.entidad_id` está declarado `Integer` en el motor, pero
    en este producto casi todos los ids son `VARCHAR(100)`. Si el valor se
    perdiera o se truncara, el log diría que alguien tocó *algo* sin decir
    cuál — que es justo lo que se va a buscar cuando se lo consulte."""
    paciente = _paciente(admin_client, pid="pac-abc-123")

    fila = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "ficha"][0]
    assert str(fila["entidad_id"]) == paciente["id"]


# ── 🔴 Lo clínico no entra al log ─────────────────────────────────────────

def test_crear_lo_clinico_no_deja_su_contenido_en_el_log(admin_client):
    """Que el alta de una nota y de una receta no escriba el texto ni la
    medicación en ningún campo del log.

    ⚠️ **Este test NO ejercita `COLUMNAS_CLINICAS`** — se verificó por falla
    forzada: vaciar esa lista lo deja igual de verde. El motivo es que el
    motor sólo calcula el diff para los objetos **editados**
    (`session.dirty`); en un alta manda `cambios=None`. Lo que sostiene este
    caso es que ninguna de las dos entidades tiene atributo de etiqueta.

    Se deja igual porque es la garantía que le importa a quien lee: creada la
    nota por la vía normal, el contenido no aparece. La defensa del diff se
    prueba en `test_editar_lo_clinico_no_filtra_el_contenido`.
    """
    paciente = _paciente(admin_client)
    _nota(admin_client, paciente["id"])
    _receta(admin_client, paciente["id"])

    log = str(_logs(admin_client))
    assert TEXTO_NOTA not in log
    assert MEDICACION not in log
    assert DOSIS not in log


def test_editar_lo_clinico_no_filtra_el_contenido(admin_client):
    """La defensa del **diff**: `text` y `medication` están en
    `COLUMNAS_CLINICAS`.

    Va contra la sesión y no contra la API **a propósito**: hoy lo clínico es
    append-only (sólo POST y DELETE, ningún PUT), así que por HTTP no hay
    forma de producir una edición y la defensa quedaría sin probar. El día que
    alguien agregue un endpoint de edición —corregir una nota mal cargada es
    un pedido plausible— este test ya está puesto y la protección no depende
    de que se acuerde de mirarla.
    """
    from libragenda.database import get_session_factory

    from app.services.clinical_notes import ClinicalNoteRow

    paciente = _paciente(admin_client)
    nota = _nota(admin_client, paciente["id"])

    sessions = get_session_factory()
    with sessions() as session:
        fila = session.get(ClinicalNoteRow, nota["id"])
        fila.text = "TEXTO-CORREGIDO-" + TEXTO_NOTA
        session.commit()

    log = str(_logs(admin_client))
    assert TEXTO_NOTA not in log
    assert "TEXTO-CORREGIDO" not in log
    # Y la edición sí quedó registrada: lo que se oculta es el contenido, no
    # el hecho de que alguien lo tocó.
    ediciones = [
        f for f in _logs(admin_client)["actividad"]
        if f["entidad"] == "nota clinica" and f["accion"] == "editar"
    ]
    assert ediciones, "editar una nota clínica no dejó ninguna fila"


def test_el_titulo_de_un_documento_clinico_no_queda_en_la_descripcion(admin_client):
    """La defensa de la **descripción**: `etiqueta_segura()`.

    Un `ClinicalDocumentRow` tiene `title`, que es uno de los atributos con
    los que el motor arma la etiqueta de la fila. Sin esta defensa la
    descripción diría "Documento clinico — Interconsulta cardiologia por
    arritmia", que ya es información clínica del paciente.

    Es la **única** entidad de este producto donde la defensa de la etiqueta
    hace algo: las demás clínicas no tienen ningún atributo de los que el
    motor busca, así que su etiqueta sale vacía sola. Ver el comentario en
    `app/auditoria.py`.
    """
    paciente = _paciente(admin_client)
    _documento(admin_client, paciente["id"])

    assert TITULO_DOCUMENTO not in str(_logs(admin_client))

    doc = [
        f for f in _logs(admin_client)["actividad"] if f["entidad"] == "documento clinico"
    ][0]
    assert doc["descripcion"] == "Documento clinico"


def test_la_nota_igual_deja_rastro_de_que_alguien_la_toco(admin_client):
    """El log tiene que servir: que no diga *qué* dice la nota no significa que
    no diga que se creó una, quién y cuándo. Si esto quedara vacío, la
    redacción se habría comido la fila entera."""
    paciente = _paciente(admin_client)
    _nota(admin_client, paciente["id"])

    notas = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "nota clinica"]
    assert notas, "la nota clínica no dejó ninguna fila"
    assert notas[0]["accion"] == "crear"
    assert notas[0]["usuario"] == "admin"


def test_el_nombre_del_paciente_si_aparece_en_el_log(admin_client):
    """🟡 **Documenta una decisión, no la festeja.**

    El nombre del paciente vive en `ClientRow` (el modelo de LibraGenda), que
    **no** está en `ENTIDADES_SIN_ETIQUETA`. Así que el log dice "Paciente —
    Ana Pérez" aunque el DNI, el mail y el teléfono estén tapados.

    Es defendible: el log lo lee un admin, que ya ve los nombres en la agenda,
    y sin nombre la fila se vuelve inservible para lo único que existe —
    contestar *quién tocó qué ficha*. Pero es una decisión de privacidad, no
    un detalle técnico, y estaba implícita. Este test la deja explícita: si
    algún día se decide que el log no muestre nombres, esto se pone en rojo y
    obliga a cambiarlo a propósito.

    (De paso: `PatientRow` sí está en `ENTIDADES_SIN_ETIQUETA` y ahí es un
    no-op, porque esa tabla no tiene columna de nombre.)
    """
    _paciente(admin_client, nombre="Ana Pérez")

    paciente = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "paciente"][0]
    assert "Ana Pérez" in paciente["descripcion"]


def test_los_datos_identificatorios_del_paciente_no_entran_al_diff(admin_client):
    """El DNI, el mail y el teléfono no son contenido clínico, pero en un
    sistema de salud identifican a la persona detrás de cada fila del log."""
    paciente = _paciente(admin_client, dni=DNI_PACIENTE, email="ana@ejemplo.com")
    r = admin_client.put(f"/patients/{paciente['id']}", json={
        "name": "Ana Pérez", "dni": "30111222", "email": "otro@ejemplo.com",
    })
    assert r.status_code == 200, r.text

    log = str(_logs(admin_client))
    assert DNI_PACIENTE not in log
    assert "30111222" not in log
    assert "ana@ejemplo.com" not in log


def test_una_entidad_no_clinica_si_lleva_su_nombre(admin_client):
    """La contracara del test anterior: la redacción tiene que ser quirúrgica.
    Una sede no dice nada de ningún paciente, y sin su nombre en la
    descripción el log se vuelve ilegible."""
    r = admin_client.post("/branches", json={
        "id": "centro", "name": "Sede Centro", "address": "Suipacha 123",
    })
    assert r.status_code == 201, r.text

    sede = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "sede"][0]
    assert "Sede Centro" in sede["descripcion"]


# ── La lista blanca ───────────────────────────────────────────────────────

def test_las_entidades_del_filtro_son_las_de_este_dominio(admin_client):
    entidades = _logs(admin_client)["entidades"]
    for esperada in ("ficha", "turno", "prestacion", "sede", "nota clinica", "receta"):
        assert esperada in entidades, f"falta '{esperada}' en el filtro"


def test_lo_que_ya_es_historial_no_se_audita(admin_client):
    """La ficha del turno ya muestra sus transiciones y los recordatorios
    enviados: auditarlos pondría el mismo hecho dos veces."""
    entidades = _logs(admin_client)["entidades"]
    assert "transicion" not in entidades
    assert "recordatorio" not in entidades


def test_el_seed_de_modulos_no_ensucia_el_log(admin_client):
    """`ensure_seeded()` corre en CADA arranque del contenedor. Auditar
    `modulos` habría dejado filas de "editar módulo" en cada deploy."""
    assert "modulo" not in _logs(admin_client)["entidades"]


def test_la_alicuota_de_iva_por_prestacion_si_se_audita(admin_client):
    """Es un dato con efecto fiscal (ADR-027) y lo cambia un admin a mano:
    exactamente el caso para el que sirve un log."""
    assert "alicuota" in _logs(admin_client)["entidades"]


# ── Accesos ───────────────────────────────────────────────────────────────

def test_el_login_queda_registrado(admin_client):
    accesos = _logs(admin_client)["accesos"]
    assert accesos[0]["evento"] == "login"
    assert accesos[0]["username"] == "admin"


def test_el_intento_fallido_deja_el_usuario_tipeado(admin_client):
    admin_client.post("/auth/login", json={"username": "fantasma", "password": "x"})
    fallidos = [a for a in _logs(admin_client)["accesos"] if a["evento"] == "login_fallido"]
    assert fallidos[0]["username"] == "fantasma"


def test_la_contrasena_no_aparece_en_ningun_lado(admin_client):
    admin_client.post("/auth/login", json={"username": "admin", "password": "clave-secretisima"})
    assert "secretisima" not in str(_logs(admin_client))


# ── Permisos ──────────────────────────────────────────────────────────────

def test_el_staff_no_ve_los_logs(staff_client):
    """Acá el gate importa más que en los otros productos: la fila dice quién
    abrió la ficha de qué paciente."""
    assert staff_client.get("/logs").status_code == 403


def test_lo_que_escribe_el_staff_queda_a_su_nombre(admin_client, staff_client):
    """El usuario sale de la cookie de cada request: si quedara pegado del
    contexto anterior, el trabajo del médico aparecería como del admin."""
    paciente = _paciente(admin_client)
    _nota(staff_client, paciente["id"])

    notas = [f for f in _logs(admin_client)["actividad"] if f["entidad"] == "nota clinica"]
    assert notas and notas[0]["usuario"] == "staff-1"
