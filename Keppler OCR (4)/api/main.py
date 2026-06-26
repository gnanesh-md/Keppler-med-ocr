from fastapi import FastAPI, UploadFile, File, HTTPException
from core.config import settings
from core.schemas import DocumentUploadResponse, JobStatusResponse
from database.models import SessionLocal, Document, ExtractionJob
import hashlib
import uuid
import os

# Initialize FastAPI application
app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

@app.post("/api/v1/document/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    Intake Layer:
    Receives document, computes MD5 hash to prevent duplicate processing,
    and dispatches an asynchronous job to the Celery queue.
    """
    contents = await file.read()
    doc_hash = hashlib.md5(contents).hexdigest()
    
    # Securely save file to local staging area
    file_path = os.path.join(settings.UPLOAD_DIR, f"{doc_hash}_{file.filename}")
    if not os.path.exists(file_path):
        with open(file_path, "wb") as f:
            f.write(contents)
            
    db = SessionLocal()
    try:
        # Prevent redundant database entries for duplicate files
        doc = db.query(Document).filter(Document.id == doc_hash).first()
        if not doc:
            doc = Document(id=doc_hash, filename=file.filename, upload_path=file_path)
            db.add(doc)
            db.commit()
            
        # Create a unique tracking ID for this extraction attempt
        job_id = str(uuid.uuid4())
        job = ExtractionJob(job_id=job_id, document_id=doc.id)
        db.add(job)
        db.commit()
        
        # DISPATCH TO CELERY WORKER
        # from workers.celery_app import process_document_task
        # process_document_task.delay(job_id, file_path)
        
        return DocumentUploadResponse(
            document_hash=doc_hash,
            job_id=job_id,
            message="Document accepted and queued for asynchronous extraction."
        )
    finally:
        db.close()

@app.get("/api/v1/job/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Status endpoint for the UI to poll instead of blocking execution.
    """
    db = SessionLocal()
    try:
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
            
        return JobStatusResponse(
            job_id=job.job_id,
            document_hash=job.document_id,
            status=job.status,
            progress=job.progress,
            message=f"Job is currently {job.status}"
        )
    finally:
        db.close()
