import asyncio
import base64
import time
import logging
from typing import List, Dict
import numpy as np
from PIL import Image
from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

MODEL_OPTIONS = {
    "temperature":  0,
    "num_ctx":      8192,
    "num_predict":  2048,
}

# Below this confidence, fall back to a second, genuinely different OCR engine
# (TrOCR) on the same crop and keep whichever result scores higher — the
# hybrid-engine behavior described in the original spec ("compare confidence,
# choose highest confidence"), scoped to what's practical on one shared GPU
# (see modules/handwriting_ocr.py).
TROCR_FALLBACK_THRESHOLD = 0.75

class AsyncRegionOCR:
    """
    Handles asynchronous, region-based OCR execution using AsyncOpenAI.
    Utilizes a semaphore to control concurrent VLLM requests and prevent OOM errors.
    """
    
    def __init__(self, max_concurrent: int = 3, model_name: str = "qwen2.5-vl-7b"):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.model_name = model_name
        # Deliberately NOT a module-level singleton: this class is instantiated
        # fresh inside every asyncio.run() call in modules/precision_ocr.py's
        # process_single_page (once per page). A module-level AsyncOpenAI
        # client would bind its connection pool to whichever event loop was
        # running the FIRST time it was used, then fail with connection
        # errors on every call after that event loop closes — a real,
        # reproducible bug (Celery workers are long-lived and process many
        # pages/jobs over their lifetime, each in its own asyncio.run() event
        # loop). Bounded timeout (SDK default is 600s) — a hung/overloaded
        # vLLM server should fail one region fast and let the existing
        # 6-strategy retry loop / Celery's own retry policy handle it, not
        # silently block a worker for up to 10 minutes per region.
        self.client = AsyncOpenAI(base_url=settings.VLLM_BASE_URL, api_key="EMPTY", timeout=90.0)

    async def _call_model_with_retry_async(self, raw_img: Image.Image, prompt: str) -> tuple[str, str, list, float]:
        """
        Async version of call_model_with_retry.
        Tries each preprocessing strategy in order.

        Returns (result, strategy_name, predictions, ocr_confidence). ocr_confidence
        is the mean per-token log-prob of the model's response, exponentiated to a
        [0, 1] probability — a genuine model-confidence signal (via the vLLM
        OpenAI-compatible endpoint's logprobs support), not a text heuristic. Used
        by _process_region to decide whether to try the TrOCR fallback.
        """
        # Local import to prevent circular dependency with precision_ocr.py
        from modules.precision_ocr import STRATEGIES, img_to_bytes, clean_output
        from modules.unified_resolver import resolve_entities_in_text

        for strategy_name, strategy_fn in STRATEGIES:
            try:
                # High resolution image processing for accurate OCR
                max_dim = 3000
                w, h = raw_img.size
                if max(w, h) > max_dim:
                    scale = max_dim / max(w, h)
                    raw_img = raw_img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)

                processed = strategy_fn(raw_img)
                image_bytes = img_to_bytes(processed)

                confidence = 0.0
                try:
                    base64_img = base64.b64encode(image_bytes).decode('utf-8')
                    resp = await self.client.chat.completions.create(
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
                        logprobs=True,
                        top_logprobs=1,
                    )
                    raw_text = resp.choices[0].message.content
                    logprobs_content = resp.choices[0].logprobs.content if resp.choices[0].logprobs else None
                    if logprobs_content:
                        mean_logprob = float(np.mean([t.logprob for t in logprobs_content]))
                        confidence = float(np.exp(mean_logprob))
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
                    return result, strategy_name, predictions, confidence

            except Exception as e:
                logger.warning(f"Async Strategy '{strategy_name}' failed: {e}")
                continue

        return "", "", [], 0.0

    async def _process_region(self, region: Dict, raw_img: Image.Image, page_num: int, prompt: str) -> Dict:
        """
        Processes a single layout region asynchronously, wrapped in a semaphore.
        Falls back to TrOCR (a genuinely different engine, not another retry of
        the same model) when the primary vLLM result's own confidence is low.
        """
        async with self.semaphore:
            box = region['bbox']
            # Add a 5px padding around crop to ensure edges aren't cut
            pad = 5
            w, h = raw_img.size
            crop_box = (max(0, box[0]-pad), max(0, box[1]-pad), min(w, box[2]+pad), min(h, box[3]+pad))
            cropped_img = raw_img.crop(crop_box)

            extracted_text, strategy_used, predictions, ocr_confidence = await self._call_model_with_retry_async(
                cropped_img, prompt
            )
            ocr_model_used = self.model_name

            if not extracted_text or ocr_confidence < TROCR_FALLBACK_THRESHOLD:
                try:
                    from modules.handwriting_ocr import TrOCREngine
                    trocr_text, trocr_confidence = await asyncio.to_thread(
                        TrOCREngine().recognize, cropped_img
                    )
                    if trocr_text and trocr_confidence > ocr_confidence:
                        extracted_text = trocr_text
                        ocr_confidence = trocr_confidence
                        ocr_model_used = "trocr-base-handwritten"
                        strategy_used = "trocr-fallback"
                except Exception as e:
                    logger.warning(f"TrOCR fallback failed for region {region['region_id']}: {e}")

            return {
                "page": page_num,
                "region_id": region["region_id"],
                "region_type": region["region_type"],
                "text": extracted_text,
                "bbox": box,
                "predictions": predictions,
                "strategy_used": strategy_used,
                "layout_confidence": region.get("confidence", 1.0),
                "ocr_confidence": ocr_confidence,
                "ocr_model_used": ocr_model_used,
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
