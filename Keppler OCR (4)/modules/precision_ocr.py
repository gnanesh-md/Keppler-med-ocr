# modules/precision_ocr.py  — Production OCR Engine v2.0
"""
Production-level OCR pipeline using gemma4:26b vision model.
Features:
  - 5 adaptive image preprocessing strategies with auto-retry
  - Multi-page PDF support (processes all pages, merges results)
  - Image upscaling for low-resolution scans
  - Robust response parsing with fallback chain
  - Per-step error surfacing (no silent failures)
  - Archive vault integration
  - Download in MD / PDF / DOCX formats
"""
import time
import io
import asyncio
import json
import fitz          # PyMuPDF
import re
import math
import numpy as np
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from openai import OpenAI
import base64
import markdown
from xhtml2pdf import pisa
from docx import Document
import time
import pandas as pd
from modules.unified_resolver import resolve_entities_in_text
from modules.layout_detector import DocLayoutDetector
from modules.reading_order import ReadingOrderEngine
from modules.region_ocr import AsyncRegionOCR
from modules.table_extractor import TableExtractor
from modules.medical_corrector import MedicalCorrector
from modules.confidence_engine import ConfidenceEngine

client = OpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY")

# ---------------------------------------------------------------------------
# 1.  IMAGE PREPROCESSING STRATEGIES
MIN_DIM = 600   # minimum pixel dimension; smaller images are upscaled

def _upscale_if_small(img: Image.Image) -> Image.Image:
    """Upscale image if either dimension is below MIN_DIM."""
    w, h = img.size
    if min(w, h) < MIN_DIM:
        scale = MIN_DIM / min(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.BILINEAR)
    return img

def strategy_original(img: Image.Image) -> Image.Image:
    """Strategy 0 — Send the image with minimal changes (fix orientation only)."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    return img.convert("RGB")

def strategy_mild_enhance(img: Image.Image) -> Image.Image:
    """Strategy 1 — Mild sharpening + contrast boost. Best for printed forms."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    img = img.convert("RGB")
    img = ImageEnhance.Sharpness(img).enhance(1.8) 
    img = ImageEnhance.Contrast(img).enhance(1.5)
    return img

def strategy_grayscale_boost(img: Image.Image) -> Image.Image:
    """Strategy 2 — Grayscale + moderate contrast. Good for photocopies."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    return gray.convert("RGB")

def strategy_adaptive_threshold(img: Image.Image) -> Image.Image:
    """Strategy 3 — Near-binarization for faded handwriting on white background."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    gray = img.convert("L")
    # Auto-level: stretch histogram
    arr = np.array(gray, dtype=np.float32)
    p2, p98 = np.percentile(arr, 2), np.percentile(arr, 98)
    if p98 > p2:
        arr = np.clip((arr - p2) / (p98 - p2) * 255, 0, 255)
    gray = Image.fromarray(arr.astype(np.uint8))
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    # Unsharp mask to make thin strokes pop
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
    return gray.convert("RGB")

def strategy_denoised(img: Image.Image) -> Image.Image:
    """Strategy 4 — Denoise first then enhance. For camera photos of documents."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    img = img.convert("RGB")
    # Median filter removes camera noise
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img

STRATEGIES = [
    ("Original",            strategy_original),
    ("Mild Enhancement",    strategy_mild_enhance),
    ("Grayscale Boost",     strategy_grayscale_boost),
    ("Adaptive Threshold",  strategy_adaptive_threshold),
    ("Denoise + Enhance",   strategy_denoised),
]

def img_to_bytes(img: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

# ---------------------------------------------------------------------------
# 2.  RESPONSE CLEANING
# ---------------------------------------------------------------------------
def clean_output(raw: str) -> str:
    """
    Remove model control tokens and code fences.
    Falls back to the raw text if cleaning removes everything.
    Preserves medical symbols like < > in reference ranges.
    """
    if not raw:
        return ""

    text = raw

    # Strip content before <|text|> markers (some model variants)
    if "<|text|>" in text:
        text = text.split("<|text|>")[-1]
    if "</|text|>" in text:
        text = text.split("</|text|>")[0]

    # Remove thinking blocks — both formats used by different model variants
    text = re.sub(r'<\|think\|>.*?</\|think\|>', '', text, flags=re.DOTALL)   # pipe format
    text = re.sub(r'<think>.*?</think>',           '', text, flags=re.DOTALL)   # plain format

    # Remove code fences
    text = re.sub(r'```[a-z]*\n?', '', text)
    text = text.replace('```', '')

    cleaned = text.strip()

    # Safety fallback: if stripping removed EVERYTHING, return raw minus fences
    if not cleaned:
        fallback = re.sub(r'```[a-z]*\n?', '', raw).replace('```', '').strip()
        return fallback

    return cleaned

# ---------------------------------------------------------------------------
# 3.  PDF MULTI-PAGE LOADER
# ---------------------------------------------------------------------------
def load_pdf_pages(file_bytes: bytes, max_pages: int = 10) -> list[Image.Image]:
    """Extract all pages from a PDF as PIL images at 220 DPI (Balanced for Qwen)."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        pix  = page.get_pixmap(dpi=144)
        pages.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return pages

