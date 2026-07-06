import hashlib
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from core.config import settings
from core.security import CurrentUser, get_current_user
from database.db_utils import archive_document, get_document_full
from database.models import Document, ExtractionJob, SessionLocal
from modules.pdf_summarizer import generate_summary_docx, generate_summary_pdf, run_summary_pipeline

router = APIRouter(prefix="/api/v1/summarizer", tags=["summarizer"])


@router.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    contents = await file.read()
    doc_hash = hashlib.md5(contents).hexdigest()
    file_path = os.path.join(settings.UPLOAD_DIR, f"{doc_hash}_{file.filename}")
    if not os.path.exists(file_path):
        with open(file_path, "wb") as f:
            f.write(contents)

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_hash).first()
        if not doc:
            doc = Document(id=doc_hash, filename=file.filename, upload_path=file_path)
            db.add(doc)
            db.commit()

        job_id = str(uuid.uuid4())
        job = ExtractionJob(
            job_id=job_id,
            document_id=doc.id,
            user_id=current_user.user_id,
            job_type="summarizer",
            status="PENDING",
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    background_tasks.add_task(_run_summary_job, job_id, file_path, file.filename, current_user.user_id)

    return {
        "document_hash": doc_hash,
        "job_id": job_id,
        "message": "Document accepted and queued for summarization.",
    }


def _run_summary_job(job_id: str, file_path: str, filename: str, user_id: int):
    db = SessionLocal()
    try:
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        job.status = "PROCESSING"
        db.commit()

        def progress_cb(pct: float):
            db2 = SessionLocal()
            try:
                j = db2.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
                j.progress = round(pct * 100, 1)
                db2.commit()
            finally:
                db2.close()

        with open(file_path, "rb") as f:
            pdf_bytes = f.read()

        result = run_summary_pipeline(pdf_bytes, filename=filename, progress_cb=progress_cb)

        name, ip_no, doctor, nurse = result["patient_meta"]
        vault_id = archive_document(
            user_id=user_id,
            filename=filename,
            category="PDF Summary",
            markdown=result["summary_md"],
            confidence=99.0,
            metadata={
                "page_texts": {str(k): v for k, v in result["page_texts"].items()},
                "patient_meta": {"name": name, "ip_no": ip_no, "doctor": doctor, "nurse": nurse},
            },
        )

        job.result_doc_id = vault_id
        job.status = "COMPLETED"
        job.progress = 100.0
        job.completed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if job:
            job.status = "FAILED"
            job.error_message = str(e)
            db.commit()
    finally:
        db.close()


def _get_owned_job(db, job_id: str, user_id: int) -> ExtractionJob:
    job = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.job_id == job_id, ExtractionJob.user_id == user_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/job/{job_id}")
async def job_status(job_id: str, current_user: CurrentUser = Depends(get_current_user)):
    db = SessionLocal()
    try:
        job = _get_owned_job(db, job_id, current_user.user_id)
        return {
            "job_id": job.job_id,
            "document_hash": job.document_id,
            "status": job.status,
            "progress": job.progress,
            "error_message": job.error_message,
        }
    finally:
        db.close()


@router.get("/job/{job_id}/result")
async def job_result(job_id: str, current_user: CurrentUser = Depends(get_current_user)):
    db = SessionLocal()
    try:
        job = _get_owned_job(db, job_id, current_user.user_id)
        if job.status != "COMPLETED":
            raise HTTPException(status_code=409, detail=f"Job is {job.status}, not completed yet.")
        result_doc_id = job.result_doc_id
    finally:
        db.close()

    doc = get_document_full(result_doc_id, current_user.user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Result document not found.")

    return {
        "filename": doc["filename"],
        "summary_md": doc["markdown"],
        "page_texts": doc["metadata"].get("page_texts", {}),
        "patient_meta": doc["metadata"].get("patient_meta", {}),
    }


@router.get("/job/{job_id}/export")
async def export(
    job_id: str, format: str = "md", current_user: CurrentUser = Depends(get_current_user)
):
    db = SessionLocal()
    try:
        job = _get_owned_job(db, job_id, current_user.user_id)
        if job.status != "COMPLETED":
            raise HTTPException(status_code=409, detail=f"Job is {job.status}, not completed yet.")
        result_doc_id = job.result_doc_id
    finally:
        db.close()

    doc = get_document_full(result_doc_id, current_user.user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Result document not found.")

    summary_md = doc["markdown"]
    meta = doc["metadata"].get("patient_meta", {})
    name = meta.get("name", "Patient")
    ip_no = meta.get("ip_no", "—")
    doctor = meta.get("doctor", "—")
    nurse = meta.get("nurse", "—")

    if format == "md":
        return Response(content=summary_md, media_type="text/markdown")
    if format == "pdf":
        data = generate_summary_pdf(summary_md, name, ip_no, doctor, nurse)
        if isinstance(data, str):
            raise HTTPException(status_code=500, detail=data)
        return Response(content=data, media_type="application/pdf")
    if format == "docx":
        data = generate_summary_docx(summary_md, name, ip_no, doctor, nurse)
        if isinstance(data, str):
            raise HTTPException(status_code=500, detail=data)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    raise HTTPException(status_code=400, detail="Unsupported format. Use md|pdf|docx.")
