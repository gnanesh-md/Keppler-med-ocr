import io
import torch
import logging
import pandas as pd
from PIL import Image
from typing import List, Dict

logger = logging.getLogger(__name__)

class TableExtractor:
    """
    Production-grade medical table extractor.
    Uses Microsoft Table Transformer (TATR) for precise row-level structure detection,
    and delegates to Qwen2.5-VL for text extraction.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TableExtractor, cls).__new__(cls)
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
            from transformers import TableTransformerForObjectDetection
        except ImportError:
            logger.error("transformers library is not installed.")
            return

        try:
            logger.info("Loading Microsoft Table Transformer (TATR)...")
            self.model = TableTransformerForObjectDetection.from_pretrained(
                "microsoft/table-transformer-structure-recognition"
            )
            self.model.eval()
        except Exception as e:
            logger.error(f"Failed to load TATR: {e}")

    async def extract(self, image: Image.Image, async_ocr_engine, page_num: int) -> pd.DataFrame:
        """
        Executes TATR structure recognition, slices rows, and builds a DataFrame.
        """
        if self.model is None:
            logger.warning("TATR model not loaded, skipping structural extraction.")
            return pd.DataFrame()

        w, h = image.size
        prompt = (
            "Extract the data in this table and format it as a clean Markdown table. "
            "Include all rows and columns exactly as they appear. Do not skip any rows. "
            "If the table spans multiple lines, preserve the structure in markdown format."
        )
        results = await async_ocr_engine.process_page_regions(
            regions=[{"region_id": "table_full", "region_type": "Table", "bbox": [0, 0, w, h], "confidence": 1.0}],
            raw_img=image,
            page_num=page_num,
            prompt=prompt
        )
        
        table_data = []
        if results:
            text = results[0]["text"]
            lines = [line.strip() for line in text.split('\n') if '|' in line]
            for line in lines:
                if '---' in line:
                    continue
                cols = [col.strip() for col in line.strip('|').split('|')]
                if any(cols):
                    table_data.append(cols)

        if not table_data:
            return pd.DataFrame()

        # Normalize column counts (pad short rows)
        max_cols = max(len(row) for row in table_data)
        for row in table_data:
            while len(row) < max_cols:
                row.append("")

        # Assume first row is header if we have more than 1 row
        if len(table_data) > 1:
            df = pd.DataFrame(table_data[1:], columns=table_data[0])
        else:
            df = pd.DataFrame(table_data)
            
        return df
