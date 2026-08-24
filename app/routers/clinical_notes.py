from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import require_admin
from ..dependencies import get_clinical_note_repository, get_patient_repository
from ..services.clinical_notes import ClinicalNoteRepository
from ..services.patients import PatientRepository
from ._instantes import InstanteUTC

router = APIRouter(prefix="/patients/{patient_id}/notes", tags=["clinical-notes"])


class NoteCreate(BaseModel):
    author: str
    text: str


class NoteOut(BaseModel):
    id: str
    patient_id: str
    created_at: InstanteUTC
    author: str
    text: str


def _require_patient(patient_id: str, patients: PatientRepository) -> None:
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")


@router.post("", status_code=201, response_model=NoteOut)
def create_note(
    patient_id: str,
    data: NoteCreate,
    notes: ClinicalNoteRepository = Depends(get_clinical_note_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return notes.create(patient_id, data.author, data.text)


@router.get("", response_model=list[NoteOut])
def list_notes(
    patient_id: str,
    notes: ClinicalNoteRepository = Depends(get_clinical_note_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return notes.list_by_patient(patient_id)


@router.get("/{note_id}", response_model=NoteOut)
def get_note(
    patient_id: str,
    note_id: str,
    notes: ClinicalNoteRepository = Depends(get_clinical_note_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    note = notes.get(note_id)
    if note is None or note["patient_id"] != patient_id:
        raise HTTPException(404, "note not found")
    return note


@router.delete("/{note_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_note(
    patient_id: str,
    note_id: str,
    notes: ClinicalNoteRepository = Depends(get_clinical_note_repository),
):
    try:
        notes.delete(note_id)
    except KeyError:
        raise HTTPException(404, "note not found")
    return Response(status_code=204)
