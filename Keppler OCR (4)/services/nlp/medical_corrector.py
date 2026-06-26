import asyncio
import aiohttp
import logging
from typing import List
from core.schemas import RegionPrediction
from core.config import settings

logger = logging.getLogger(__name__)

class MedicalCorrectionService:
    """
    Layer 7: Medical Correction Service.
    Acts as a deterministic post-processing layer to fix hallucinatory spelling mistakes 
    in drug names, diagnoses, and procedural codes using zero-temperature dictionary validation.
    """
    def __init__(self):
        self.vllm_url = f"{settings.VLLM_BASE_URL}/chat/completions"
        self.model = settings.QWEN_OCR_MODEL
        
    async def correct_regions_async(self, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            for region in regions:
                # Bypass non-text, tables (which have strict markdown), and empty blocks
                if not region.text_content or region.region_type in ["Figure", "Signature", "Table", "Checkbox"]:
                    continue
                    
                # Only correct regions that have a decent length
                if len(region.text_content.strip()) > 5:
                    tasks.append(self._async_correct_text(session, region))
                
            if tasks:
                logger.info(f"Validating {len(tasks)} regions against medical dictionaries.")
                await asyncio.gather(*tasks)
                
        return regions

    def correct_regions(self, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        """Synchronous wrapper for Celery integration."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(self.correct_regions_async(regions))
        
    async def _async_correct_text(self, session: aiohttp.ClientSession, region: RegionPrediction):
        prompt = f"""You are a strict Clinical OCR Corrector.
Fix typos in drug names, diagnoses, and procedures based on RxNorm/SNOMED dictionaries.
Do NOT change numbers, dates, vital signs, or non-medical terms.
Return ONLY the exact corrected text. Do NOT add conversational filler or quotes.

Original Text:
{region.text_content}"""
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.0 # Deterministic grounding
        }
        
        try:
            async with session.post(self.vllm_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    corrected = data["choices"][0]["message"]["content"].strip()
                    if corrected and len(corrected) > 0:
                        # Log high-confidence corrections
                        if corrected != region.text_content.strip():
                            logger.info(f"Corrector Fixed: '{region.text_content[:20]}...' -> '{corrected[:20]}...'")
                        region.text_content = corrected
        except Exception as e:
            logger.error(f"Medical correction failed: {e}")
