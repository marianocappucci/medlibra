from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import require_admin
from ..dependencies import get_consent_repository, get_patient_repository
from ..services.consents import ConsentRepository
from ..services.patients import PatientRepository
from ._instantes import InstanteUTC

router = APIRouter(prefix="/patients/{patient_id}/consents", tags=["consents"])


class ConsentCreate(BaseModel):
    author: str
    procedure: str
    granted_by: str
    text: str


class ConsentOut(BaseModel):
    id: str
    patient_id: str
    created_at: InstanteUTC
    author: str
    procedure: str
    granted_by: str
    text: str


def _require_patient(patient_id: str, patients: PatientRepository) -> None:
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")


@router.post("", status_code=201, response_model=ConsentOut)
def create_consent(
    patient_id: str,
    data: ConsentCreate,
    consents: ConsentRepository = Depends(get_consent_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return consents.create(patient_id, data.author, data.procedure, data.granted_by, data.text)


@router.get("", response_model=list[ConsentOut])
def list_consents(
    patient_id: str,
    consents: ConsentRepository = Depends(get_consent_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return consents.list_by_patient(patient_id)


@router.get("/{consent_id}", response_model=ConsentOut)
def get_consent(
    patient_id: str,
    consent_id: str,
    consents: ConsentRepository = Depends(get_consent_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    consent = consents.get(consent_id)
    if consent is None or consent["patient_id"] != patient_id:
        raise HTTPException(404, "consent not found")
    return consent


@router.delete("/{consent_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_consent(
    patient_id: str,
    consent_id: str,
    consents: ConsentRepository = Depends(get_consent_repository),
):
    try:
        consents.delete(consent_id)
    except KeyError:
        raise HTTPException(404, "consent not found")
    return Response(status_code=204)
