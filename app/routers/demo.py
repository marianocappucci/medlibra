"""Placeholder catalog bootstrap until real CRUD for branches/resources/
services exists (see TASKS.md "Próximas") -- same role /demo/seed played in
Gestiolibra before its own catalog CRUD round. Patients are real already
(see routers/patients.py); this only covers what's still missing.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from libragenda import Branch, Resource, Service
from libragenda.catalog_repository import SqlAlchemyCatalogRepository

from ..dependencies import get_catalog_repository

router = APIRouter(prefix="/demo", tags=["demo"])


class SeedRequest(BaseModel):
    resource_id: str
    resource_name: str
    service_id: str
    service_name: str
    duration_minutes: int = 30


@router.post("/seed")
def seed(
    data: SeedRequest, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    catalog.add_branch(Branch("demo-branch", "Consultorio demo"))
    catalog.add_resource(Resource(data.resource_id, data.resource_name, "demo-branch"))
    catalog.add_service(
        Service(data.service_id, data.service_name, timedelta(minutes=data.duration_minutes)),
    )
    return {"ok": True}
