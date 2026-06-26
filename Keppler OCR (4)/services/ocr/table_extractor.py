import logging
import asyncio
import aiohttp
import base64
import io
from typing import List
from PIL import Image
from core.schemas import RegionPrediction
from services.ocr.engine import RegionOCREngine

logger = logging.getLogger(__name__)

class TableExtractionService:
    """
    Layer 6: Table Extraction Service.
    Intercepts regions tagged as 'Table' and enforces structural markdown extraction 
    to prevent row/column flattening.
    """
    def __init__(self, ocr_engine: RegionOCREngine):
        self.ocr_engine = ocr_engine
        
    async def process_tables_async(self, image: Image.Image, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        table_regions = [r for r in regions if r.region_type == "Table"]
        if not table_regions:
            return regions
            
        logger.info(f"Structurally extracting {len(table_regions)} tables.")
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for region in table_regions:
                crop_box = (region.bbox[0], region.bbox[1], region.bbox[2], region.bbox[3])
                
                if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                    region.text_content = "[Invalid Table Dimensions]"
                    continue
                    
                cropped_img = image.crop(crop_box)
                tasks.append(self._async_table_ocr(session, cropped_img, region))
                
            await asyncio.gather(*tasks)
            
        return regions

    def process_tables(self, image: Image.Image, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        """Synchronous wrapper for Celery workflow."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(self.process_tables_async(image, regions))
            
    async def _async_table_ocr(self, session: aiohttp.ClientSession, img: Image.Image, region: RegionPrediction):
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        # Strict Markdown structural prompt
        prompt = (
            "You are a clinical data extraction engine. "
            "Extract this table perfectly into Markdown format. "
            "Maintain all rows and columns exactly as they appear. "
            "Do NOT add conversational filler or external text."
        )
        
        payload = {
            "model": self.ocr_engine.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.0
        }
        
        try:
            async with session.post(self.ocr_engine.vllm_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    region.text_content = data["choices"][0]["message"]["content"].strip()
                else:
                    logger.error(f"vLLM API Error during Table extraction: {response.status}")
                    region.text_content = "[Table Extraction Failed]"
        except Exception as e:
            logger.error(f"vLLM connection failed during Table extraction: {e}")
            region.text_content = "[Table Extraction Failed]"
