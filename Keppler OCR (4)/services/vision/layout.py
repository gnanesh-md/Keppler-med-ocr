import os
import uuid
import logging
from typing import List
from PIL import Image
from core.schemas import RegionPrediction

logger = logging.getLogger(__name__)

class LayoutDetectionService:
    """
    Layer 3: YOLO-based Document Layout Detection.
    Parses document structures (Paragraphs, Tables, Headers) and bounds them 
    for isolated region-based OCR execution.
    """
    _instance = None
    
    def __new__(cls):
        # Singleton pattern to prevent multiple heavy model loads in worker memory
        if cls._instance is None:
            cls._instance = super(LayoutDetectionService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
        
    def __init__(self):
        if self._initialized:
            return
        self.model = None
        self._load_model()
        self._initialized = True
        
    def _load_model(self):
        try:
            from ultralytics import YOLO
            from huggingface_hub import hf_hub_download
            
            model_path = os.path.join(os.path.dirname(__file__), "..", "..", "models", "doclayout.pt")
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            
            if not os.path.exists(model_path):
                logger.info("Downloading DocLayout-YOLO model weights...")
                downloaded_path = hf_hub_download(
                    repo_id="foduucom/document-layout-analysis-yolov8",
                    filename="best.pt",
                    local_dir=os.path.dirname(model_path)
                )
                os.rename(downloaded_path, model_path)
                
            self.model = YOLO(model_path)
            logger.info("DocLayout-YOLO model successfully loaded into memory.")
        except ImportError:
            logger.error("ultralytics or huggingface_hub is not installed.")
        except Exception as e:
            logger.error(f"Failed to load layout model: {e}")
            
    def detect_regions(self, image: Image.Image, page_number: int = 1) -> List[RegionPrediction]:
        w, h = image.size
        fallback_region = RegionPrediction(
            region_id=str(uuid.uuid4()),
            region_type="Paragraph",
            bbox=[0, 0, w, h],
            page_number=page_number,
            confidence_score=1.0
        )
        
        if self.model is None:
            return [fallback_region]
            
        try:
            results = self.model.predict(image, verbose=False, conf=0.3)
            regions = []
            
            if len(results) > 0 and len(results[0].boxes) > 0:
                for box in results[0].boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    class_name = self.model.names[cls_id] if hasattr(self.model, 'names') else str(cls_id)
                    
                    regions.append({
                        "id": str(uuid.uuid4()),
                        "type": self._map_class(class_name),
                        "box": [int(x1), int(y1), int(x2), int(y2)],
                        "conf": conf
                    })
                    
            if not regions:
                return [fallback_region]
                
            # Step 3: Overlap Resolution - Mathematically separate intersecting text blocks
            resolved = self._resolve_overlaps(regions)
            
            # Map to Pydantic contracts
            final_predictions = []
            for m in resolved:
                final_predictions.append(RegionPrediction(
                    region_id=m["id"],
                    region_type=m["type"],
                    bbox=m["box"],
                    page_number=page_number,
                    confidence_score=m["conf"]
                ))
            return final_predictions
            
        except Exception as e:
            logger.error(f"YOLO Layout detection failed: {e}")
            return [fallback_region]
            
    def _map_class(self, raw_class: str) -> str:
        raw = raw_class.lower()
        if "table" in raw: return "Table"
        if "title" in raw or "heading" in raw: return "Title"
        if "header" in raw: return "Header"
        if "footer" in raw: return "Footer"
        if "figure" in raw or "picture" in raw or "image" in raw: return "Figure"
        return "Paragraph"
        
    def _resolve_overlaps(self, regions: List[dict]) -> List[dict]:
        """
        Geometrically resolves bounding box overlaps.
        Instead of merging, it mathematically slices intersecting boundaries 
        to isolate adjacent text blocks (preventing name merging).
        """
        # Sort by confidence so higher confidence boxes get priority during slicing
        regions.sort(key=lambda r: r["conf"], reverse=True)
        
        resolved = []
        for r in regions:
            r_box = r["box"].copy()
            
            for m in resolved:
                m_box = m["box"]
                
                xA, yA = max(r_box[0], m_box[0]), max(r_box[1], m_box[1])
                xB, yB = min(r_box[2], m_box[2]), min(r_box[3], m_box[3])
                
                interArea = max(0, xB - xA) * max(0, yB - yA)
                
                if interArea > 0:
                    rArea = (r_box[2] - r_box[0]) * (r_box[3] - r_box[1])
                    if rArea > 0 and (interArea / float(rArea)) > 0.15:
                        # Slice the intersection out of the current (lower conf) box
                        if (xB - xA) < (yB - yA):
                            # Horizontal slice
                            if r_box[0] < m_box[0]: r_box[2] = max(r_box[0] + 1, m_box[0] - 2)
                            else: r_box[0] = min(r_box[2] - 1, m_box[2] + 2)
                        else:
                            # Vertical slice
                            if r_box[1] < m_box[1]: r_box[3] = max(r_box[1] + 1, m_box[1] - 2)
                            else: r_box[1] = min(r_box[3] - 1, m_box[3] + 2)
            
            if r_box[2] > r_box[0] and r_box[3] > r_box[1]:
                r["box"] = r_box
                resolved.append(r)
                
        return resolved
