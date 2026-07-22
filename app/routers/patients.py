from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..auth import require_admin
from ..dependencies import get_patient_repository
from ..services.patients import PatientHasClinicalNotes, PatientRepository

router = APIRouter(prefix="/patients", tags=["patients"])


class PatientCreate(BaseModel):
    id: str
    name: str
    phone: str | None = None
    email: str | None = None
    active: bool = True
    dni: str | None = None
    birth_date: date | None = None


class PatientUpdate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    active: bool = True
    dni: str | None = None
    birth_date: date | None = None


class PatientOut(BaseModel):
    id: str
    name: str
    phone: str | None
    email: str | None
    active: bool
    dni: str | None
    birth_date: date | None


@router.post("", status_code=201, response_model=PatientOut)
def create_patient(
    data: PatientCreate, patients: PatientRepository = Depends(get_patient_repository),
):
    try:
        return patients.create(
            data.id, data.name, data.phone, data.email, data.active, data.dni, data.birth_date,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except IntegrityError:
        raise HTTPException(409, "patient already exists")


@router.get("", response_model=list[PatientOut])
def list_patients(patients: PatientRepository = Depends(get_patient_repository)):
    return patients.list()


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, patients: PatientRepository = Depends(get_patient_repository)):
    patient = patients.get(patient_id)
    if patient is None:
        raise HTTPException(404, "patient not found")
    return patient


@router.put("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: str,
    data: PatientUpdate,
    patients: PatientRepository = Depends(get_patient_repository),
):
    try:
        return patients.update(
            patient_id, data.name, data.phone, data.email, data.active, data.dni, data.birth_date,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, "patient not found")


@router.delete("/{patient_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_patient(patient_id: str, patients: PatientRepository = Depends(get_patient_repository)):
    try:
        patients.delete(patient_id)
    except KeyError:
        raise HTTPException(404, "patient not found")
    except PatientHasClinicalNotes:
        raise HTTPException(409, "patient has clinical notes")
    return Response(status_code=204)
