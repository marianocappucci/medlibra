import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import require_admin
from ..dependencies import get_clinical_document_repository, get_patient_repository
from ..services.clinical_documents import ClinicalDocumentRepository
from ..services.patients import PatientRepository
from ._instantes import InstanteUTC

router = APIRouter(prefix="/patients/{patient_id}/documents", tags=["clinical-documents"])

# Formatos esperados para informes/estudios escaneados. Nombre de archivo
# en disco normalizado (UUID), esta lista solo gatea la extension del
# nombre original recibido.
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


class ClinicalDocumentOut(BaseModel):
    id: str
    patient_id: str
    created_at: InstanteUTC
    author: str
    title: str
    description: str | None
    original_filename: str
    content_type: str | None
    size_bytes: int


def _require_patient(patient_id: str, patients: PatientRepository) -> None:
    if patients.get(patient_id) is None:
        raise HTTPException(404, "patient not found")


def _require_document(patient_id: str, document_id: str, documents: ClinicalDocumentRepository) -> dict:
    document = documents.get(document_id)
    if document is None or document["patient_id"] != patient_id:
        raise HTTPException(404, "document not found")
    return document


@router.post("", status_code=201, response_model=ClinicalDocumentOut)
async def upload_clinical_document(
    patient_id: str,
    author: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    documents: ClinicalDocumentRepository = Depends(get_clinical_document_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, f"unsupported file type: {ext or '(none)'}")
    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(422, "file too large (max 20MB)")
    return documents.create(
        patient_id, author, title, description, file.filename, file.content_type, content,
    )


@router.get("", response_model=list[ClinicalDocumentOut])
def list_clinical_documents(
    patient_id: str,
    documents: ClinicalDocumentRepository = Depends(get_clinical_document_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return documents.list_by_patient(patient_id)


@router.get("/{document_id}", response_model=ClinicalDocumentOut)
def get_clinical_document(
    patient_id: str,
    document_id: str,
    documents: ClinicalDocumentRepository = Depends(get_clinical_document_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    return _require_document(patient_id, document_id, documents)


@router.get("/{document_id}/file")
def download_clinical_document(
    patient_id: str,
    document_id: str,
    documents: ClinicalDocumentRepository = Depends(get_clinical_document_repository),
    patients: PatientRepository = Depends(get_patient_repository),
):
    _require_patient(patient_id, patients)
    document = _require_document(patient_id, document_id, documents)
    path = documents.get_file_path(document_id)
    if path is None or not os.path.exists(path):
        raise HTTPException(404, "file not found on disk")
    return FileResponse(
        path, media_type=document["content_type"] or "application/octet-stream",
        filename=document["original_filename"],
    )


@router.delete("/{document_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_clinical_document(
    patient_id: str,
    document_id: str,
    documents: ClinicalDocumentRepository = Depends(get_clinical_document_repository),
):
    try:
        documents.delete(document_id)
    except KeyError:
        raise HTTPException(404, "document not found")
    return Response(status_code=204)
