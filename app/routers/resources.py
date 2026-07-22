from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from libragenda import Resource
from libragenda.catalog_repository import SqlAlchemyCatalogRepository

from ..dependencies import get_catalog_repository

router = APIRouter(prefix="/resources", tags=["resources"])


class ResourceCreate(BaseModel):
    id: str
    name: str
    branch_id: str | None = None
    active: bool = True


class ResourceUpdate(BaseModel):
    name: str
    branch_id: str | None = None
    active: bool = True


class ResourceOut(BaseModel):
    id: str
    name: str
    branch_id: str | None
    active: bool


def _to_out(resource: Resource) -> ResourceOut:
    return ResourceOut(
        id=resource.id, name=resource.name,
        branch_id=resource.branch_id, active=resource.active,
    )


@router.post("", status_code=201, response_model=ResourceOut)
def create_resource(
    data: ResourceCreate, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        resource = Resource(data.id, data.name, data.branch_id, data.active)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.add_resource(resource)
    except IntegrityError:
        raise HTTPException(409, "resource already exists")
    return _to_out(resource)


@router.get("", response_model=list[ResourceOut])
def list_resources(catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)):
    return [_to_out(item) for item in catalog.list_resources()]


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(
    resource_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    resource = catalog.get_resource(resource_id)
    if resource is None:
        raise HTTPException(404, "resource not found")
    return _to_out(resource)


@router.put("/{resource_id}", response_model=ResourceOut)
def update_resource(
    resource_id: str,
    data: ResourceUpdate,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    try:
        resource = Resource(resource_id, data.name, data.branch_id, data.active)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.update_resource(resource_id, resource)
    except KeyError:
        raise HTTPException(404, "resource not found")
    return _to_out(resource)


@router.delete("/{resource_id}", status_code=204)
def delete_resource(
    resource_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        catalog.delete_resource(resource_id)
    except KeyError:
        raise HTTPException(404, "resource not found")
    return Response(status_code=204)
