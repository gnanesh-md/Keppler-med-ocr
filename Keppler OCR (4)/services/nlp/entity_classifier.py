import asyncio
import aiohttp
import logging
from typing import List
from core.schemas import RegionPrediction
from core.config import settings

logger = logging.getLogger(__name__)

class EntityClassificationService:
    """
    Classifies OCR text into strict Entity Types to prevent cross-dataset resolution hallucination.
    Acts as a firewall before the Resolver Router.
    """
    def __init__(self):
        self.vllm_url = f"{settings.VLLM_BASE_URL}/chat/completions"
        self.model = settings.QWEN_OCR_MODEL
        
    async def classify_regions_async(self, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        async with aiohttp.ClientSession() as session:
            tasks = []
            for region in regions:
                if not region.text_content or region.region_type in ["Figure", "Signature", "Table", "Checkbox"]:
                    region.entity_classification = "None"
                    continue
                    
                # Skip overly long paragraphs (likely not a single entity)
                if len(region.text_content.split()) > 15:
                    region.entity_classification = "Paragraph"
                    continue
                    
                tasks.append(self._async_classify(session, region))
                
            if tasks:
                logger.info(f"Classifying {len(tasks)} entities via vLLM...")
                await asyncio.gather(*tasks)
                
        return regions

    def classify_regions(self, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        """Synchronous wrapper for Celery integration."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.classify_regions_async(regions))
        
    async def _async_classify(self, session: aiohttp.ClientSession, region: RegionPrediction):
        prompt = f"""Classify the following clinical text block into EXACTLY ONE of the following types:
- Human Name
- Doctor Name
- Hospital Name
- Medication
- Laboratory Test
- Service Name
- Item Name
- Frequency Code
- Procedure
- Diagnosis
- None

Return ONLY the exact type string. No quotes, no explanation.

Text:
{region.text_content}"""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16,
            "temperature": 0.0 # Strict classification
        }
        
        try:
            async with session.post(self.vllm_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    classification = data["choices"][0]["message"]["content"].strip()
                    
                    valid_types = [
                        "Human Name", "Doctor Name", "Hospital Name", "Medication",
                        "Laboratory Test", "Service Name", "Item Name", "Frequency Code",
                        "Procedure", "Diagnosis", "None"
                    ]
                    
                    if classification in valid_types:
                        region.entity_classification = classification
                    else:
                        region.entity_classification = "None"
                else:
                    region.entity_classification = "None"
        except Exception as e:
            logger.error(f"Entity Classification failed: {e}")
            region.entity_classification = "None"
