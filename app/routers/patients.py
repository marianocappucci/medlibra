from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..auth import require_admin
from ..dependencies import get_patient_repository
from ..services import pacientes_nodo
from ..services.patients import PatientHasClinicalNotes, PatientRepository

router = APIRouter(prefix="/patients", tags=["patients"])


def _modificable_en_el_nodo(patient_id: str) -> None:
    """En un nodo sin conexion (ADR-045) un paciente no se edita ni se borra: el del central es del espejo y el provisorio ya
    subio con sus datos. 409. Fuera de un nodo no hace nada."""
    pacientes_nodo.exigir_paciente_modificable(patient_id)


class PatientCreate(BaseModel):
    # Opcional: sin `id` el backend genera el próximo número (`p-001`, `p-002`...). Con
    # `id` se respeta tal cual, como siempre. Un `id` vacío no cuenta como ausente: es
    # un dato inválido y da 422.
    id: str | None = None
    name: str
    phone: str | None = None
    email: str | None = None
    active: bool = True
    dni: str | None = None
    birth_date: date | None = None
    cuit: str | None = None
    condicion_iva: str | None = None


class PatientUpdate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    active: bool = True
    dni: str | None = None
    birth_date: date | None = None
    cuit: str | None = None
    condicion_iva: str | None = None


class PatientOut(BaseModel):
    id: str
    name: str
    phone: str | None
    email: str | None
    active: bool
    dni: str | None
    birth_date: date | None
    cuit: str | None
    condicion_iva: str | None


@router.post("", status_code=201, response_model=PatientOut)
def create_patient(
    data: PatientCreate, patients: PatientRepository = Depends(get_patient_repository),
):
    try:
        return patients.create(
            data.id, data.name, data.phone, data.email, data.active, data.dni, data.birth_date,
            data.cuit, data.condicion_iva,
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


@router.put("/{patient_id}", response_model=PatientOut, dependencies=[Depends(_modificable_en_el_nodo)])
def update_patient(
    patient_id: str,
    data: PatientUpdate,
    patients: PatientRepository = Depends(get_patient_repository),
):
    try:
        return patients.update(
            patient_id, data.name, data.phone, data.email, data.active, data.dni, data.birth_date,
            data.cuit, data.condicion_iva,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except KeyError:
        raise HTTPException(404, "patient not found")


@router.delete(
    "/{patient_id}", status_code=204, dependencies=[Depends(require_admin), Depends(_modificable_en_el_nodo)],
)
def delete_patient(patient_id: str, patients: PatientRepository = Depends(get_patient_repository)):
    try:
        patients.delete(patient_id)
    except KeyError:
        raise HTTPException(404, "patient not found")
    except PatientHasClinicalNotes:
        raise HTTPException(409, "patient has clinical notes")
    return Response(status_code=204)
