from celery import Celery
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# Initialize Celery app
celery_app = Celery(
    "keppler_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Worker optimizations for GPU blocking
    worker_prefetch_multiplier=1,
    task_acks_late=True
)

@celery_app.task(bind=True, name="extract_document")
def process_document_task(self, job_id: str, file_path: str):
    """
    Background worker that executes the heavy 12-layer Map-Reduce extraction pipeline.
    Runs asynchronously to prevent Streamlit UI blocking.
    """
    from database.models import SessionLocal, ExtractionJob
    import time
    
    db = SessionLocal()
    try:
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in database.")
            return "Job not found"
            
        # Update status to Processing
        job.status = "PROCESSING"
        job.progress = 5.0
        db.commit()
        logger.info(f"Started processing job {job_id} for file {file_path}")
        
        # ---------------------------------------------------------------------
        # PIPELINE EXECUTION (Sprint 2: Vision Pipeline Integration)
        # ---------------------------------------------------------------------
        
        # Layer 2: Enhancement
        from services.vision.enhancer import ImageEnhancementService
        import cv2
        from PIL import Image
        
        logger.info(f"Enhancing image {file_path}")
        enhanced_img_cv = ImageEnhancementService.optimize_for_ocr(file_path)
        enhanced_img_pil = Image.fromarray(cv2.cvtColor(enhanced_img_cv, cv2.COLOR_BGR2RGB))
        
        job.progress = 10.0
        db.commit()
        
        # Layer 3: Layout Detection
        from services.vision.layout import LayoutDetectionService
        layout_service = LayoutDetectionService()
        logger.info("Running DocLayout-YOLO...")
        regions = layout_service.detect_regions(enhanced_img_pil, page_number=1)
        
        job.progress = 30.0
        db.commit()
        
        # Layer 4: Reading Order Reconstruction
        from services.ocr.reading_order import ReadingOrderEngine
        ro_engine = ReadingOrderEngine()
        w, h = enhanced_img_pil.size
        logger.info("Reconstructing spatial reading order...")
        ordered_regions = ro_engine.reconstruct(regions, w, h)
        
        job.progress = 50.0
        db.commit()
        
        # ---------------------------------------------------------------------
        # PIPELINE EXECUTION (Sprint 3: Extraction Pipeline Integration)
        # ---------------------------------------------------------------------
        
        # Layer 5 & 6: Async Region OCR & Table Extraction
        from services.ocr.engine import RegionOCREngine
        from services.ocr.table_extractor import TableExtractionService
        
        ocr_engine = RegionOCREngine()
        logger.info("Executing high-throughput asynchronous Region OCR...")
        extracted_regions = ocr_engine.process_regions(enhanced_img_pil, ordered_regions)
        
        logger.info("Executing structural Table extraction...")
        table_extractor = TableExtractionService(ocr_engine)
        extracted_regions = table_extractor.process_tables(enhanced_img_pil, extracted_regions)
        
        job.progress = 70.0
        db.commit()
        
        # Layer 8: Confidence Scoring
        from services.telemetry.confidence import ConfidenceScoringService
        logger.info("Fusing YOLO layout and OCR semantic confidence scores...")
        final_regions = ConfidenceScoringService.calculate_confidence(extracted_regions)
        
        job.progress = 80.0
        db.commit()
        
        # Layer 7: Medical Corrector
        from services.nlp.medical_corrector import MedicalCorrectionService
        logger.info("Executing zero-temperature Medical Corrector...")
        corrector = MedicalCorrectionService()
        final_regions = corrector.correct_regions(final_regions)
        
        job.progress = 85.0
        db.commit()
        
        # Layer 8: Entity Classification & Context-Aware Routing
        from services.nlp.entity_classifier import EntityClassificationService
        from services.nlp.resolver_router import ResolverRouter
        
        logger.info("Executing zero-shot Entity Classification (vLLM)...")
        classifier = EntityClassificationService()
        final_regions = classifier.classify_regions(final_regions)
        
        logger.info("Routing entities to designated datasets...")
        final_regions = ResolverRouter.route_and_resolve(final_regions)
        
        job.progress = 90.0
        db.commit()
        
        # Layer 9-11: Map-Reduce Summarization & Entity Extraction
        logger.info("Initiating Map-Reduce Summarization across document...")
        full_document_text = "\n\n".join([r.text_content for r in final_regions if r.text_content])
        
        from services.summarizer.chunker import TextChunker
        from services.summarizer.hierarchical import HierarchicalSummarizer
        from services.summarizer.aggregator import MasterAggregator
        
        chunker = TextChunker(file_path, full_document_text)
        chunks = chunker.get_chunks()
        
        summarizer = HierarchicalSummarizer()
        master_data = summarizer.process_chunks(chunker)
        
        aggregator = MasterAggregator()
        final_markdown_report = aggregator.build_master_report(master_data)
        
        # Save report to a local storage bucket equivalent
        report_path = file_path + "_report.md"
        with open(report_path, "w") as f:
            f.write(final_markdown_report)
            
        # Step 6: Structured OCR Output Export
        import json
        json_path = file_path + "_structured.json"
        with open(json_path, "w") as f:
            json.dump([r.model_dump() for r in final_regions], f, indent=4)
            
        # ---------------------------------------------------------------------
        
        job.status = "COMPLETED"
        job.progress = 100.0
        db.commit()
        logger.info(f"Successfully completed job {job_id}")
        
        return {"status": "success", "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        job = db.query(ExtractionJob).filter(ExtractionJob.job_id == job_id).first()
        if job:
            job.status = "FAILED"
            db.commit()
        raise e
    finally:
        db.close()
