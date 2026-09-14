from conftest import https_client
from fastapi.testclient import TestClient
from libraauth.testing import verificar_contrato_de_usuarios


# ── Contrato compartido (ADR-018, libraauth v0.43.0) ────────────────────────
#
# El ciclo completo (listar → alta → editar → releer → resetear contraseña →
# borrar) que ejerce el backoffice ya no se prueba a mano acá: lo corre
# `libraauth.testing`, con los MISMOS modelos públicos que usa la factory, así
# que este test y `build_users_router()` no pueden divergir entre sí. Antes
# vivía repartido en `test_admin_can_create_list_and_get_a_staff_user` y
# `test_delete_user`, que se sacaron de acá por quedar redundantes con esto.
#
# Lo que el helper NO prueba -- las reglas de negocio de la factory (rol
# inválido, username duplicado, protecciones del único admin) -- se prueban
# UNA sola vez en la suite de `libraauth`, no en cada producto (ver el
# docstring de `verificar_contrato_de_usuarios`). Lo que sigue abajo es sólo
# lo propio de MedLibra: que la tupla `roles=("admin","staff")` con la que se
# armó el router acá es la correcta, la integración con el login/sesión de
# este producto, y el correo, que este archivo ya cubría antes de la factory.
def test_contrato_de_usuarios(admin_client: TestClient):
    verificar_contrato_de_usuarios(admin_client, "/users", role="staff")


def test_create_response_never_leaks_the_password(admin_client: TestClient):
    """`verificar_contrato_de_usuarios` no lo mira -- comparte los mismos
    modelos públicos que el router, así que un campo que la factory agregara
    al modelo de salida se colaría en los dos lados por igual. Esto es lo que
    ya probaba `test_admin_can_create_list_and_get_a_staff_user` antes de la
    migración; se preserva la aserción, no el resto del test (redundante con
    el contrato de arriba)."""
    body = admin_client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    }).json()
    assert "password" not in body
    assert "password_hash" not in body


def test_update_user_rejects_invalid_role_returns_422_not_500(admin_client: TestClient):
    """El caso que motivó la migración según la ADR-018 -- pero medido, no
    heredado del README: con el router VIEJO de este archivo esto YA daba 422
    y no 500, porque `UserUpdate.role` estaba tipado `Literal["admin",
    "staff"]` y pydantic lo rechazaba antes de que el handler (que no
    atrapaba el `ValueError` de `UserRepository.update()`) llegara a correr.
    Se corrió este mismo test contra el router viejo, con Postgres real,
    antes de tocar nada: pasó (422), no lo tumbó ninguna mutación. Queda igual
    como regresión -- la fuente de la validación cambió (de un tipo fijo del
    modelo a la tupla `roles` de la factory) y este test es lo que nota si
    alguna vuelve a dejar escapar el `ValueError`."""
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    }).json()
    response = admin_client.put(f"/users/{created['id']}", json={
        "name": "Dr. Perez", "role": "owner", "active": True,
    })
    assert response.status_code == 422


def test_create_user_rejects_invalid_role(admin_client: TestClient):
    response = admin_client.post("/users", json={
        "username": "u1", "name": "X", "password": "pw", "role": "owner",
    })
    assert response.status_code == 422


def test_create_user_duplicate_username_returns_409(admin_client: TestClient):
    admin_client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    })
    response = admin_client.post("/users", json={
        "username": "staff-1", "name": "Otro",
        "password": "s3cret", "role": "staff",
    })
    assert response.status_code == 409


def test_update_user_role_and_deactivate(admin_client: TestClient):
    client = admin_client
    created = client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    }).json()
    updated = client.put(f"/users/{created['id']}", json={
        "name": "Dr. Perez (jefe)", "role": "admin", "active": False,
    })
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == created["id"]
    assert body["username"] == "staff-1"
    assert body["name"] == "Dr. Perez (jefe)"
    assert body["role"] == "admin"
    assert body["active"] is False


def test_update_user_not_found_returns_404(admin_client: TestClient):
    response = admin_client.put("/users/missing", json={
        "name": "X", "role": "staff", "active": True,
    })
    assert response.status_code == 404


def test_deactivated_user_cannot_log_in(admin_client: TestClient):
    client = admin_client
    created = client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "s3cret", "role": "staff",
    }).json()
    client.put(f"/users/{created['id']}", json={"name": "Dr. Perez", "role": "staff", "active": False})

    other = https_client(client.app)
    response = other.post("/auth/login", json={"username": "staff-1", "password": "s3cret"})
    assert response.status_code == 401


def test_update_password_then_login_with_new_password(admin_client: TestClient):
    client = admin_client
    created = client.post("/users", json={
        "username": "staff-1", "name": "Dr. Perez",
        "password": "old-pass", "role": "staff",
    }).json()
    assert client.put(f"/users/{created['id']}/password", json={"password": "new-pass"}).status_code == 204

    other = https_client(client.app)
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "old-pass"},
    ).status_code == 401
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "new-pass"},
    ).status_code == 200


def test_delete_user_not_found_returns_404(admin_client: TestClient):
    assert admin_client.delete("/users/missing").status_code == 404


