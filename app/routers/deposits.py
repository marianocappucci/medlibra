from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from libragenda import Deposit, DepositManager, DepositNotFound, InvalidDepositTransition
from libragenda.repositories import DepositRepository

from ..dependencies import get_deposit_manager, get_deposit_repository

request_router = APIRouter(prefix="/appointments/{appointment_id}/deposit", tags=["deposits"])
admin_router = APIRouter(prefix="/deposits", tags=["deposits"])


class DepositRequest(BaseModel):
    amount: Decimal


class MarkPaidRequest(BaseModel):
    medio_pago: str | None = None


class DepositOut(BaseModel):
    id: str
    appointment_id: str
    amount: Decimal
    status: str
    medio_pago: str | None = None


def _to_out(deposit: Deposit) -> DepositOut:
    return DepositOut(
        id=deposit.id, appointment_id=deposit.appointment_id,
        amount=deposit.amount, status=deposit.status.value, medio_pago=deposit.medio_pago,
    )


@request_router.post("", status_code=201, response_model=DepositOut)
def request_deposit(
    appointment_id: str, data: DepositRequest,
    manager: DepositManager = Depends(get_deposit_manager),
):
    try:
        return _to_out(manager.request(str(uuid4()), appointment_id, data.amount))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@request_router.get("", response_model=DepositOut)
def get_deposit(appointment_id: str, deposits: DepositRepository = Depends(get_deposit_repository)):
    deposit = deposits.get_by_appointment(appointment_id)
    if deposit is None:
        raise HTTPException(404, "deposit not found")
    return _to_out(deposit)


@admin_router.post("/{deposit_id}/mark-paid", response_model=DepositOut)
def mark_paid(
    deposit_id: str, data: MarkPaidRequest = MarkPaidRequest(),
    manager: DepositManager = Depends(get_deposit_manager),
):
    try:
        return _to_out(manager.mark_paid(deposit_id, medio_pago=data.medio_pago))
    except DepositNotFound:
        raise HTTPException(404, "deposit not found")
    except InvalidDepositTransition as exc:
        raise HTTPException(409, str(exc))


@admin_router.post("/{deposit_id}/mark-failed", response_model=DepositOut)
def mark_failed(deposit_id: str, manager: DepositManager = Depends(get_deposit_manager)):
    try:
        return _to_out(manager.mark_failed(deposit_id))
    except DepositNotFound:
        raise HTTPException(404, "deposit not found")
    except InvalidDepositTransition as exc:
        raise HTTPException(409, str(exc))


@admin_router.post("/{deposit_id}/refund", response_model=DepositOut)
def refund(deposit_id: str, manager: DepositManager = Depends(get_deposit_manager)):
    try:
        return _to_out(manager.request_refund(deposit_id))
    except DepositNotFound:
        raise HTTPException(404, "deposit not found")
    except InvalidDepositTransition as exc:
        raise HTTPException(409, str(exc))
