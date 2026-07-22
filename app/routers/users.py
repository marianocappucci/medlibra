from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_user_repository
from ..services.users import UserRepository

router = APIRouter(prefix="/users", tags=["users"])

Role = Literal["admin", "staff"]


class UserCreate(BaseModel):
    id: str
    username: str
    name: str
    password: str
    role: Role


class UserUpdate(BaseModel):
    name: str
    role: Role
    active: bool = True


class PasswordUpdate(BaseModel):
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    name: str
    role: str
    active: bool


@router.post("", status_code=201, response_model=UserOut)
def create_user(data: UserCreate, users: UserRepository = Depends(get_user_repository)):
    try:
        return users.create(data.id, data.username, data.name, data.password, data.role)
    except IntegrityError:
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
        return users.update(user_id, data.name, data.role, data.active)
    except KeyError:
        raise HTTPException(404, "user not found")


@router.put("/{user_id}/password", status_code=204)
def update_user_password(
    user_id: str, data: PasswordUpdate, users: UserRepository = Depends(get_user_repository),
):
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
