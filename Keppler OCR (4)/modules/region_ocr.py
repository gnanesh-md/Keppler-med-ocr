import asyncio
import base64
import time
import logging
from typing import List, Dict
from PIL import Image
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Initialize Async client
client = AsyncOpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY")

MODEL_OPTIONS = {
    "temperature":  0,
    "num_ctx":      8192,   
    "num_predict":  2048,   
}

class AsyncRegionOCR:
    """
    Handles asynchronous, region-based OCR execution using AsyncOpenAI.
    Utilizes a semaphore to control concurrent VLLM requests and prevent OOM errors.
    """
    
    def __init__(self, max_concurrent: int = 3, model_name: str = "qwen2.5-vl-7b"):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.model_name = model_name

    async def _call_model_with_retry_async(self, raw_img: Image.Image, prompt: str) -> tuple[str, str, list]:
        """
        Async version of call_model_with_retry.
        Tries each preprocessing strategy in order.
        """
        # Local import to prevent circular dependency with precision_ocr.py
        from modules.precision_ocr import STRATEGIES, img_to_bytes, clean_output
        from modules.unified_resolver import resolve_entities_in_text

        for strategy_name, strategy_fn in STRATEGIES:
            try:
                # High resolution image processing for accurate OCR
                max_dim = 1280
                w, h = raw_img.size
                if max(w, h) > max_dim:
                    scale = max_dim / max(w, h)
                    raw_img = raw_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                    
                processed = strategy_fn(raw_img)
                image_bytes = img_to_bytes(processed)

                try:
                    base64_img = base64.b64encode(image_bytes).decode('utf-8')
                    resp = await client.chat.completions.create(
                        model=self.model_name,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                            ]
                        }],
                        temperature=MODEL_OPTIONS.get("temperature", 0),
                        max_tokens=MODEL_OPTIONS.get("num_predict", 2048),
                    )
                    raw_text = resp.choices[0].message.content
                except Exception as e:
                    logger.warning(f"vLLM unavailable or request failed: {e}")
                    raw_text = ""
                
                # Proceed with cleaning even if raw_text is empty
                result = clean_output(raw_text)
                predictions = []
                
                try:
                    result, predictions = resolve_entities_in_text(result)
                except Exception:
                    pass

                if result and len(result.strip()) >= 5:
                    return result, strategy_name, predictions

            except Exception as e:
                logger.warning(f"Async Strategy '{strategy_name}' failed: {e}")
                continue

        return "", "", []

    async def _process_region(self, region: Dict, raw_img: Image.Image, page_num: int, prompt: str) -> Dict:
        """
        Processes a single layout region asynchronously, wrapped in a semaphore.
        """
        async with self.semaphore:
            box = region['bbox']
            # Add a 5px padding around crop to ensure edges aren't cut
            pad = 5
            w, h = raw_img.size
            crop_box = (max(0, box[0]-pad), max(0, box[1]-pad), min(w, box[2]+pad), min(h, box[3]+pad))
            cropped_img = raw_img.crop(crop_box)
            
            extracted_text, strategy_used, predictions = await self._call_model_with_retry_async(cropped_img, prompt)
            
            return {
                "page": page_num,
                "region_id": region["region_id"],
                "region_type": region["region_type"],
                "text": extracted_text,
                "bbox": box,
                "predictions": predictions,
                "strategy_used": strategy_used,
                "layout_confidence": region.get("confidence", 1.0)
            }

    async def process_page_regions(self, regions: List[Dict], raw_img: Image.Image, page_num: int, prompt: str) -> List[Dict]:
        """
        Processes all regions on a page concurrently up to the semaphore limit.
        Returns a list of structured region results in the exact order they were provided.
        """
        tasks = []
        for region in regions:
            # Create a task for each region
            task = asyncio.create_task(self._process_region(region, raw_img, page_num, prompt))
            tasks.append(task)
            
        # Gather all tasks concurrently
        results = await asyncio.gather(*tasks)
        return list(results)
