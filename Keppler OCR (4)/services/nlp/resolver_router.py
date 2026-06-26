import logging
from typing import List
from core.schemas import RegionPrediction

try:
    from modules.unified_resolver import get_prediction, LOOKUP
    LEGACY_RESOLVER_AVAILABLE = True
except ImportError:
    LEGACY_RESOLVER_AVAILABLE = False

logger = logging.getLogger(__name__)

class ResolverRouter:
    """
    Context-aware routing layer.
    Receives classified entities and routes them strictly to their authorized datasets,
    bypassing datasets that would cause hallucinations (e.g., preventing Human Names from matching Item Master).
    """
    
    @staticmethod
    def route_and_resolve(regions: List[RegionPrediction]) -> List[RegionPrediction]:
        if not LEGACY_RESOLVER_AVAILABLE:
            logger.warning("Legacy Unified Resolver not available. Skipping resolution.")
            return regions
            
        logger.info(f"Executing Context-Aware Resolver Routing for {len(regions)} regions...")
        
        for region in regions:
            cls_type = region.entity_classification
            
            # Explicit Bypass Logic
            if cls_type in ["Human Name", "Doctor Name", "Hospital Name", "None", "Paragraph"]:
                region.resolved_name = None
                region.dataset_source = None
                region.resolution_confidence = 0.0
                continue
                
            text = region.text_content
            if not text:
                continue
                
            # Perform unified TF-IDF prediction
            labels, scores = get_prediction(text)
            
            if labels and scores[0] > 0.55:
                info = LOOKUP.get(labels[0], {})
                dataset_type = info.get("TYPE", "UNKNOWN")
                
                # Context-Aware Firewall Validation
                is_valid_match = False
                
                if cls_type in ["Medication", "Item Name"] and dataset_type == "ITEM":
                    is_valid_match = True
                elif cls_type in ["Service Name", "Procedure", "Laboratory Test"] and dataset_type == "SERVICE":
                    is_valid_match = True
                elif cls_type == "Frequency Code" and dataset_type == "FREQUENCY":
                    is_valid_match = True
                elif cls_type == "Diagnosis":
                    # Unified resolver currently lacks ICD-10
                    is_valid_match = False
                    
                if is_valid_match:
                    region.resolved_name = info.get("NAME", info.get("MEANING", labels[0]))
                    region.dataset_source = dataset_type
                    region.resolution_confidence = round(float(scores[0]), 3)
                    logger.info(f"Resolved [{cls_type}]: '{text}' -> '{region.resolved_name}' ({dataset_type})")
                else:
                    logger.debug(f"Blocked Cross-Dataset Match: {cls_type} '{text}' matched against {dataset_type}")
                    region.resolved_name = None
                    region.dataset_source = None
                    region.resolution_confidence = 0.0
                    
        return regions
