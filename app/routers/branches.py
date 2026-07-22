from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_branch_repository
from ..services.branches import BranchRepository

router = APIRouter(prefix="/branches", tags=["branches"])


class BranchCreate(BaseModel):
    id: str
    name: str
    active: bool = True
    timezone: str = "UTC"
    phone: str | None = None
    address: str | None = None


class BranchUpdate(BaseModel):
    name: str
    active: bool = True
    timezone: str = "UTC"
    phone: str | None = None
    address: str | None = None


class BranchOut(BaseModel):
    id: str
    name: str
    active: bool
    timezone: str
    phone: str | None
    address: str | None


@router.post("", status_code=201, response_model=BranchOut)
def create_branch(data: BranchCreate, branches: BranchRepository = Depends(get_branch_repository)):
    try:
        return branches.create(
            data.id, data.name, data.active, data.timezone, data.phone, data.address,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except IntegrityError:
        raise HTTPException(409, "branch already exists")


@router.get("", response_model=list[BranchOut])
def list_branches(branches: BranchRepository = Depends(get_branch_repository)):
    return branches.list()


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(branch_id: str, branches: BranchRepository = Depends(get_branch_repository)):
    branch = branches.get(branch_id)
    if branch is None:
        raise HTTPException(404, "branch not found")
    return branch


@router.put("/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: str,
    data: BranchUpdate,
    branches: BranchRepository = Depends(get_branch_repository),
):
    try:
        return branches.update(
            branch_id, data.name, data.active, data.timezone, data.phone, data.address,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, "branch not found")


@router.delete("/{branch_id}", status_code=204)
def delete_branch(branch_id: str, branches: BranchRepository = Depends(get_branch_repository)):
    try:
        branches.delete(branch_id)
    except KeyError:
        raise HTTPException(404, "branch not found")
    except IntegrityError:
        raise HTTPException(409, "branch still has dependent records")
    return Response(status_code=204)