def test_staff_cannot_manage_users(staff_client: TestClient):
    assert staff_client.get("/users").status_code == 403
    assert staff_client.post("/users", json={
        "username": "x", "name": "X", "password": "pw", "role": "staff",
    }).status_code == 403


# ── Contraseña ajena y correo ────────────────────────────────────────────────
#
# El endpoint de contraseña ya existía acá (no así en LibraDesk ni VentaLibra),
# pero **ninguna pantalla lo llamaba**: la grilla de usuarios de `libra-ui`, que
# es la misma para los cuatro productos, no ofrecía la acción. Se encontró el
# 2026-08-18 porque un usuario de una instancia de LibraDesk olvidó su
# contraseña y no había forma de recuperarla — ni propia (el ABM nunca cargaba
# un correo al que mandar el mail de recuperación) ni del administrador.
#
# Lo que llega acá es el correo, la guarda contra la clave vacía, y la
# cobertura de que una edición común no pise ninguna de las dos cosas.


def test_update_password_rejects_an_empty_password(admin_client: TestClient):
    """No alcanza con asertar el 422: un endpoint que devolviera 422 *después*
    de haber hasheado el vacío daría el mismo código y la cuenta quedaría
    abierta con el campo en blanco. Lo que prueba la guarda es que la
    contraseña anterior sigue entrando."""
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Empleada",
        "password": "old-pass", "role": "staff",
    }).json()

    for empty in ("", "   "):
        response = admin_client.put(f"/users/{created['id']}/password", json={"password": empty})
        assert response.status_code == 422, f"{empty!r} tendría que rechazarse"

    other = https_client(admin_client.app)
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "old-pass"},
    ).status_code == 200


def test_update_password_now_requires_a_minimum_of_six(admin_client: TestClient):
    """🔴 Cambio de comportamiento visible (ADR-018, libraauth v0.43.0).

    Hasta la adopción de la factory este test se llamaba
    `test_update_password_has_no_minimum_length` y afirmaba justo lo
    contrario: que una contraseña de un solo caracter SÍ se aceptaba en el
    reset de otro usuario, a propósito ("este endpoint existe para destrabar
    a alguien que quedó afuera"). La factory unifica el mínimo de 6
    caracteres (`MIN_PASSWORD_LENGTH`) para el alta Y el reset -- antes sólo
    se exigía en el alta, acá tampoco. Sigue sin haber política de
    complejidad, sólo longitud."""
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Empleada",
        "password": "old-pass", "role": "staff",
    }).json()

    response = admin_client.put(
        f"/users/{created['id']}/password", json={"password": "abcde"},
    )
    assert response.status_code == 422

    other = https_client(admin_client.app)
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "old-pass"},
    ).status_code == 200

    assert admin_client.put(
        f"/users/{created['id']}/password", json={"password": "abcdef"},
    ).status_code == 204
    assert other.post(
        "/auth/login", json={"username": "staff-1", "password": "abcdef"},
    ).status_code == 200


def test_staff_cannot_change_another_users_password(
    admin_client: TestClient, staff_client: TestClient,
):
    """El router entero cuelga del gate de admin, así que la ruta hereda la
    exigencia. Se cubre igual: el día que alguien la monte aparte, el gate se
    pierde sin que nada avise."""
    created = admin_client.post("/users", json={
        "username": "victima", "name": "Víctima",
        "password": "old-pass", "role": "staff",
    }).json()
    assert staff_client.put(
        f"/users/{created['id']}/password", json={"password": "tomada"},
    ).status_code == 403


def test_create_user_stores_and_returns_the_email(admin_client: TestClient):
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Empleada", "password": "s3cret",
        "role": "staff", "email": "empleada@empresa.com",
    })
    assert created.status_code == 201
    assert created.json()["email"] == "empleada@empresa.com"

    fetched = admin_client.get(f"/users/{created.json()['id']}")
    assert fetched.json()["email"] == "empleada@empresa.com"


def test_updating_name_or_role_does_not_wipe_the_email(admin_client: TestClient):
    """La razón por la que `UserUpdate.email` es `None` y no `""`.

    El toggle de activo/inactivo de la grilla manda el cuerpo entero sin tocar
    el correo. Con un default vacío, desactivar a alguien le borraba el mail en
    silencio — y el mail es lo único que le permite recuperar la contraseña.
    """
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Empleada", "password": "s3cret",
        "role": "staff", "email": "empleada@empresa.com",
    }).json()

    updated = admin_client.put(f"/users/{created['id']}", json={
        "name": "Empleada Senior", "role": "staff", "active": False,
    })
    assert updated.status_code == 200
    assert updated.json()["email"] == "empleada@empresa.com"
    assert updated.json()["name"] == "Empleada Senior"


def test_the_email_can_be_cleared_on_purpose(admin_client: TestClient):
    """La contracara del anterior: `""` explícito sí lo borra. Sin esto, un
    correo cargado mal no se podría sacar nunca."""
    created = admin_client.post("/users", json={
        "username": "staff-1", "name": "Empleada", "password": "s3cret",
        "role": "staff", "email": "mal@escrito.com",
    }).json()

    updated = admin_client.put(f"/users/{created['id']}", json={
        "name": "Empleada", "role": "staff", "active": True, "email": "",
    })
    assert updated.status_code == 200
    assert updated.json()["email"] == ""