# ---------------------------------------------------------------------------
# 5.  EXPORT GENERATORS  (PDF / DOCX)
# ---------------------------------------------------------------------------
def generate_pro_pdf(md_text: str, client_name: str) -> bytes | str:
    try:
        safe = re.sub(r'<\|.*?\|>', '', md_text)
        safe = safe.replace('<', '&lt;').replace('>', '&gt;')
        safe = safe.replace('\u2022', '*').replace('\u2713', '[x]')
        html_body = markdown.markdown(safe, extensions=['tables'])
        orientation = "landscape" if "| S.No |" in md_text else "portrait"
        html = f"""<html><head><style>
            @page {{size: A4 {orientation}; margin:1cm;}}
            body {{font-family:Helvetica,Arial,sans-serif; font-size:10px;}}
            table {{width:100%; border-collapse:collapse; margin-top:10px;}}
            th,td {{border:1px solid #333; padding:5px; text-align:left;}}
            th {{background:#ddd; font-weight:bold;}}
        </style></head><body>{html_body}</body></html>"""
        out = io.BytesIO()
        status = pisa.CreatePDF(io.StringIO(html), dest=out, encoding="utf-8")
        return out.getvalue() if not status.err else f"PDF Error: {status.err}"
    except Exception as e:
        return f"PDF Error: {e}"

def generate_docx(md_text: str, client_name: str) -> bytes | str:
    try:
        doc = Document()
        clean = re.sub(r'<\|.*?\|>', '', md_text)
        in_table = False
        table    = None
        for line in clean.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.startswith('|'):
                if '---' in line:
                    continue
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if not cells:
                    continue
                if not in_table:
                    table    = doc.add_table(rows=1, cols=len(cells))
                    table.style = 'Table Grid'
                    for i, c in enumerate(cells):
                        table.rows[0].cells[i].text = c
                    in_table = True
                else:
                    row = table.add_row()
                    for i, c in enumerate(cells):
                        if i < len(row.cells):
                            row.cells[i].text = c
            else:
                in_table = False
                doc.add_paragraph(line)
        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()
    except Exception as e:
        return f"Word Error: {e}"

def generate_excel(md_text: str) -> bytes | None:
    if not md_text.strip():
        return None
        
    try:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            # --- 1. CONSOLIDATED REPORT (Primary Sheet) ---
            report_data = []
            lines = md_text.split('\n')
            
            # Extract key-value pairs (like **Key:** Value)
            metadata = []
            other_text = []
            tables = []
            current_table = []
            
            for line in lines:
                raw_line = line.strip()
                if not raw_line: continue
                
                # Table detection
                if raw_line.count('|') >= 2:
                    if all(c in '|- ' for c in raw_line) and '-' in raw_line:
                        continue
                    cells = [c.strip() for c in raw_line.split('|') if c.strip()]
                    if cells:
                        current_table.append(cells)
                    continue
                else:
                    if current_table:
                        if len(current_table) > 1:
                            tables.append(current_table)
                        current_table = []
                
                # Metadata detection (Bold keys)
                if '**' in raw_line and ':' in raw_line:
                    # Clean up markers like **Patient Name:**
                    parts = re.split(r'\*\*|\*', raw_line)
                    cleaned = " ".join([p.strip() for p in parts if p.strip()])
                    metadata.append([cleaned])
                else:
                    other_text.append([raw_line])
            
            if current_table and len(current_table) > 1:
                tables.append(current_table)

            # Build the master list for the first sheet
            # [A] Patient / Form Metadata
            if metadata:
                report_data.append(["--- FORM DETAILS ---"])
                report_data.extend(metadata)
                report_data.append([""]) # Spacer
            
            # [B] Tables
            if tables:
                for i, table in enumerate(tables):
                    report_data.append([f"--- TABLE {i+1} ---"])
                    report_data.extend(table)
                    report_data.append([""]) # Spacer
            
            # [C] Other Text / Footer
            if other_text:
                report_data.append(["--- ADDITIONAL INFORMATION ---"])
                report_data.extend(other_text)
            
            # Create the Consolidated Sheet
            # Find max width to avoid dataframe errors
            max_cols = max([len(r) for r in report_data]) if report_data else 1
            df_cons = pd.DataFrame(report_data, columns=[f"Col {i+1}" for i in range(max_cols)])
            df_cons.to_excel(writer, index=False, header=False, sheet_name='Consolidated Report')
            
            # --- 2. CLEAN TABLE SHEETS (Individual sheets for analysis) ---
            if tables:
                for i, table in enumerate(tables):
                    header = table[0]
                    rows = table[1:]
                    cleaned_rows = [r[:len(header)] if len(r) > len(header) else r + ['']*(len(header)-len(r)) for r in rows]
                    df_table = pd.DataFrame(cleaned_rows, columns=header)
                    sheet_name = f'Table_{i+1}'
                    df_table.to_excel(writer, index=False, sheet_name=sheet_name)
            
            # --- 3. RAW EXTRACTION SHEET ---
            paragraphs = [p.strip() for p in md_text.split('\n') if p.strip()]
            df_full = pd.DataFrame({"Raw Content": paragraphs})
            df_full.to_excel(writer, index=False, sheet_name='Raw Text')
            
        return out.getvalue()
    except Exception as e:
        print(f"Excel Error: {e}")
        # Final fallback
        try:
            out = io.BytesIO()
            pd.DataFrame({"Extraction": [md_text]}).to_excel(out, index=False)
            return out.getvalue()
        except:
            return None

