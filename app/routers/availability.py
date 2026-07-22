"""CRUD for a resource's weekly windows, point-in-time blocks and date
exceptions — the three concepts LibraGenda uses to decide when a resource
can receive an appointment (see AppointmentService.create, which reads
this configuration instead of a hardcoded window)."""

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from libragenda import Availability
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.scheduling import AvailabilityException, TimeBlock

from ..dependencies import get_availability_repository

router = APIRouter(prefix="/resources/{resource_id}", tags=["availability"])


# -- weekly windows ------------------------------------------------------

class AvailabilityCreate(BaseModel):
    weekday: int
    starts_at: time
    ends_at: time


class AvailabilityOut(BaseModel):
    id: int
    resource_id: str
    weekday: int
    starts_at: time
    ends_at: time


def _availability_out(availability_id: int, item: Availability) -> AvailabilityOut:
    return AvailabilityOut(
        id=availability_id, resource_id=item.resource_id,
        weekday=item.weekday, starts_at=item.starts_at, ends_at=item.ends_at,
    )


@router.post("/availability", status_code=201, response_model=AvailabilityOut)
def create_availability(
    resource_id: str, data: AvailabilityCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = Availability(resource_id, data.weekday, data.starts_at, data.ends_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    availability_id = repo.add_availability(item)
    return _availability_out(availability_id, item)


@router.get("/availability", response_model=list[AvailabilityOut])
def list_availability(
    resource_id: str,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    return [_availability_out(i, item) for i, item in repo.list_availability(resource_id)]


@router.put("/availability/{availability_id}", response_model=AvailabilityOut)
def update_availability(
    resource_id: str, availability_id: int, data: AvailabilityCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = Availability(resource_id, data.weekday, data.starts_at, data.ends_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        repo.update_availability(availability_id, item)
    except KeyError:
        raise HTTPException(404, "availability window not found")
    return _availability_out(availability_id, item)


@router.delete("/availability/{availability_id}", status_code=204)
def delete_availability(
    resource_id: str, availability_id: int,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        repo.delete_availability(availability_id)
    except KeyError:
        raise HTTPException(404, "availability window not found")
    return Response(status_code=204)


# -- point-in-time blocks --------------------------------------------------

class BlockCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str = ""


class BlockOut(BaseModel):
    id: int
    resource_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str


def _block_out(block_id: int, item: TimeBlock) -> BlockOut:
    return BlockOut(
        id=block_id, resource_id=item.resource_id,
        starts_at=item.starts_at, ends_at=item.ends_at, reason=item.reason,
    )


@router.post("/blocks", status_code=201, response_model=BlockOut)
def create_block(
    resource_id: str, data: BlockCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = TimeBlock(resource_id, data.starts_at, data.ends_at, data.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    block_id = repo.add_block(item)
    return _block_out(block_id, item)


@router.get("/blocks", response_model=list[BlockOut])
def list_blocks(
    resource_id: str,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    return [_block_out(i, item) for i, item in repo.list_blocks(resource_id)]


@router.put("/blocks/{block_id}", response_model=BlockOut)
def update_block(
    resource_id: str, block_id: int, data: BlockCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = TimeBlock(resource_id, data.starts_at, data.ends_at, data.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        repo.update_block(block_id, item)
    except KeyError:
        raise HTTPException(404, "block not found")
    return _block_out(block_id, item)


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(
    resource_id: str, block_id: int,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        repo.delete_block(block_id)
    except KeyError:
        raise HTTPException(404, "block not found")
    return Response(status_code=204)


# -- date-specific exceptions -----------------------------------------------

class ExceptionCreate(BaseModel):
    day: date
    starts_at: time
    ends_at: time
    available: bool = False


class ExceptionOut(BaseModel):
    id: int
    resource_id: str
    day: date
    starts_at: time
    ends_at: time
    available: bool


def _exception_out(exception_id: int, item: AvailabilityException) -> ExceptionOut:
    return ExceptionOut(
        id=exception_id, resource_id=item.resource_id, day=item.day,
        starts_at=item.starts_at, ends_at=item.ends_at, available=item.available,
    )


@router.post("/exceptions", status_code=201, response_model=ExceptionOut)
def create_exception(
    resource_id: str, data: ExceptionCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = AvailabilityException(
            resource_id, data.day, data.starts_at, data.ends_at, data.available,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    exception_id = repo.add_exception(item)
    return _exception_out(exception_id, item)


@router.get("/exceptions", response_model=list[ExceptionOut])
def list_exceptions(
    resource_id: str,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    return [_exception_out(i, item) for i, item in repo.list_exceptions(resource_id)]


@router.put("/exceptions/{exception_id}", response_model=ExceptionOut)
def update_exception(
    resource_id: str, exception_id: int, data: ExceptionCreate,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        item = AvailabilityException(
            resource_id, data.day, data.starts_at, data.ends_at, data.available,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        repo.update_exception(exception_id, item)
    except KeyError:
        raise HTTPException(404, "exception not found")
    return _exception_out(exception_id, item)


@router.delete("/exceptions/{exception_id}", status_code=204)
def delete_exception(
    resource_id: str, exception_id: int,
    repo: SqlAlchemyAvailabilityRepository = Depends(get_availability_repository),
):
    try:
        repo.delete_exception(exception_id)
    except KeyError:
        raise HTTPException(404, "exception not found")
    return Response(status_code=204)
