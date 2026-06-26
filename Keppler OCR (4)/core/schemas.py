from pydantic import BaseModel
from typing import List, Optional

class RegionPrediction(BaseModel):
    """Data contract for an extracted region from the document."""
    region_id: str
    region_type: str        # e.g., "paragraph", "table", "header"
    bbox: List[int]         # [x1, y1, x2, y2]
    page_number: int
    text_content: Optional[str] = None
    confidence_score: float = 0.0
    reading_order: int = 0
    
    # Resolver Audit Fields
    entity_classification: Optional[str] = None
    resolved_name: Optional[str] = None
    dataset_source: Optional[str] = None
    resolution_confidence: float = 0.0

class DocumentUploadResponse(BaseModel):
    """Response returned when a file is uploaded."""
    document_hash: str
    job_id: str
    message: str

class JobStatusResponse(BaseModel):
    """Response returned when polling a job's status."""
    job_id: str
    document_hash: str
    status: str
    progress: float
    message: str
    
class ExtractionResult(BaseModel):
    """Final output schema returned after a job completes."""
    job_id: str
    document_hash: str
    regions: List[RegionPrediction]