def generate_json(md_text: str) -> str:
    if not md_text.strip(): return "{}"
    
    data = {"metadata": {}, "tables": [], "text": []}
    lines = md_text.split('\n')
    current_table = []
    
    for line in lines:
        raw = line.strip()
        if not raw: continue
        
        if raw.count('|') >= 2:
            if all(c in '|- ' for c in raw) and '-' in raw: continue
            cells = [c.strip() for c in raw.split('|') if c.strip()]
            if cells: current_table.append(cells)
            continue
        else:
            if current_table and len(current_table) > 1:
                header = current_table[0]
                rows = current_table[1:]
                table_data = []
                for row in rows:
                    row_dict = {}
                    for i, h in enumerate(header):
                        row_dict[h] = row[i] if i < len(row) else ""
                    table_data.append(row_dict)
                data["tables"].append(table_data)
                current_table = []
        
        if '**' in raw and ':' in raw:
            parts = raw.split('**')
            if len(parts) >= 3:
                key = parts[1].replace(':', '').strip()
                val = "".join(parts[2:]).strip()
                if key: data["metadata"][key] = val
            else:
                data["text"].append(raw)
        else:
            data["text"].append(raw)
            
    if current_table and len(current_table) > 1:
        header = current_table[0]
        rows = current_table[1:]
        table_data = []
        for row in rows:
            row_dict = {}
            for i, h in enumerate(header):
                row_dict[h] = row[i] if i < len(row) else ""
            table_data.append(row_dict)
        data["tables"].append(table_data)
        
    return json.dumps(data, indent=2)

