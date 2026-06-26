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

        import torchvision.transforms as T

        # TATR expects images resized and normalized
        transform = T.Compose([
            T.Resize(800),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        pixel_values = transform(image).unsqueeze(0)

        with torch.no_grad():
            outputs = self.model(pixel_values)

        w, h = image.size
        pred_logits = outputs.logits.squeeze(0)
        pred_boxes = outputs.pred_boxes.squeeze(0)

        # Filter predictions by confidence threshold
        probs = pred_logits.softmax(-1)[:, :-1]
        scores, labels = probs.max(-1)
        
        keep = scores > 0.5
        boxes = pred_boxes[keep]
        labels = labels[keep]

        # Convert relative cxcywh back to absolute xyxy
        center_x, center_y, width, height = boxes.unbind(-1)
        x1 = (center_x - 0.5 * width) * w
        y1 = (center_y - 0.5 * height) * h
        x2 = (center_x + 0.5 * width) * w
        y2 = (center_y + 0.5 * height) * h
        xyxy_boxes = torch.stack([x1, y1, x2, y2], dim=-1)

        # Extract "table row" boxes (Class ID 2 in TATR structure model)
        row_class_id = 2
        row_mask = (labels == row_class_id)
        row_boxes = xyxy_boxes[row_mask].tolist()
        row_scores = scores[row_mask].tolist()

        # Bundle with scores
        row_data = list(zip(row_boxes, row_scores))
        # Sort rows top-to-bottom
        row_data.sort(key=lambda x: x[0][1])

        # Fallback if no rows detected
        if not row_data:
            row_data = [([0, 0, w, h], 1.0)]

        # Prepare regions for AsyncRegionOCR
        row_regions = []
        for i, (r_box, r_conf) in enumerate(row_data):
            row_regions.append({
                "region_id": f"row_{i}",
                "region_type": "TableRow",
                "bbox": r_box,
                "confidence": r_conf
            })

        # Table-specific strict prompt
        prompt = (
            "Extract the data in this table row as a single pipe-delimited (|) string. "
            "Do not include markdown tables, explanations, or code fences. "
            "Ensure empty columns are represented by empty spaces between pipes. "
            "Output exactly one line of text."
        )

        # Execute extraction concurrently across all rows using existing engine
        results = await async_ocr_engine.process_page_regions(
            regions=row_regions,
            raw_img=image,
            page_num=page_num,
            prompt=prompt
        )

        # Build DataFrame
        table_data = []
        for res in results:
            text = res["text"].strip()
            # Split by pipe and clean up whitespace
            cols = [col.strip() for col in text.split('|')]
            if any(cols): # Skip completely empty rows
                table_data.append(cols)

        if not table_data:
            return pd.DataFrame()

        # Normalize column counts (pad short rows)
        max_cols = max(len(row) for row in table_data)
        for row in table_data:
            while len(row) < max_cols:
                row.append("")

        # Assume first row is header
        df = pd.DataFrame(table_data[1:], columns=table_data[0])
        return df
