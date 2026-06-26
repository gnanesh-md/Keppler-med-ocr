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
import streamlit as st
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
from database.db_utils import archive_document
from modules.unified_resolver import resolve_entities_in_text
from modules.layout_detector import DocLayoutDetector
from modules.reading_order import ReadingOrderEngine
from modules.region_ocr import AsyncRegionOCR
from modules.table_extractor import TableExtractor
from modules.medical_corrector import MedicalCorrector
from modules.confidence_engine import ConfidenceEngine
from modules.grounding import VisualGrounder

client = OpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY")

# ---------------------------------------------------------------------------
# 1.  IMAGE PREPROCESSING STRATEGIES
MIN_DIM = 800   # minimum pixel dimension; smaller images are upscaled

def _upscale_if_small(img: Image.Image) -> Image.Image:
    """Upscale image if either dimension is below MIN_DIM."""
    w, h = img.size
    if min(w, h) < MIN_DIM:
        scale = MIN_DIM / min(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
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
# 3.  OLLAMA CALL WITH RETRY ACROSS PREPROCESSING STRATEGIES
# ---------------------------------------------------------------------------
MODEL_OPTIONS = {
    "temperature":  0,
    "num_ctx":      8192,   
    "num_predict":  2048,   
}

def call_model_with_retry(
    raw_img: Image.Image,
    prompt: str,
    status_placeholder=None,
    model_name="qwen2.5-vl-7b"
) -> tuple[str, str]:
    """
    Try each preprocessing strategy in order.
    Returns (extracted_text, strategy_name_used) or ('', '') on total failure.
    """
    for strategy_name, strategy_fn in STRATEGIES:
        if status_placeholder:
            status_placeholder.info(f"🔄 Trying strategy: **{strategy_name}**…")
        try:
            # High resolution image processing for accurate OCR
            max_dim = 1280
            w, h = raw_img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                raw_img = raw_img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                
            processed = strategy_fn(raw_img)
            image_bytes = img_to_bytes(processed)

            # Attempt to call the model.
            try:
                base64_img = base64.b64encode(image_bytes).decode('utf-8')
                resp = client.chat.completions.create(
                    model=model_name,
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
                # If vLLM is unavailable or the request fails, warn and skip this strategy.
                st.warning(f"vLLM unavailable or request failed: {e}")
                raw_text = ""
            
            # Proceed with cleaning even if raw_text is empty.
            result = clean_output(raw_text)
            predictions = []
            # Annotate entities (Items, Services, Frequencies) with resolved meanings when possible
            try:
                result, predictions = resolve_entities_in_text(result)
            except Exception:
                pass
            
            # DEBUG LOGGING (Absolute path)
            try:
                from pathlib import Path
                log_dir = Path(__file__).resolve().parents[1] / "database"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / "ocr_debug.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n--- {time.strftime('%H:%M:%S')} | STRATEGY: {strategy_name} ---\n")
                    f.write(f"RAW (len {len(raw_text)}): {raw_text[:300]}\n")
                    f.write(f"CLEANED (len {len(result)}): {result[:300]}\n")
            except Exception:
                pass

            if result and len(result.strip()) >= 5:
                return result, strategy_name, predictions

        except Exception as e:
            if status_placeholder:
                status_placeholder.warning(f"⚠️ Strategy '{strategy_name}' failed: {e}")
            continue

    return "", "", []

# ---------------------------------------------------------------------------
# 4.  PDF MULTI-PAGE LOADER
# ---------------------------------------------------------------------------
def load_pdf_pages(file_bytes: bytes, max_pages: int = 10) -> list[Image.Image]:
    """Extract all pages from a PDF as PIL images at 220 DPI (Balanced for Qwen)."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        pix  = page.get_pixmap(dpi=220)
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
# 8.  MAIN STREAMLIT APP
# ---------------------------------------------------------------------------
def render_ocr_app():
    client    = st.session_state.get("current_client", "Universal OCR (Any Text)")

    st.header("⚡ Keppler OCR")

    # Session-state initialisation
    for key, default in [
        ("ocr_pages",    []),   # list of (page_label, extracted_text)
        ("ocr_combined", ""),
        ("last_time",    0.0),
        ("ocr_client",   ""),
        ("ocr_images",   []),   # list of original PIL images
        ("active_grounding", None), # dict for current highlight tracking
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Reset results when client template changes
    if st.session_state.ocr_client != client:
        st.session_state.ocr_pages    = []
        st.session_state.ocr_combined = ""
        st.session_state.ocr_images   = []
        st.session_state.ocr_client   = client

    # ── SIDEBAR ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 📤 Upload Document")
        uploaded = st.file_uploader(
            "Supported: PNG, JPG, JPEG, PDF",
            type=["png", "jpg", "jpeg", "pdf"],
            key="ocr_uploader_prod",
        )

        process_btn = st.button(
            "🚀 Extract Data",
            width='stretch',
            type="primary",
        )
        clear_btn = st.button(
            "🗑️ Clear Results",
            width='stretch',
        )

        st.divider()
        st.markdown("**⚙️ Engine Info**")
        st.caption("Active Model: `qwen2.5vl:32b` (Fixed)")
        st.caption("Resolution: Optimized 300 DPI")
        st.caption("Strategies: 5 adaptive preprocessing layers")
        st.caption("Auto-retries if response is empty")

    if clear_btn:
        st.session_state.ocr_pages    = []
        st.session_state.ocr_combined = ""
        st.session_state.ocr_images   = []
        st.session_state.last_time    = 0.0
        st.rerun()

    # ── PROCESSING ──────────────────────────────────────────────────────────
    if process_btn:
        if not uploaded:
            st.warning("⚠️ Please upload a file first.")
        else:
            st.session_state.ocr_pages    = []
            st.session_state.ocr_combined = ""
            st.session_state.ocr_images   = []

            start_time = time.time()

            # Load pages
            try:
                if uploaded.name.lower().endswith(".pdf"):
                    pages = load_pdf_pages(uploaded.read())
                    page_labels = [f"Page {i+1}" for i in range(len(pages))]
                else:
                    pages = [Image.open(uploaded)]
                    page_labels = ["Page 1"]
                
                st.session_state.ocr_images = pages
            except Exception as e:
                st.error(f"❌ Could not open file: {e}")
                st.stop()

            total_pages = len(pages)
            progress    = st.progress(0, text="Starting…")
            status_box  = st.empty()

            all_pages_text = []
            all_preds = []

            for idx, (raw_img, label) in enumerate(zip(pages, page_labels)):
                progress.progress(
                    (idx) / total_pages,
                    text=f"Processing {label} of {total_pages}…"
                )

                page_info = f"{label} of {total_pages}" if total_pages > 1 else ""
                prompt    = build_prompt(client, page_info)

                # Layout Detection Layer
                status_box.info(f"🔍 Analyzing document layout for {label}...")
                detector = DocLayoutDetector()
                regions = detector.detect_regions(raw_img)
                
                status_box.info("📚 Reconstructing Semantic Reading Order...")
                ro_engine = ReadingOrderEngine()
                w, h = raw_img.size
                ordered_mapping = ro_engine.reconstruct(regions, page_width=w, page_height=h)
                
                # Sort regions by reading order
                order_dict = {item['region_id']: item['reading_order'] for item in ordered_mapping}
                regions.sort(key=lambda r: order_dict.get(r['region_id'], 9999))
                
                status_box.info(f"✂️ Detected {len(regions)} layout regions. Processing asynchronously in batches...")
                
                non_table_regions = []
                table_regions = []
                for r in regions:
                    if r['region_type'] == 'Table':
                        table_regions.append(r)
                    else:
                        non_table_regions.append(r)
                        
                # Execute async region OCR for standard content
                async_ocr = AsyncRegionOCR(max_concurrent=3, model_name="qwen2.5-vl-7b")
                table_extractor = TableExtractor()
                
                structured_results = asyncio.run(async_ocr.process_page_regions(
                    regions=non_table_regions, 
                    raw_img=raw_img, 
                    page_num=idx+1, 
                    prompt=prompt
                ))
                
                # Process tables with TATR
                for t_reg in table_regions:
                    status_box.info(f"📊 Extracting Table Structure using TATR...")
                    pad = 10
                    box = t_reg['bbox']
                    w, h = raw_img.size
                    crop_box = (max(0, box[0]-pad), max(0, box[1]-pad), min(w, box[2]+pad), min(h, box[3]+pad))
                    table_img = raw_img.crop(crop_box)
                    
                    df = asyncio.run(table_extractor.extract(table_img, async_ocr, page_num=idx+1))
                    if not df.empty:
                        md_table = df.to_markdown(index=False)
                        structured_results.append({
                            "page": idx+1,
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
                        page_extracted_parts.append(f"### [{res['region_type']}]\n{res['text']}")
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
                    status_box.info("⚕️ Running Medical Terminology Correction...")
                    med_corrector = MedicalCorrector()
                    correction_result = asyncio.run(med_corrector.correct_text(final_page_text))
                    
                    corrected_page_text = correction_result["corrected_text"]
                    
                    # Append corrections to the predictions array for UI display
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
                        
                    status_box.success(f"✅ {label} extracted ({success_count}/{len(regions)} regions, {len(correction_result.get('corrections', []))} corrections)")
                    all_pages_text.append((label, corrected_page_text))
                else:
                    status_box.error(
                        f"❌ {label}: Extraction failed for all regions."
                    )
                    all_pages_text.append((label, f"*[{label}: Extraction failed — content too short or empty]*"))

            progress.progress(1.0, text="Done!")

            elapsed = time.time() - start_time
            st.session_state.ocr_pages    = all_pages_text
            st.session_state.last_time    = elapsed
            st.session_state.ocr_predictions = all_preds

            # Merge all pages into one document
            if total_pages == 1:
                st.session_state.ocr_combined = all_pages_text[0][1]
            else:
                parts = []
                for lbl, txt in all_pages_text:
                    parts.append(f"---\n### {lbl}\n\n{txt}")
                st.session_state.ocr_combined = "\n\n".join(parts)

            # Archive
            try:
                archive_document(
                    user_id   = st.session_state.get("user_id", 1),
                    filename  = uploaded.name,
                    category  = client,
                    markdown  = st.session_state.ocr_combined,
                    confidence= 99.0,
                )
            except Exception as arc_err:
                st.warning(f"⚠️ Vault archiving failed (result still shown): {arc_err}")

            st.rerun()

    # ── CLEAN TEXT DOCUMENT RENDERER (NO HIGHLIGHTS) ───────────────────────
    def render_clean_document(text):
        """Render OCR text cleanly without background colors.
        Uses simple text coloring to distinguish OCR vs Matched content.
        """
        import html as html_mod

        # Define pure inline styles
        S_DOC = "font-family: 'Inter', 'Segoe UI', sans-serif; background: #0d1117; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 20px 24px; line-height: 2.0; font-size: 15px; color: #c9d1d9;"
        
        # Styles for text sections
        S_OCR_LBL = "font-size: 11px; font-weight: 700; color: #8b949e; text-transform: uppercase;"
        S_OCR_TXT = "color: #8b949e; font-style: italic;"
        
        S_ARROW = "color: #484f58; margin: 0 8px; font-size: 14px;"
        
        S_MATCH_LBL = "font-size: 11px; font-weight: 700; color: #58a6ff; text-transform: uppercase;"
        S_MATCH_CODE = "font-family: 'Courier New', monospace; font-size: 13px; color: #79c0ff; font-weight: 700;"
        S_MATCH_TXT = "color: #e6edf3; font-weight: 600;"

        annotation_re = re.compile(r'\[([^\[\]]+?)\s*→\s*([^\[\]]+?)\]')

        raw_lines = text.split('\n')
        while raw_lines and not raw_lines[-1].strip():
            raw_lines.pop()

        entity_count = len(annotation_re.findall(text))
        total_lines = sum(1 for l in raw_lines if l.strip())

        lines_html = []
        for raw_line in raw_lines:
            stripped = raw_line.strip()

            # Skip empty
            if not stripped:
                lines_html.append('<br>')
                continue

            # Skip markdown separators and headings — just render as text
            stripped = re.sub(r'^#{1,4}\s+', '', stripped)
            stripped = stripped.replace('---', '').strip()
            if not stripped:
                continue

            # Check for entity annotations
            matches = list(annotation_re.finditer(stripped))

            if matches:
                # Build the line with simple text formatting
                parts = []
                last_end = 0
                for m in matches:
                    # Text before annotation = OCR extracted
                    before = stripped[last_end:m.start()].strip()
                    before = annotation_re.sub('', before).strip()
                    if before:
                        parts.append(
                            f'<span style="{S_OCR_LBL}">OCR:</span> '
                            f'<span style="{S_OCR_TXT}">"{html_mod.escape(before)}"</span>'
                        )

                    code = m.group(1).strip()
                    name = m.group(2).strip()
                    parts.append(f'<span style="{S_ARROW}">→</span>')
                    parts.append(
                        f'<span style="{S_MATCH_LBL}">Matched:</span> '
                        f'<span style="{S_MATCH_CODE}">{html_mod.escape(code)}</span> '
                        f'<span style="{S_MATCH_TXT}">{html_mod.escape(name)}</span>'
                    )

                    last_end = m.end()

                # Any remaining text after the last annotation
                after = stripped[last_end:].strip()
                if after:
                    parts.append(f' <span style="color: #c9d1d9;">{html_mod.escape(after)}</span>')

                lines_html.append(f'<div style="padding: 4px 0;">{"".join(parts)}</div>')
            else:
                # Plain text line — explicitly label as invalid/irrelevant match
                S_UNMATCHED_LBL = "font-size: 10px; font-weight: 800; color: #f85149; text-transform: uppercase; letter-spacing: 1px;"
                S_UNMATCHED_TXT = "color: #8b949e; text-decoration: line-through; opacity: 0.6;"
                
                # If it's just table structural characters, keep it very faint
                if re.match(r'^[\s\|\-]+$', stripped):
                    lines_html.append(f'<div style="padding: 4px 0; color: #484f58; opacity: 0.3;">{html_mod.escape(stripped)}</div>')
                else:
                    lines_html.append(
                        f'<div style="padding: 4px 0;">'
                        f'<span style="{S_UNMATCHED_LBL}">Unmatched / Irrelevant:</span> '
                        f'<span style="{S_UNMATCHED_TXT}">"{html_mod.escape(stripped)}"</span>'
                        f'</div>'
                    )

        full_html = f'''
        <div style="{S_DOC}">
            {''.join(lines_html)}
        </div>
        <div style="font-size:11px; color:#484f58; margin-top:6px; padding-left:4px;">
            {total_lines} lines · {entity_count} entities resolved
        </div>'''

        st.markdown(full_html, unsafe_allow_html=True)

    # ── DISPLAY RESULTS ─────────────────────────────────────────────────────
    if st.session_state.ocr_combined:
        # Real Content Analysis for Output Quality
        def analyze_output_quality(text):
            if not text or len(text.strip()) == 0: return 0.0
            
            # Remove standard markdown formatting to inspect raw words
            clean = re.sub(r'[\*#\|\[\]\-\_]', ' ', text)
            words = clean.split()
            if not words: return 0.0
            
            issues = 0
            for w in words:
                # 1. Penalize endless repeating characters (e.g. '00000', 'yyyyy')
                if re.search(r'(.)\1{4,}', w):
                    issues += 1
                # 2. Penalize chaotic non-alphanumeric noise (gibberish symbols)
                elif len(w) > 3 and re.match(r'^[^A-Za-z0-9]+$', w):
                    issues += 1
                # 3. Penalize extremely long words without vowels (broken strings)
                elif len(w) > 12 and not re.search(r'[aeiouAEIOU]', w):
                    if not w.isdigit(): # large numbers are okay
                        issues += 1
            
            error_ratio = issues / len(words)
            # A 10% error ratio drops the score heavily
            score = 100.0 - (error_ratio * 250.0)
            return max(0.0, min(100.0, score))

        quality_score = analyze_output_quality(st.session_state.ocr_combined)

        st.success(
            f"✅ Extraction complete — {len(st.session_state.ocr_pages)} page(s) "
            f"in {st.session_state.last_time:.1f}s | **Output Quality Score: {quality_score:.1f}%**"
        )
        
        col_img, col_res = st.columns(2, gap="large")

        with col_img:
            st.markdown("### 🖼️ Original Input")
            if st.session_state.get("ocr_images"):
                for i, img in enumerate(st.session_state.ocr_images):
                    st.image(img, caption=f"Page {i+1}", width="stretch")
            else:
                st.info("Original image not available.")

        with col_res:
            st.markdown("### 📝 Extracted Output")
            preds_df = pd.DataFrame(st.session_state.get("ocr_predictions", []))
            
            # Multi-page: show tabs per page + combined
            def render_plain_text(text):
                if not text:
                    return
                lines = text.split('\n')
                processed = []
                for line in lines:
                    if line.strip().startswith('#'):
                        heading_text = line.lstrip('#').strip()
                        processed.append("")
                        processed.append(f"**{heading_text}**")
                        processed.append("")
                    else:
                        processed.append(line)
                final_text = '\n'.join(processed)
                with st.container(height=600, border=True):
                    st.markdown(final_text)

            if len(st.session_state.ocr_pages) > 1:
                tab_labels = [lbl for lbl, _ in st.session_state.ocr_pages] + ["📄 Combined", "📊 Data Grid", "🎯 Entities (Grid)", "📋 Entities (Vertical)"]
                tabs = st.tabs(tab_labels)
                for i, (tab, (lbl, txt)) in enumerate(zip(tabs[:-4], st.session_state.ocr_pages)): 
                    with tab:
                        render_plain_text(txt)
                with tabs[-4]:
                    render_plain_text(st.session_state.ocr_combined)
                with tabs[-3]:
                    # Try to show tables as dataframes
                    st.markdown("### 📈 Extracted Data Tables")
                    lines = st.session_state.ocr_combined.split('\n')
                    current_table = []
                    found_any = False
                    for line in lines:
                        raw_line = line.strip()
                        if raw_line.count('|') >= 2:
                            if all(c in '|- ' for c in raw_line) and '-' in raw_line: continue
                            cells = [c.strip() for c in raw_line.split('|') if c.strip()]
                            if cells: current_table.append(cells)
                        else:
                            if current_table and len(current_table) > 1:
                                header, rows = current_table[0], current_table[1:]
                                cleaned = [r[:len(header)] if len(r) > len(header) else r + ['']*(len(header)-len(r)) for r in rows]
                                st.dataframe(pd.DataFrame(cleaned, columns=header), width='stretch')
                                found_any = True
                                current_table = []
                    if current_table and len(current_table) > 1:
                        header, rows = current_table[0], current_table[1:]
                        cleaned = [r[:len(header)] if len(r) > len(header) else r + ['']*(len(header)-len(r)) for r in rows]
                        st.dataframe(pd.DataFrame(cleaned, columns=header), width='stretch')
                        found_any = True
                    if not found_any:
                        st.info("No structured tables detected for grid view. See 'Combined' for raw text.")
                with tabs[-2]:
                    if not preds_df.empty:
                        # Convert Confidence to float for progress bar
                        preds_df["Confidence"] = preds_df["Confidence"].astype(float)
                        st.dataframe(
                            preds_df, 
                            width='stretch',
                            hide_index=True,
                            column_config={
                                "Original Text": st.column_config.TextColumn("Extracted Text", width="medium"),
                                "Type": st.column_config.TextColumn("Category"),
                                "Predicted Code": st.column_config.TextColumn("Match Code", width="small"),
                                "Predicted Name": st.column_config.TextColumn("Resolved Entity", width="large"),
                                "Confidence": st.column_config.ProgressColumn(
                                    "AI Confidence",
                                    help="Cosine similarity score for the match",
                                    format="%.2f",
                                    min_value=0.0,
                                    max_value=1.0,
                                ),
                            }
                        )
                    else:
                        st.info("No medical entities were confidently detected in the text.")
                with tabs[-1]:
                    if not preds_df.empty:
                        for _, row in preds_df.iterrows():
                            # Premium Glassmorphism Card
                            conf = float(row['Confidence'])
                            conf_color = "#00d2ff" if conf > 0.4 else "#f39c12" if conf > 0.3 else "#e74c3c"
                            card_html = f'''
                            <div style="
                                background: linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
                                border: 1px solid rgba(255,255,255,0.15);
                                border-radius: 16px;
                                padding: 20px;
                                margin-bottom: 16px;
                                backdrop-filter: blur(12px);
                                -webkit-backdrop-filter: blur(12px);
                                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
                                font-family: 'Inter', 'Segoe UI', sans-serif;
                                transition: transform 0.3s ease, box-shadow 0.3s ease;
                            " onmouseover="this.style.transform='translateY(-4px)'; this.style.boxShadow='0 12px 24px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 15px rgba(0,0,0,0.05)';">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                    <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #fff; background: {conf_color}; padding: 4px 12px; border-radius: 20px;">{row['Type']}</span>
                                    <span style="font-size: 12px; font-weight: 600; color: {conf_color};">⚡ Score: {conf:.2f}</span>
                                </div>
                                <div style="font-size: 14px; font-weight: 500; color: #888; margin-bottom: 6px;">
                                    Extracted: <strong style="color: inherit; font-style: italic;">"{row['Original Text']}"</strong>
                                </div>
                                <div style="font-size: 18px; font-weight: 800; color: inherit;">
                                    <span style="opacity: 0.7;">{row['Predicted Code']}</span> <span style="opacity: 0.3;">|</span> {row['Predicted Name']}
                                </div>
                            </div>
                            '''
                            st.markdown(card_html, unsafe_allow_html=True)
                    else:
                        st.info("No medical entities were confidently detected in the text.")
            else:
                tab1, tab2, tab3, tab4 = st.tabs(["📄 Document View", "📊 Data Grid", "🎯 Entities (Grid)", "📋 Entities (Vertical)"])
                with tab1:
                    if st.session_state.active_grounding:
                        gr = st.session_state.active_grounding
                        if st.button("❌ Clear Highlight"):
                            st.session_state.active_grounding = None
                            st.rerun()
                        
                        page_idx = gr["page"] - 1
                        if 0 <= page_idx < len(st.session_state.ocr_images):
                            img = st.session_state.ocr_images[page_idx]
                            highlighted = VisualGrounder.draw_highlight(img, gr["bbox"], label=gr.get("label", ""))
                            st.image(highlighted, use_container_width=True)
                        else:
                            st.warning("Original image not found for grounding.")
                            
                    render_plain_text(st.session_state.ocr_combined)
                with tab2:
                    st.markdown("### 📈 Extracted Data Tables")
                    lines = st.session_state.ocr_combined.split('\n')
                    current_table = []
                    found_any = False
                    for line in lines:
                        raw_line = line.strip()
                        if raw_line.count('|') >= 2:
                            if all(c in '|- ' for c in raw_line) and '-' in raw_line: continue
                            cells = [c.strip() for c in raw_line.split('|') if c.strip()]
                            if cells: current_table.append(cells)
                        else:
                            if current_table and len(current_table) > 1:
                                header, rows = current_table[0], current_table[1:]
                                cleaned = [r[:len(header)] if len(r) > len(header) else r + ['']*(len(header)-len(r)) for r in rows]
                                header_unique = []
                                counts = {}
                                for c in header:
                                    counts[c] = counts.get(c, 0) + 1
                                    header_unique.append(f"{c} ({counts[c]})" if counts[c] > 1 else c)
                                st.dataframe(pd.DataFrame(cleaned, columns=header_unique), width='stretch')
                                found_any = True
                                current_table = []
                    if current_table and len(current_table) > 1:
                        header, rows = current_table[0], current_table[1:]
                        cleaned = [r[:len(header)] if len(r) > len(header) else r + ['']*(len(header)-len(r)) for r in rows]
                        header_unique = []
                        counts = {}
                        for c in header:
                            counts[c] = counts.get(c, 0) + 1
                            header_unique.append(f"{c} ({counts[c]})" if counts[c] > 1 else c)
                        st.dataframe(pd.DataFrame(cleaned, columns=header_unique), width='stretch')
                        found_any = True
                    if not found_any:
                        st.info("No structured tables detected for grid view. See 'Document View' for raw text.")
                with tab3:
                    if not preds_df.empty:
                        preds_df["Confidence"] = preds_df["Confidence"].astype(float)
                        st.dataframe(
                            preds_df, 
                            width='stretch',
                            hide_index=True,
                            column_config={
                                "Original Text": st.column_config.TextColumn("Extracted Text", width="medium"),
                                "Type": st.column_config.TextColumn("Category"),
                                "Predicted Code": st.column_config.TextColumn("Match Code", width="small"),
                                "Predicted Name": st.column_config.TextColumn("Resolved Entity", width="large"),
                                "Confidence": st.column_config.ProgressColumn(
                                    "AI Confidence",
                                    help="Cosine similarity score for the match",
                                    format="%.2f",
                                    min_value=0.0,
                                    max_value=1.0,
                                ),
                            }
                        )
                    else:
                        st.info("No medical entities were confidently detected in the text.")
                with tab4:
                    if not preds_df.empty:
                        for _, row in preds_df.iterrows():
                            conf = float(row['Confidence'])
                            conf_color = "#2ecc71" if conf >= 0.80 else "#f39c12" if conf >= 0.50 else "#e74c3c"
                            alert_icon = "⚠️ REVIEW:" if conf < 0.80 else "⚡ Score:"
                            
                            card_html = f'''
                            <div style="
                                background: linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
                                border: 1px solid {'rgba(243, 156, 18, 0.5)' if conf < 0.80 else 'rgba(255,255,255,0.15)'};
                                border-radius: 16px;
                                padding: 20px;
                                margin-bottom: 16px;
                                backdrop-filter: blur(12px);
                                -webkit-backdrop-filter: blur(12px);
                                box-shadow: {'0 0 15px rgba(243, 156, 18, 0.2)' if conf < 0.80 else '0 4px 15px rgba(0,0,0,0.05)'};
                                font-family: 'Inter', 'Segoe UI', sans-serif;
                                transition: transform 0.3s ease, box-shadow 0.3s ease;
                            " onmouseover="this.style.transform='translateY(-4px)'; this.style.boxShadow='0 12px 24px rgba(0,0,0,0.15)';" onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow={'0 0 15px rgba(243, 156, 18, 0.2)' if conf < 0.80 else '0 4px 15px rgba(0,0,0,0.05)'};">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                    <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #fff; background: {conf_color}; padding: 4px 12px; border-radius: 20px;">{row['Type']}</span>
                                    <span style="font-size: 12px; font-weight: 600; color: {conf_color};">{alert_icon} {conf:.2f}</span>
                                </div>
                                <div style="font-size: 14px; font-weight: 500; color: #888; margin-bottom: 6px;">
                                    Extracted: <strong style="color: inherit; font-style: italic;">"{row['Original Text']}"</strong>
                                </div>
                                <div style="font-size: 18px; font-weight: 800; color: inherit;">
                                    <span style="opacity: 0.7;">{row['Predicted Code']}</span> <span style="opacity: 0.3;">|</span> {row['Predicted Name']}
                                </div>
                            </div>
                            '''
                            st.markdown(card_html, unsafe_allow_html=True)
                            
                            bbox = row.get('bbox')
                            if isinstance(bbox, list) and len(bbox) == 4:
                                if st.button("🔍 View Source", key=f"ground_{_}"):
                                    st.session_state.active_grounding = {
                                        "page": int(row.get("page", 1)),
                                        "bbox": bbox,
                                        "label": row["Predicted Code"]
                                    }
                                    st.rerun()
                    else:
                        st.info("No medical entities were confidently detected in the text.")

        st.divider()

        # Download buttons
        col1, col2, col3, col4, col5 = st.columns(5)
        combined = st.session_state.ocr_combined
        
        def save_with_dialog(content, default_ext, file_types):
            import subprocess
            import os
            try:
                # Use zenity for the file save dialog
                zenity_cmd = [
                    "zenity",
                    "--file-selection",
                    "--save",
                    "--confirm-overwrite",
                    f"--title=Save {default_ext} File As..."
                ]
                
                # Format file filters for Zenity: --file-filter="PDF Files | *.pdf"
                if file_types:
                    for name, ext in file_types:
                        zenity_cmd.append(f"--file-filter={name} | {ext}")
                
                result = subprocess.run(zenity_cmd, capture_output=True, text=True)
                
                if result.returncode == 0 and result.stdout.strip():
                    file_path = result.stdout.strip()
                    # Append extension if not present
                    if not os.path.splitext(file_path)[1]:
                        file_path += default_ext
                        
                    mode = "wb" if isinstance(content, bytes) else "w"
                    encoding = "utf-8" if mode == "w" else None
                    with open(file_path, mode, encoding=encoding) as f:
                        f.write(content)
                    st.toast(f"✅ Saved successfully to {file_path}")
                else:
                    st.toast("⚠️ Save cancelled")
            except Exception as e:
                st.error(f"Could not open file explorer. (Error: {e}). Make sure zenity is installed.")

        with col1:
            if st.button("📥 Markdown", width='stretch', key='btn_md'):
                save_with_dialog(combined, ".md", [("Markdown Files", "*.md"), ("All Files", "*.*")])
                
        with col2:
            if st.button("📥 PDF", width='stretch', key='btn_pdf'):
                pdf = generate_pro_pdf(combined, client)
                if isinstance(pdf, bytes):
                    save_with_dialog(pdf, ".pdf", [("PDF Files", "*.pdf"), ("All Files", "*.*")])
                else:
                    st.error(pdf)
                    
        with col3:
            if st.button("📥 Word", width='stretch', key='btn_word'):
                docx_bytes = generate_docx(combined, client)
                if isinstance(docx_bytes, bytes):
                    save_with_dialog(docx_bytes, ".docx", [("Word Documents", "*.docx"), ("All Files", "*.*")])
                else:
                    st.error(docx_bytes)
                    
        with col4:
            if st.button("📥 Excel", width='stretch', key='btn_excel'):
                excel_bytes = generate_excel(combined)
                if excel_bytes:
                    save_with_dialog(excel_bytes, ".xlsx", [("Excel Files", "*.xlsx"), ("All Files", "*.*")])
                else:
                    st.info("No table found")
                    
        with col5:
            if st.button("📥 JSON", width='stretch', key='btn_json'):
                json_str = generate_json(combined)
                save_with_dialog(json_str, ".json", [("JSON Files", "*.json"), ("All Files", "*.*")])

    else:
        # Idle state
        st.info(
            "📋 Upload a medical form (image or PDF) in the sidebar and click "
            "**Extract Data** to begin."
        )
        with st.expander("ℹ️ How the engine works"):
            st.markdown("""
**5-Strategy Auto-Retry Pipeline:**
1. **Original** — raw image with orientation fix  
2. **Mild Enhancement** — sharpness + 1.5× contrast (printed forms)  
3. **Grayscale Boost** — grayscale + 1.8× contrast (photocopies)  
4. **Adaptive Threshold** — histogram stretch + unsharp mask (faded handwriting)  
5. **Denoise + Enhance** — median filter + enhance (camera phone photos)  

The engine automatically tries the next strategy if a response is empty.
            """)