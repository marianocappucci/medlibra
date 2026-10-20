"""La barra de estado del pie (libracore ADR-075, libra-ui ADR-083): `GET /api/estado-del-sistema` está montada, pide
sesión, y el respaldo y la versión del motor los ve sólo el admin."""


def test_el_admin_ve_respaldo_y_version_del_motor(admin_client):
    r = admin_client.get("/api/estado-del-sistema")
    assert r.status_code == 200
    datos = r.json()
    assert datos["usuario"]["rol"] == "admin" and datos["libraedge"] is None
    assert datos["respaldo"] is not None and datos["version"]["motor"]


def test_el_staff_no_ve_respaldo_ni_version_del_motor(staff_client):
    datos = staff_client.get("/api/estado-del-sistema").json()
    assert datos["usuario"]["rol"] == "staff"
    assert datos["respaldo"] is None and datos["arca"] is None and datos["version"]["motor"] is None
