import logging
from typing import List
from core.schemas import RegionPrediction

logger = logging.getLogger(__name__)

class ConfidenceScoringService:
    """
    Layer 8: Confidence Scoring Engine.
    Aggregates layout confidence (YOLO) with semantic confidence (OCR heuristic/logprobs)
    to provide a final actionable score.
    """
    
    @staticmethod
    def calculate_confidence(regions: List[RegionPrediction]) -> List[RegionPrediction]:
        logger.info(f"Calculating multi-modal confidence scores for {len(regions)} regions.")
        
        for r in regions:
            # Layout confidence from Layer 3 (YOLO)
            layout_conf = r.confidence_score
            
            # Semantic confidence heuristics (Layer 5/6)
            semantic_conf = 1.0
            
            if r.region_type in ["Figure", "Signature", "Checkbox"]:
                # Bypass text heuristics for non-text objects
                pass
            elif not r.text_content or len(r.text_content.strip()) == 0:
                semantic_conf = 0.0
            else:
                # Basic Gibberish Detection: 
                # If a paragraph consists mostly of symbols instead of alphanumeric chars,
                # the OCR engine likely hallucinated or read noise.
                text = r.text_content
                alphanumeric_count = sum(c.isalnum() for c in text)
                ratio = alphanumeric_count / len(text)
                
                # If less than 50% of the text is alphanumeric, penalize the score
                if ratio < 0.5:
                    semantic_conf = ratio * 1.5 # Scale it slightly
                    
            # Weighted Aggregation:
            # Semantic text accuracy is usually more critical than perfect bounding box precision
            final_conf = (layout_conf * 0.4) + (semantic_conf * 0.6)
            
            # Cap at 1.0
            r.confidence_score = min(1.0, round(final_conf, 3))
            
        return regions
