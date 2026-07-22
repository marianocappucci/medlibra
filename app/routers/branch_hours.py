from datetime import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..dependencies import get_branch_hours_repository
from ..services.branch_hours import BranchHoursRepository

router = APIRouter(prefix="/branches/{branch_id}/hours", tags=["branch-hours"])


class HoursCreate(BaseModel):
    weekday: int
    starts_at: time
    ends_at: time


class HoursOut(BaseModel):
    id: int
    branch_id: str
    weekday: int
    starts_at: time
    ends_at: time


@router.post("", status_code=201, response_model=HoursOut)
def create_hours(
    branch_id: str, data: HoursCreate,
    hours: BranchHoursRepository = Depends(get_branch_hours_repository),
):
    try:
        return hours.create(branch_id, data.weekday, data.starts_at, data.ends_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("", response_model=list[HoursOut])
def list_hours(branch_id: str, hours: BranchHoursRepository = Depends(get_branch_hours_repository)):
    return hours.list_for_branch(branch_id)


@router.put("/{hours_id}", response_model=HoursOut)
def update_hours(
    branch_id: str, hours_id: int, data: HoursCreate,
    hours: BranchHoursRepository = Depends(get_branch_hours_repository),
):
    try:
        return hours.update(hours_id, data.weekday, data.starts_at, data.ends_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, "hours not found")


@router.delete("/{hours_id}", status_code=204)
def delete_hours(
    branch_id: str, hours_id: int,
    hours: BranchHoursRepository = Depends(get_branch_hours_repository),
):
    try:
        hours.delete(hours_id)
    except KeyError:
        raise HTTPException(404, "hours not found")
    return Response(status_code=204)
