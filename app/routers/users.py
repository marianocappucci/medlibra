from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from libraauth.repository import UsernameTaken
from pydantic import BaseModel

from ..dependencies import get_user_repository
from ..services.users import UserRepository

router = APIRouter(prefix="/users", tags=["users"])

Role = Literal["admin", "staff"]


class UserCreate(BaseModel):
    # Sin `id`: libracore.db.usuarios asigna un id autoincremental --
    # ninguna otra tabla de MedLibra lo referencia como FK, así que no hay
    # ningún callsite que dependiera de elegir el id (ver
    # wiki/entities/medlibra.md "Unificación de login").
    username: str
    name: str
    password: str
    role: Role
    # Opcional: el alta se puede seguir haciendo sin correo. Es la
    # dirección a la que llega el mail de `POST /auth/forgot-password`,
    # y el ABM es el único lugar donde se carga.
    email: str = ""


class UserUpdate(BaseModel):
    name: str
    role: Role
    active: bool = True
    # `None` = "dejalo como está" en `UserRepository.update()`; `""` =
    # borralo. El default tiene que ser None porque el toggle de
    # activo/inactivo de la grilla manda este mismo cuerpo sin tocar el
    # correo -- con un default vacío, desactivar a alguien le borraba el
    # mail en silencio.
    email: str | None = None


class PasswordUpdate(BaseModel):
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    name: str
    role: str
    active: bool
    email: str = ""


@router.post("", status_code=201, response_model=UserOut)
def create_user(data: UserCreate, users: UserRepository = Depends(get_user_repository)):
    try:
        return users.create(data.username, data.name, data.password, data.role, email=data.email)
    # Excepcion de dominio de libraauth (v0.1.1+), no la del motor de storage:
    # antes esto era `except sqlite3.IntegrityError`, que filtraba la
    # implementacion sqlite3 de libracore y dejo de matchear al migrar.
    except UsernameTaken:
        raise HTTPException(409, "user already exists")


@router.get("", response_model=list[UserOut])
def list_users(users: UserRepository = Depends(get_user_repository)):
    return users.list()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, users: UserRepository = Depends(get_user_repository)):
    user = users.get_by_id(user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str, data: UserUpdate, users: UserRepository = Depends(get_user_repository),
):
    try:
        return users.update(user_id, data.name, data.role, data.active, email=data.email)
    except KeyError:
        raise HTTPException(404, "user not found")


@router.put("/{user_id}/password", status_code=204)
def update_user_password(
    user_id: str, data: PasswordUpdate, users: UserRepository = Depends(get_user_repository),
):
    # Único rechazo: la clave vacía. Sin mínimo de longitud ni de
    # complejidad -- este endpoint existe para destrabar a alguien que
    # quedó afuera, y un requisito que el administrador no puede cumplir
    # en el momento lo manda de vuelta a la base de datos. Pero `""`
    # hasheada deja la cuenta abierta con el campo en blanco, que no es
    # una contraseña floja: es ninguna.
    if not (data.password or "").strip():
        raise HTTPException(422, "la contraseña no puede estar vacía")
    try:
        users.update_password(user_id, data.password)
    except KeyError:
        raise HTTPException(404, "user not found")
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, users: UserRepository = Depends(get_user_repository)):
    try:
        users.delete(user_id)
    except KeyError:
        raise HTTPException(404, "user not found")
    return Response(status_code=204)