# ---------------------------------------------------------------------------
# 6.  BLUEPRINTS
# ---------------------------------------------------------------------------
BLUEPRINTS = {
    "Universal OCR (Any Text)": {
        "identity": "You are an advanced Universal OCR engine capable of extracting text from ANY image. Your job is to perform complete, highly accurate, and exhaustive transcription of the entire document from top to bottom.",
        "structure": "Organize the extracted text into a clean, professional Markdown format. Use Markdown Headers (###) for sections, **bold text** for keys/labels, bullet points (-) for lists, and Markdown Tables (|---|) for any tabular or grid-like data.",
        "instructions": "MANDATORY: Extract EVERY single line of text from the image without exception. Do not truncate, omit, or summarize the content. Scan the entire image carefully and transcribe all items, values, and notes from top to bottom.",
        "rules": "2. EXHAUSTIVE TRANSCRIPTION: Do not stop generating until the very last word of the image is transcribed.\n3. FORMATTING: Use Markdown (bolding, lists, tables) to give the text a professional structure.\n4. KEY-VALUE PAIRS: If you see a label and a value (e.g., Name: John), format it as **Name:** John.\n5. NO PREAMBLE: Start directly with the extracted data. No greetings or meta-commentary.\n6. MISSING DATA: If any field is missing from the document, leave it completely blank. Do NOT write 'Not documented', 'N/A', or 'None'."
    },
    "LDSL Diagnostics": {
        "identity": "You are a high-performance medical OCR engine (Qwen 2.5 VL optimized).",
        "structure": """\
**Patient Name:** [Full Name] | **Age/Sex:** [Age]/[Sex]
**Referred Doctor:** [Doctor Name] | **Coll. Time & Date:** [Date and Time]

| S.No | Test Description | Sample Type | Result (if any) |
|------|-----------------|-------------|-----------------|
| 1    | [Test Name]     | [Sample]    | [Value/Result]  |

**History:** DOB: [DOB] | Weight: [Weight] | Diabetes: [Yes/No] | Ultrasound: [Details]
**Footer:** Checked By: [Name] | Area: [Location]""",
        "instructions": "MANDATORY: Transcribe every handwritten entry exactly. Use the Markdown table for all test results. Do not omit the Patient Name or History section.",
        "rules": "2. SPATIAL AWARENESS: Maintain the exact layout and hierarchy seen in the document.\n3. HANDWRITING: Transcribe every handwritten scribble or mark. If a checkmark is present in a box, represent it as [x].\n4. NUMERICAL PRECISION: Do not round or alter any numbers, dates, or measurements.\n5. NO PREAMBLE: Start directly with the extracted data. No greetings or meta-commentary.\n6. TABLE INTEGRITY: Ensure every column of the table is populated correctly based on the visual rows.\n7. MISSING DATA: If any field is missing from the document, leave it completely blank. Do NOT write 'Not documented', 'N/A', or 'None'."
    },
    "Healmax Diagnostics": {
        "identity": "You are a high-performance medical OCR engine (Qwen 2.5 VL optimized).",
        "structure": """\
**Franchisee Code:** ___ | **Date:** ___

| S.No | Patient Name | Age/Sex | Test Code/Name | Sample Type | Barcode No | Date/Time | Customer | Referral Doctor |
|------|-------------|---------|----------------|-------------|------------|-----------|----------|-----------------|""",
        "instructions": "Fill all 9 table columns. Do NOT merge or skip any column.",
        "rules": "2. SPATIAL AWARENESS: Maintain the exact layout and hierarchy seen in the document.\n3. HANDWRITING: Transcribe every handwritten scribble or mark. If a checkmark is present in a box, represent it as [x].\n4. NUMERICAL PRECISION: Do not round or alter any numbers, dates, or measurements.\n5. NO PREAMBLE: Start directly with the extracted data. No greetings or meta-commentary.\n6. TABLE INTEGRITY: Ensure every column of the table is populated correctly based on the visual rows.\n7. MISSING DATA: If any field is missing from the document, leave it completely blank. Do NOT write 'Not documented', 'N/A', or 'None'."
    }
}

# ---------------------------------------------------------------------------
# 7.  PROMPT BUILDER
# ---------------------------------------------------------------------------
def build_prompt(client: str, page_info: str = "") -> str:
    bp = BLUEPRINTS.get(client, BLUEPRINTS["Universal OCR (Any Text)"])
    page_note = f" ({page_info})" if page_info else ""
    return f"""{bp['identity']}{page_note}

Your objective: Extract EVERY piece of text from the image with 100% fidelity.

Output Format:
{bp['structure']}

Rules for 100% Accuracy:
1. MANDATORY: {bp['instructions']}
{bp['rules']}"""

