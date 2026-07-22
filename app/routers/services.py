from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from libragenda import Service
from libragenda.catalog_repository import SqlAlchemyCatalogRepository

from ..dependencies import get_catalog_repository

router = APIRouter(prefix="/services", tags=["services"])


class ServiceCreate(BaseModel):
    id: str
    name: str
    duration_minutes: int
    active: bool = True


class ServiceUpdate(BaseModel):
    name: str
    duration_minutes: int
    active: bool = True


class ServiceOut(BaseModel):
    id: str
    name: str
    duration_minutes: int
    active: bool


def _to_out(service: Service) -> ServiceOut:
    return ServiceOut(
        id=service.id, name=service.name,
        duration_minutes=int(service.duration.total_seconds() // 60), active=service.active,
    )


@router.post("", status_code=201, response_model=ServiceOut)
def create_service(
    data: ServiceCreate, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        service = Service(data.id, data.name, timedelta(minutes=data.duration_minutes), data.active)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.add_service(service)
    except IntegrityError:
        raise HTTPException(409, "service already exists")
    return _to_out(service)


@router.get("", response_model=list[ServiceOut])
def list_services(catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)):
    return [_to_out(item) for item in catalog.list_services()]


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(
    service_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    service = catalog.get_service(service_id)
    if service is None:
        raise HTTPException(404, "service not found")
    return _to_out(service)


@router.put("/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: str,
    data: ServiceUpdate,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    try:
        service = Service(service_id, data.name, timedelta(minutes=data.duration_minutes), data.active)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.update_service(service_id, service)
    except KeyError:
        raise HTTPException(404, "service not found")
    return _to_out(service)


@router.delete("/{service_id}", status_code=204)
def delete_service(
    service_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        catalog.delete_service(service_id)
    except KeyError:
        raise HTTPException(404, "service not found")
    except IntegrityError:
        raise HTTPException(409, "service still has dependent records")
    return Response(status_code=204)
