from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import require_admin
from ..dependencies import get_patient_repository, get_study_order_repository
from ..services.patients import PatientRepository
from ..services.study_orders import StudyOrderRepository

router = APIRouter(prefix="/patients/{patient_id}/study-orders", tags=["study-orders"])


class StudyOrderItemCreate(BaseModel):
    study_type: str
    reason: str | None = None


class StudyOrderCreate(BaseModel):
    author: str
    items: list[StudyOrderItemCreate]


class StudyResultCreate(BaseModel):
    author: str
    text: str


class StudyResultOut(BaseModel):
    id: str
    item_id: str
    created_at: datetime
    author: str
    text: str


class StudyOrderItemOut(BaseModel):
    id: str
    study_type: str
    reason: str | None
    results: list[StudyResultOut]


class StudyOrderOut(BaseModel):
    id: str
    patient_id: str
    created_at: datetime
    author: str
    items: list[StudyOrderItemOut]


def _require_patient(patient_id: str, patients: PatientRepository) -> None:
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")


def _require_order(patient_id: str, order_id: str, orders: StudyOrderRepository) -> dict:
    order = orders.get(order_id)
    if order is None or order["patient_id"] != patient_id:
        raise HTTPException(404, "study order not found")
    return order


def _require_item(order: dict, item_id: str) -> None:
    if not any(item["id"] == item_id for item in order["items"]):
        raise HTTPException(404, "study order item not found")


@router.post("", status_code=201, response_model=StudyOrderOut)
def create_study_order(
    patient_id: str,
    data: StudyOrderCreate,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    try:
        return orders.create(
            patient_id, data.author, [item.model_dump() for item in data.items],
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("", response_model=list[StudyOrderOut])
def list_study_orders(
    patient_id: str,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return orders.list_by_patient(patient_id)


@router.get("/{order_id}", response_model=StudyOrderOut)
def get_study_order(
    patient_id: str,
    order_id: str,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return _require_order(patient_id, order_id, orders)


@router.delete("/{order_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_study_order(
    patient_id: str,
    order_id: str,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
):
    try:
        orders.delete(order_id)
    except KeyError:
        raise HTTPException(404, "study order not found")
    return Response(status_code=204)


@router.post("/{order_id}/items/{item_id}/results", status_code=201, response_model=StudyResultOut)
def add_study_result(
    patient_id: str,
    order_id: str,
    item_id: str,
    data: StudyResultCreate,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    order = _require_order(patient_id, order_id, orders)
    _require_item(order, item_id)
    return orders.add_result(item_id, data.author, data.text)


@router.delete(
    "/{order_id}/items/{item_id}/results/{result_id}",
    status_code=204, dependencies=[Depends(require_admin)],
)
def delete_study_result(
    patient_id: str,
    order_id: str,
    item_id: str,
    result_id: str,
    orders: StudyOrderRepository = Depends(get_study_order_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    order = _require_order(patient_id, order_id, orders)
    _require_item(order, item_id)
    if not any(result["id"] == result_id for item in order["items"] for result in item["results"]):
        raise HTTPException(404, "study result not found")
    orders.delete_result(result_id)
    return Response(status_code=204)