# ---------------------------------------------------------------------------
# 8.  CORE PIPELINE (Streamlit-free — used by both render_ocr_app() and the FastAPI worker)
# ---------------------------------------------------------------------------
def run_ocr_pipeline(pages: list[Image.Image], client: str, progress_cb=None) -> dict:
    """
    Run the full per-page OCR pipeline (layout detection -> reading order ->
    async region OCR -> table extraction -> medical correction -> confidence fusion)
    over already-loaded page images.

    progress_cb, if given, is called with a float in [0, 1] as pages complete.

    Returns {"pages": [(label, text), ...], "combined": str, "predictions": list[dict], "elapsed": float}.
    """
    start_time = time.time()
    total_pages = len(pages)
    page_labels = [f"Page {i+1}" for i in range(total_pages)]

    all_pages_text = []
    all_preds = []

    for idx, (raw_img, label) in enumerate(zip(pages, page_labels)):
        base_pct = idx / total_pages
        page_slice = 1.0 / total_pages

        if progress_cb: progress_cb(base_pct + 0.05 * page_slice)

        page_info = f"{label} of {total_pages}" if total_pages > 1 else ""
        prompt = build_prompt(client, page_info)

        # Layout Detection Layer
        if progress_cb: progress_cb(base_pct + 0.15 * page_slice)
        detector = DocLayoutDetector()
        regions = detector.detect_regions(raw_img)

        # Reading Order Reconstruction
        if progress_cb: progress_cb(base_pct + 0.30 * page_slice)
        ro_engine = ReadingOrderEngine()
        w, h = raw_img.size
        ordered_mapping = ro_engine.reconstruct(regions, page_width=w, page_height=h)

        order_dict = {item['region_id']: item['reading_order'] for item in ordered_mapping}
        regions.sort(key=lambda r: order_dict.get(r['region_id'], 9999))

        non_table_regions = []
        table_regions = []
        for r in regions:
            if r['region_type'] == 'Table':
                table_regions.append(r)
            else:
                non_table_regions.append(r)

        # Async region OCR for standard content
        if progress_cb: progress_cb(base_pct + 0.45 * page_slice)
        async_ocr = AsyncRegionOCR(max_concurrent=5, model_name="qwen2.5-vl-7b")
        table_extractor = TableExtractor()

        structured_results = asyncio.run(async_ocr.process_page_regions(
            regions=non_table_regions,
            raw_img=raw_img,
            page_num=idx + 1,
            prompt=prompt
        ))

        # Table Extraction (TATR)
        if progress_cb: progress_cb(base_pct + 0.65 * page_slice)
        for t_reg in table_regions:
            pad = 10
            box = t_reg['bbox']
            w, h = raw_img.size
            crop_box = (max(0, box[0] - pad), max(0, box[1] - pad), min(w, box[2] + pad), min(h, box[3] + pad))
            table_img = raw_img.crop(crop_box)

            df = asyncio.run(table_extractor.extract(table_img, async_ocr, page_num=idx + 1))
            if not df.empty:
                md_table = df.to_markdown(index=False)
                structured_results.append({
                    "page": idx + 1,
                    "region_id": t_reg["region_id"],
                    "region_type": "Table",
                    "text": md_table,
                    "bbox": box,
                    "predictions": []
                })

        # Re-sort results to preserve semantic reading order
        structured_results.sort(key=lambda r: order_dict.get(r['region_id'], 9999))

        page_extracted_parts = []
        success_count = 0

        for res in structured_results:
            if res["text"]:
                success_count += 1
                clean_txt = res["text"].replace('*', '').replace('#', '')
                page_extracted_parts.append(clean_txt)
                layout_conf = res.get("layout_confidence", 1.0)
                for pred in res.get("predictions", []):
                    sem_conf = float(pred.get("Confidence", 0.0))
                    final_conf = ConfidenceEngine.calculate_final_confidence(layout_conf, sem_conf)
                    pred["Confidence"] = f"{final_conf:.2f}"
                    pred["page"] = idx + 1
                    pred["bbox"] = res.get("bbox", [])
                    all_preds.append(pred)

        if success_count > 0:
            final_page_text = "\n\n".join(page_extracted_parts)

            # Medical Correction Layer
            if progress_cb: progress_cb(base_pct + 0.85 * page_slice)
            med_corrector = MedicalCorrector()
            correction_result = asyncio.run(med_corrector.correct_text(final_page_text))

            corrected_page_text = correction_result["corrected_text"]

            for c in correction_result.get("corrections", []):
                sem_conf = float(c.get('confidence', 0.0))
                final_conf = ConfidenceEngine.calculate_final_confidence(1.0, sem_conf)
                all_preds.append({
                    "Original Text": c["original"],
                    "Predicted Code": "CORRECTION",
                    "Predicted Name": c["corrected"],
                    "Type": "Medical Typo",
                    "Confidence": f"{final_conf:.2f}",
                    "page": idx + 1,
                    "bbox": []
                })

            all_pages_text.append((label, corrected_page_text))
        else:
            all_pages_text.append((label, f"*[{label}: Extraction failed — content too short or empty]*"))

    if progress_cb:
        progress_cb(1.0)

    elapsed = time.time() - start_time

    if total_pages == 1:
        combined = all_pages_text[0][1]
    else:
        parts = [f"---\n### {lbl}\n\n{txt}" for lbl, txt in all_pages_text]
        combined = "\n\n".join(parts)

    return {
        "pages": all_pages_text,
        "combined": combined,
        "predictions": all_preds,
        "elapsed": elapsed,
    }

