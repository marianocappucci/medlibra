"""Datos del consultorio, logo y Datos / Backup — ítems 1, 4 y 5.

Hasta hoy este producto **no tenía ninguna pantalla de configuración**.

El mecanismo es de `libracore` y tiene sus propios tests ahí. Lo que se prueba
acá es lo que sólo este producto puede verificar, y es más que en los otros:

1. 🔴 Que el backup traiga **las dos bases y los documentos clínicos**. Los
   estudios y las interconsultas subidas son archivos en disco: un backup "de
   la base" los deja afuera enteros y el usuario se lleva un ZIP creyendo que
   tiene los estudios de sus pacientes. No falla de ninguna forma visible.
2. Que después de restaurar la app sirva los datos nuevos.
3. Que todo sea admin-only.
"""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from motor_de_test import url_para_archivo


def https_client(app) -> TestClient:
    """Igual que el de `conftest.py`: la cookie de sesión es Secure y httpx no
    la reenvía sobre http plano ni con un host de un solo label. No se importa
    de allá porque `tests/` no es un paquete."""
    return TestClient(app, base_url="https://medlibra.test")


@pytest.fixture
def admin_client(tmp_path):
    """⚠️ Fixture propia, con la base del dominio **en un archivo real**.

    La de `conftest.py` usa `sqlite:///:memory:`, y para estos tests no sirve
    por dos motivos, los dos artefactos del entorno y no del producto:

    1. No hay archivo que respaldar, así que el ZIP saldría con una sola base
       y el test de las dos bases fallaría por el motivo equivocado.
    2. `engine.dispose()` sobre una base en memoria **la borra**: la base vive
       en la conexión. En producción siempre es un archivo.

    🔴 Por `url_para_archivo()` y no con la URL escrita a mano: contra
    PostgreSQL no hay archivo, y con la cadena fija el dominio quedaba en un
    `.db` mientras LibraCore iba a la base nueva. El ZIP salía con una sola
    base y el test fallaba por el cableado del test, no por el producto.
    """
    app = create_app(url_para_archivo(tmp_path / "medlibra.db"))
    with https_client(app) as client:
        r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
        assert r.status_code == 200, r.text
        yield client


@pytest.fixture
def staff_client(admin_client: TestClient):
    creado = admin_client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "staff-pass", "role": "staff",
    })
    assert creado.status_code == 201, creado.text
    with https_client(admin_client.app) as client:
        r = client.post("/auth/login", json={"username": "staff-1", "password": "staff-pass"})
        assert r.status_code == 200, r.text
        yield client


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 40


def _paciente(client, pid="pac-1", nombre="Ana Pérez"):
    r = client.post("/patients", json={"id": pid, "name": nombre})
    assert r.status_code == 201, r.text
    return r.json()


def _documento(client, patient_id, titulo="Interconsulta"):
    r = client.post(
        f"/patients/{patient_id}/documents",
        data={"author": "Dr. Perez", "title": titulo, "description": "control"},
        files={"file": ("estudio.pdf", b"%PDF-1.4 estudio real", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── 🔴 Las dos bases y los documentos ─────────────────────────────────────

def test_el_backup_trae_las_dos_bases(admin_client):
    _paciente(admin_client)

    r = admin_client.get("/api/config/backup-ahora")
    assert r.status_code == 200, r.text

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        bases = sorted(n for n in z.namelist() if n.startswith("bases/"))

    assert len(bases) == 2, f"esperaba dos bases, vinieron {bases}"
    # "core" y no "libracore" porque el nombre depende del motor: en SQLite es
    # el archivo `medlibra_libracore.db` y en PostgreSQL el dump de la base
    # `medlibra_core`. Lo que se prueba es que la mitad de usuarios/facturación
    # esté, no cómo se llama el archivo.
    assert any("core" in b for b in bases), f"falta la base de usuarios: {bases}"


def test_el_backup_trae_los_documentos_clinicos(admin_client):
    """🔴 Son archivos en disco, no filas. Un backup que sólo tome las bases
    deja los estudios afuera y el usuario no tiene cómo darse cuenta: el ZIP se
    descarga igual."""
    paciente = _paciente(admin_client)
    _documento(admin_client, paciente["id"])

    r = admin_client.get("/api/config/backup-ahora")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        documentos = [n for n in z.namelist() if "documents" in n and n.startswith("datos/")]
        assert documentos, f"faltan los documentos clínicos: {z.namelist()}"
        # Y que traigan el contenido real, no un archivo vacío.
        assert b"estudio real" in z.read(documentos[0])


# ── El restore tiene efecto ───────────────────────────────────────────────

def test_despues_de_restaurar_la_app_sirve_los_datos_nuevos(admin_client):
    _paciente(admin_client, "pac-antes", "Antes del backup")
    copia = admin_client.get("/api/config/backup-ahora").content

    _paciente(admin_client, "pac-despues", "Después del backup")

    r = admin_client.post("/api/config/restore",
                          files={"backup_file": ("b.zip", copia, "application/zip")})
    assert r.status_code == 200, r.text

    ids = [p["id"] for p in admin_client.get("/patients").json()]
    assert "pac-antes" in ids
    assert "pac-despues" not in ids


def test_restaurar_devuelve_tambien_los_documentos(admin_client):
    """La contracara del test de arriba: que el ZIP los traiga no alcanza si el
    restore no los vuelve a poner."""
    paciente = _paciente(admin_client)
    doc = _documento(admin_client, paciente["id"])
    copia = admin_client.get("/api/config/backup-ahora").content

    borrado = admin_client.delete(f"/patients/{paciente['id']}/documents/{doc['id']}")
    assert borrado.status_code == 204, borrado.text

    admin_client.post("/api/config/restore",
                      files={"backup_file": ("b.zip", copia, "application/zip")})

    bajado = admin_client.get(f"/patients/{paciente['id']}/documents/{doc['id']}/file")
    assert bajado.status_code == 200, bajado.text
    assert b"estudio real" in bajado.content


def test_la_sesion_sobrevive_al_restore(admin_client):
    copia = admin_client.get("/api/config/backup-ahora").content
    admin_client.post("/api/config/restore",
                      files={"backup_file": ("b.zip", copia, "application/zip")})

    assert admin_client.get("/auth/me").status_code == 200


# ── Empresa, logo y gates ─────────────────────────────────────────────────

def test_guardar_y_leer_los_datos_del_consultorio(admin_client):
    r = admin_client.put("/api/config/empresa", json={
        "empresa_nombre": "Centro Médico Suipacha", "empresa_cuit": "30-11111111-9",
    })
    assert r.status_code == 200, r.text
    assert admin_client.get("/api/config/empresa").json()["empresa_cuit"] == "30-11111111-9"


def test_subir_y_bajar_el_logo(admin_client):
    r = admin_client.post("/api/config/empresa/logo",
                          files={"logo": ("l.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    assert admin_client.get("/api/config/empresa/logo").content == _png()


def test_el_staff_no_ve_nada_de_configuracion(staff_client):
    """Acá el backup es lo más sensible de toda la familia: se lleva las
    historias clínicas enteras."""
    for ruta in ("/api/config/empresa", "/api/config/backups", "/api/config/backup-ahora"):
        assert staff_client.get(ruta).status_code == 403, ruta


def test_el_staff_no_restaura(staff_client):
    r = staff_client.post("/api/config/restore",
                          files={"backup_file": ("b.zip", b"x", "application/zip")})
    assert r.status_code == 403
