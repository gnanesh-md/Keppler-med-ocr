from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from core.config import settings
from datetime import datetime

Base = declarative_base()

class Document(Base):
    """Stores unique document metadata and physical storage locations."""
    __tablename__ = "documents"
    
    # We use the document's MD5 hash as the primary key to enable instant deduplication
    id = Column(String, primary_key=True, index=True) 
    filename = Column(String, index=True)
    upload_path = Column(String)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    jobs = relationship("ExtractionJob", back_populates="document")

class ExtractionJob(Base):
    """Tracks asynchronous Celery extraction jobs."""
    __tablename__ = "extraction_jobs"
    
    job_id = Column(String, primary_key=True, index=True) # Celery Task ID
    document_id = Column(String, ForeignKey("documents.id"))
    user_id = Column(Integer, index=True, nullable=True)

    # Which pipeline this job runs: "ocr" or "summarizer"
    job_type = Column(String, default="ocr")

    # Status can be PENDING, PROCESSING, COMPLETED, FAILED
    status = Column(String, default="PENDING")
    progress = Column(Float, default=0.0)
    error_message = Column(String, nullable=True)

    # Links to the universal_docs row (in the separate ai_portal.db) holding the
    # actual markdown/entities once archive_document() runs on completion.
    result_doc_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    document = relationship("Document", back_populates="jobs")

# Initialize database connection
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create tables for local testing
Base.metadata.create_all(bind=engine)
