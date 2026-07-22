from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from libragenda import Branch
from libragenda.catalog_repository import SqlAlchemyCatalogRepository

from ..dependencies import get_catalog_repository

router = APIRouter(prefix="/branches", tags=["branches"])


class BranchCreate(BaseModel):
    id: str
    name: str
    active: bool = True
    timezone: str = "UTC"


class BranchUpdate(BaseModel):
    name: str
    active: bool = True
    timezone: str = "UTC"


class BranchOut(BaseModel):
    id: str
    name: str
    active: bool
    timezone: str


def _to_out(branch: Branch) -> BranchOut:
    return BranchOut(id=branch.id, name=branch.name, active=branch.active, timezone=branch.timezone)


@router.post("", status_code=201, response_model=BranchOut)
def create_branch(
    data: BranchCreate, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        branch = Branch(data.id, data.name, data.active, data.timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.add_branch(branch)
    except IntegrityError:
        raise HTTPException(409, "branch already exists")
    return _to_out(branch)


@router.get("", response_model=list[BranchOut])
def list_branches(catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)):
    return [_to_out(item) for item in catalog.list_branches()]


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(
    branch_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    branch = catalog.get_branch(branch_id)
    if branch is None:
        raise HTTPException(404, "branch not found")
    return _to_out(branch)


@router.put("/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: str,
    data: BranchUpdate,
    catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository),
):
    try:
        branch = Branch(branch_id, data.name, data.active, data.timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        catalog.update_branch(branch_id, branch)
    except KeyError:
        raise HTTPException(404, "branch not found")
    return _to_out(branch)


@router.delete("/{branch_id}", status_code=204)
def delete_branch(
    branch_id: str, catalog: SqlAlchemyCatalogRepository = Depends(get_catalog_repository)
):
    try:
        catalog.delete_branch(branch_id)
    except KeyError:
        raise HTTPException(404, "branch not found")
    return Response(status_code=204)
