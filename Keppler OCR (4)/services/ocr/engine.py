import base64
import io
import asyncio
import aiohttp
import logging
from typing import List
from PIL import Image
from core.schemas import RegionPrediction
from core.config import settings

logger = logging.getLogger(__name__)

class RegionOCREngine:
    """
    Layer 5: Region-Based OCR Engine.
    Executes high-throughput asynchronous OCR. Instead of dumping massive 8K images into the LLM,
    it crops individual layout regions and blasts them to vLLM concurrently.
    """
    def __init__(self):
        self.vllm_url = f"{settings.VLLM_BASE_URL}/chat/completions"
        self.model = settings.QWEN_OCR_MODEL
        
    async def process_regions_async(self, image: Image.Image, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        if not regions:
            return []
            
        async with aiohttp.ClientSession() as session:
            tasks = []
            skipped_regions = []
            
            for region in regions:
                # Tables are strictly delegated to Layer 6
                if region.region_type == "Table":
                    skipped_regions.append(region)
                    continue
                    
                # Figures/Signatures bypass expensive inference
                if region.region_type in ["Figure", "Signature", "Checkbox"]:
                    region.text_content = f"[{region.region_type}]"
                    skipped_regions.append(region)
                    continue
                    
                # Crop isolated bounding box
                crop_box = (region.bbox[0], region.bbox[1], region.bbox[2], region.bbox[3])
                
                # Prevent negative or 0-width crops
                if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                    region.text_content = ""
                    skipped_regions.append(region)
                    continue
                    
                cropped_img = image.crop(crop_box)
                tasks.append(self._async_ocr_call(session, cropped_img, region))
                
            # Execute all crops concurrently
            completed_regions = await asyncio.gather(*tasks)
            
            # Step 4: Missing Text Recovery (Second Pass OCR)
            recovery_tasks = []
            import cv2
            import numpy as np
            for r in completed_regions:
                if r.region_type in ["Figure", "Signature", "Table", "Checkbox"]:
                    continue
                    
                text = r.text_content
                # Heuristic: empty text or suspiciously short text
                if not text or len(text.strip()) == 0 or len(text) < 5:
                    logger.info(f"Triggering Second-Pass OCR Recovery for Region {r.region_id}")
                    
                    # Expand crop box padding by 5px
                    pad = 5
                    crop_box = (max(0, r.bbox[0]-pad), max(0, r.bbox[1]-pad), min(image.width, r.bbox[2]+pad), min(image.height, r.bbox[3]+pad))
                    cropped_img = image.crop(crop_box)
                    
                    # Apply aggressive contrast filter for small/faint text
                    cv_img = cv2.cvtColor(np.array(cropped_img), cv2.COLOR_RGB2BGR)
                    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
                    equalized = cv2.equalizeHist(gray)
                    recovery_img = Image.fromarray(cv2.cvtColor(equalized, cv2.COLOR_GRAY2RGB))
                    
                    recovery_tasks.append(self._async_ocr_call(session, recovery_img, r))
                    
            if recovery_tasks:
                await asyncio.gather(*recovery_tasks)
            
            # Re-integrate skipped regions
            completed_regions.extend(skipped_regions)
            return completed_regions

    def process_regions(self, image: Image.Image, regions: List[RegionPrediction]) -> List[RegionPrediction]:
        """Synchronous wrapper for Celery."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(self.process_regions_async(image, regions))
            
    async def _async_ocr_call(self, session: aiohttp.ClientSession, img: Image.Image, region: RegionPrediction) -> RegionPrediction:
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        prompt = "Extract the text exactly as it appears. Do not add conversational filler. If there is no text, return an empty string."
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.0
        }
        
        try:
            async with session.post(self.vllm_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    text = data["choices"][0]["message"]["content"].strip()
                    region.text_content = text
                else:
                    logger.error(f"vLLM API Error: {response.status}")
                    region.text_content = ""
        except Exception as e:
            logger.error(f"vLLM connection failed: {e}")
            region.text_content = ""
            
        return region
