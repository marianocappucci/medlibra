from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import require_admin
from ..dependencies import get_patient_repository, get_prescription_repository
from ..services.patients import PatientRepository
from ..services.prescriptions import PrescriptionRepository

router = APIRouter(prefix="/patients/{patient_id}/prescriptions", tags=["prescriptions"])


class PrescriptionItemCreate(BaseModel):
    medication: str
    dosage: str
    instructions: str | None = None


class PrescriptionCreate(BaseModel):
    author: str
    items: list[PrescriptionItemCreate]


class PrescriptionItemOut(BaseModel):
    id: str
    medication: str
    dosage: str
    instructions: str | None


class PrescriptionOut(BaseModel):
    id: str
    patient_id: str
    created_at: datetime
    author: str
    items: list[PrescriptionItemOut]


def _require_patient(patient_id: str, patients: PatientRepository) -> None:
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")


@router.post("", status_code=201, response_model=PrescriptionOut)
def create_prescription(
    patient_id: str,
    data: PrescriptionCreate,
    prescriptions: PrescriptionRepository = Depends(get_prescription_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    try:
        return prescriptions.create(
            patient_id, data.author, [item.model_dump() for item in data.items],
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("", response_model=list[PrescriptionOut])
def list_prescriptions(
    patient_id: str,
    prescriptions: PrescriptionRepository = Depends(get_prescription_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return prescriptions.list_by_patient(patient_id)


@router.get("/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    patient_id: str,
    prescription_id: str,
    prescriptions: PrescriptionRepository = Depends(get_prescription_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    prescription = prescriptions.get(prescription_id)
    if prescription is None or prescription["patient_id"] != patient_id:
        raise HTTPException(404, "prescription not found")
    return prescription


@router.delete("/{prescription_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_prescription(
    patient_id: str,
    prescription_id: str,
    prescriptions: PrescriptionRepository = Depends(get_prescription_repository),
):
    try:
        prescriptions.delete(prescription_id)
    except KeyError:
        raise HTTPException(404, "prescription not found")
    return Response(status_code=204)
