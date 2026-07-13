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
import logging
import fitz          # PyMuPDF
import re
import math
import numpy as np
import cv2
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from openai import OpenAI
import base64
import markdown
from xhtml2pdf import pisa
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
import time
import pandas as pd
from core.config import settings
from modules.unified_resolver import resolve_entities_in_text
from modules.layout_detector import DocLayoutDetector
from modules.reading_order import ReadingOrderEngine
from modules.region_ocr import AsyncRegionOCR
from modules.table_extractor import TableExtractor
from modules.medical_corrector import MedicalCorrector
from modules.confidence_engine import ConfidenceEngine

# Bounded timeout (SDK default is 600s) — a hung/overloaded vLLM server should
# fail one call fast and let Celery's retry policy handle it, not silently
# block a worker for up to 10 minutes per call.
# Always settings.VLLM_BASE_URL, never a hardcoded "localhost:8700" — a
# hardcoded host string here silently breaks in any containerized deployment.
client = OpenAI(base_url=settings.VLLM_BASE_URL, api_key="EMPTY", timeout=90.0)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 0.  PAGE ORIENTATION DETECTION (0/90/180/270)
# ---------------------------------------------------------------------------
def detect_page_orientation(img: Image.Image) -> int:
    """
    Detects the rotation (0/90/180/270, clockwise) needed to make a page
    upright, run once per page before the fine-angle deskew strategies below
    (which only correct small ±0.5-15 degree skew, not full rotations).

    Two-step, since a single metric can't do this alone:
      1. Row-projection-variance picks the axis (portrait {0,180} vs
         landscape {90,270}) — properly oriented text has strong periodic
         horizontal line-banding that a 90-degree rotation destroys.
      2. Row-projection variance looks nearly identical for 0 vs 180 (upside
         -down text has the same line-banding pattern), so those two are
         disambiguated with a real OCR-confidence probe on a center crop —
         whichever orientation the model reads with higher confidence wins.
         This deliberately uses the primary vLLM engine (not TrOCR): tested
         against a real scanned page, TrOCR's confidence didn't track actual
         orientation at all (0.34 for the correct upright crop vs 0.37 for
         the wrong upside-down one — noise), whereas vLLM scored the correct
         orientation clearly higher (0.68 vs 0.42) and produced coherent text
         only for the right one. Costs two small vLLM calls per page.

    The confidence probe is a single noisy model signal, not a certainty. For
    the 0-vs-180 case it was reliable across every real document tested (a
    consistent, clear confidence margin favoring the correct upright read).
    For the 90-vs-270 case it was NOT: tested against two different real
    documents it confidently favored the *wrong* member of the pair both
    times (not just a low-margin coin flip the margin gate below would
    catch) — the direction of a quarter-turn is apparently harder for this
    signal to judge reliably than a half-turn is. Rather than ship something
    that can confidently flip an already-correct page 90 degrees the wrong
    way (actively worse than the pre-Phase-2 baseline of not rotating at
    all), quarter-turn axis pages are intentionally left uncorrected here —
    flagged via a log line for visibility, not silently guessed. Only the
    half-turn (0/180) correction is applied automatically. Reliably picking
    quarter-turn direction is left as follow-up work (e.g. an actual OSD
    model) rather than shipped as a guess.
    """
    arr = np.array(img.convert("L"))

    def _row_projection_variance(rotation_deg: int) -> float:
        rotated = np.rot90(arr, k=rotation_deg // 90)
        return float(np.var(rotated.sum(axis=1)))

    portrait_axis = _row_projection_variance(0) >= _row_projection_variance(90)
    if not portrait_axis:
        logger.info(
            "Page appears rotated a quarter-turn (90/270) but the direction "
            "isn't reliably determined by the current confidence probe — "
            "leaving uncorrected rather than guessing."
        )
        return 0
    candidates = (0, 180)

    w, h = img.size
    crop_w, crop_h = min(w, 700), min(h, 300)
    cx, cy = w // 2, h // 2
    center_crop = img.crop(
        (cx - crop_w // 2, cy - crop_h // 2, cx + crop_w // 2, cy + crop_h // 2)
    )

    scores = {}
    for rot in candidates:
        test_img = center_crop.rotate(-rot, expand=True) if rot else center_crop
        scores[rot] = _vllm_orientation_confidence(test_img)

    ranked = sorted(candidates, key=lambda r: scores[r], reverse=True)
    winner, runner_up = ranked[0], ranked[1]
    MIN_ABSOLUTE_CONFIDENCE = 0.5
    MIN_MARGIN_RATIO = 1.3  # winner must be a clearly better read, not a coin flip
    if scores[winner] < MIN_ABSOLUTE_CONFIDENCE or scores[winner] < MIN_MARGIN_RATIO * max(scores[runner_up], 1e-6):
        return 0
    return winner


def _vllm_orientation_confidence(img: Image.Image) -> float:
    """Mean per-token log-prob (exponentiated) of a short vLLM read of `img`,
    used only to compare orientation candidates against each other.

    Deliberately creates its own client per call rather than using the
    module-level `client` above: that client is constructed at import time,
    and Celery's prefork worker model forks child processes *after* the
    module (and its at-import-time HTTP client/connection pool) is loaded —
    reusing a pre-fork httpx client from a forked child is a known way to
    deadlock silently. Confirmed by reproduction: page tasks hung for
    ~10 minutes (the OpenAI SDK's default request timeout) with zero
    progress the first time this code path ran under the real Celery worker,
    vanishing once each call got its own client instead of sharing the
    pre-fork one.
    """
    try:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        local_client = OpenAI(base_url=settings.VLLM_BASE_URL, api_key="EMPTY", timeout=30.0)
        resp = local_client.chat.completions.create(
            model="qwen2.5-vl-7b",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read the text in this image exactly as written."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            temperature=0,
            max_tokens=40,
            logprobs=True,
            top_logprobs=1,
        )
        content = resp.choices[0].logprobs.content if resp.choices[0].logprobs else None
        if not content:
            return 0.0
        return float(np.exp(np.mean([t.logprob for t in content])))
    except Exception as e:
        logger.warning(f"Orientation confidence probe failed: {e}")
        return 0.0


def apply_orientation(img: Image.Image) -> Image.Image:
    """Detects and corrects full-rotation page orientation. No-op (cheap) for
    the common already-upright case; returns the input unchanged then."""
    rotation = detect_page_orientation(img)
    if rotation == 0:
        return img
    logger.info(f"Correcting page rotation by {rotation} degrees")
    return img.rotate(-rotation, expand=True)


# ---------------------------------------------------------------------------
# 0b. BLANK PAGE DETECTION
# ---------------------------------------------------------------------------
def is_blank_page(img: Image.Image, ink_ratio_threshold: float = 0.01) -> bool:
    """
    Cheap (no model call) check for near-empty separator/blank pages, common
    in real hospital scan batches. Thresholds against the page's own median
    background level (works for off-white/gray scans, not just pure white)
    and measures what fraction of pixels are meaningfully darker than that.

    Tuned against real documents in uploads/: genuine content pages measured
    6-17% ink coverage; a synthetic blank page (with scanner noise) measured
    0%, and a near-blank page with only a small stamp/mark measured 0.4% —
    both comfortably under this threshold, with a wide margin to real content.
    """
    gray = np.array(img.convert("L"), dtype=np.float32)
    bg_level = np.median(gray)
    ink_mask = gray < (bg_level - 30)
    ink_ratio = float(ink_mask.mean())
    return ink_ratio < ink_ratio_threshold

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

def _deskew_cv(img_bgr: np.ndarray) -> np.ndarray:
    """Hough-line-based skew detection + rotation correction."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)
    if lines is None:
        return img_bgr
    # reshape(-1, 4), not lines[:, 0]: HoughLinesP's output shape is (N, 1, 4)
    # on some opencv-python-headless versions and (N, 4) on others (hit this
    # for real — a fresh `pip install` picked up a newer version than the
    # long-running host venv had, and lines[:, 0] silently returned scalars
    # instead of (x1,y1,x2,y2) tuples on the (N, 4) shape, breaking deskew
    # for every image). reshape(-1, 4) is correct for both.
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for (x1, y1, x2, y2) in lines.reshape(-1, 4)]
    if not angles:
        return img_bgr
    median_angle = np.median(angles)
    # Only correct noticeable skew; skip near-0 (already straight) and near-90 (rotated page, different problem).
    if not (0.5 < abs(median_angle) < 15):
        return img_bgr
    h, w = img_bgr.shape[:2]
    m = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
    return cv2.warpAffine(img_bgr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def strategy_deskew_clahe_denoise(img: Image.Image) -> Image.Image:
    """Strategy 5 — Deskew + CLAHE contrast + non-local-means denoise. For crooked
    camera photos / fax-quality scans where the other strategies leave visible tilt
    or uneven lighting."""
    img = ImageOps.exif_transpose(img)
    img = _upscale_if_small(img)
    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    bgr = _deskew_cv(bgr)

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    bgr = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    bgr = cv2.fastNlMeansDenoisingColored(bgr, None, 10, 10, 7, 21)

    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


STRATEGIES = [
    ("Original",              strategy_original),
    ("Mild Enhancement",      strategy_mild_enhance),
    ("Grayscale Boost",       strategy_grayscale_boost),
    ("Adaptive Threshold",    strategy_adaptive_threshold),
    ("Denoise + Enhance",     strategy_denoised),
    ("Deskew + CLAHE",        strategy_deskew_clahe_denoise),
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
def load_pdf_page_count(file_bytes: bytes) -> int:
    """Page count without rendering — cheap, used to size the Celery chord fan-out."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    count = len(doc)
    doc.close()
    return count


def load_pdf_page(file_bytes: bytes, page_idx: int) -> Image.Image:
    """Render a single PDF page as a PIL image at 300 DPI. Used by the per-page
    Celery task so a worker only ever holds one rendered page in memory at a
    time, regardless of document length (contrast with load_pdf_pages below,
    which is a convenience for small/synchronous callers only)."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc.load_page(page_idx)
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    img.load()  # decode before closing the underlying doc/buffer
    doc.close()
    return img


def load_pdf_page_thumbnail(file_bytes: bytes, page_idx: int, dpi: int = 72) -> Image.Image:
    """Cheap low-DPI render of a single page, used only for perceptual-hash
    duplicate detection at dispatch time (see workers/celery_app.py) — avoids
    paying full 300 DPI render cost twice (once to hash, once to OCR) for
    every page just to detect the minority that are duplicates."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc.load_page(page_idx)
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    img.load()
    doc.close()
    return img


def page_phash(img: Image.Image) -> str:
    """Perceptual hash for near-duplicate page detection (tolerant to minor
    re-scan/re-compress differences that an exact byte/MD5 hash would miss)."""
    import imagehash
    return str(imagehash.phash(img))


def load_pdf_pages(file_bytes: bytes, max_pages: int | None = None) -> list[Image.Image]:
    """Extract pages from a PDF as PIL images at 300 DPI (Balanced for Qwen).

    Loads every requested page into memory at once — fine for the synchronous/
    single-process callers (tests, small documents) but NOT what the Celery OCR
    pipeline uses for large PDFs; that path calls load_pdf_page_count/
    load_pdf_page one page at a time instead. No page cap by default."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total = len(doc) if max_pages is None else min(len(doc), max_pages)
    pages = []
    for i in range(total):
        page = doc.load_page(i)
        pix  = page.get_pixmap(dpi=300)
        pages.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    doc.close()
    return pages

# ---------------------------------------------------------------------------
# 5.  EXPORT GENERATORS  (PDF / DOCX)
# ---------------------------------------------------------------------------
def generate_pro_pdf(md_text: str, client_name: str) -> bytes | str:
    try:
        safe = re.sub(r'<\|.*?\|>', '', md_text)
        safe = safe.replace('<', '&lt;').replace('>', '&gt;')
        safe = safe.replace('\u2022', '*').replace('\u2713', '[x]')
        html_body = markdown.markdown(safe, extensions=['tables', 'nl2br'])
        orientation = "landscape" if "| S.No |" in md_text else "portrait"
        
        pdf_css = f"""
        @page {{ size: A4 {orientation}; margin: 1.8cm 1.5cm 1.8cm 1.5cm; }}
        body {{ font-family: Arial, Helvetica, sans-serif; font-size: 10px; color: #222; line-height: 1.5; }}
        .cover {{ text-align: center; padding: 30px 0 20px; border-bottom: 3px solid #1a5276; margin-bottom: 20px; }}
        .cover h1 {{ font-size: 18px; color: #1a5276; margin: 0 0 4px; letter-spacing: 1px; }}
        .cover h2 {{ font-size: 13px; color: #444; margin: 0 0 16px; font-weight: normal; }}
        .cover .meta-box {{ display: inline-block; background: #eaf2ff; border: 1px solid #1a5276; border-radius: 6px; padding: 10px 30px; font-size: 11px; color: #1a5276; font-weight: bold; }}
        h1 {{ font-size: 16px; color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 3px; margin-top: 18px; margin-bottom: 6px; }}
        h2 {{ font-size: 13px; color: #1a5276; background: #eaf2ff; padding: 4px 8px; border-left: 4px solid #1a5276; margin-top: 14px; margin-bottom: 6px; }}
        h3 {{ font-size: 11px; color: #1a5276; margin-top: 10px; margin-bottom: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 8px 0 12px; font-size: 9.5px; page-break-inside: avoid; }}
        th {{ background: #1a5276; color: white; padding: 5px 7px; text-align: left; font-weight: bold; }}
        td {{ border: 1px solid #bbb; padding: 4px 7px; vertical-align: top; }}
        tr:nth-child(even) td {{ background: #f4f8ff; }}
        p {{ margin: 3px 0; }}
        ul {{ margin: 3px 0 6px 16px; padding: 0; }}
        li {{ margin: 1px 0; }}
        strong {{ color: #1a5276; }}
        .footer-note {{ font-size: 8px; color: #888; text-align: center; margin-top: 20px; border-top: 1px solid #ddd; padding-top: 6px; }}
        """

        cover = f"""
        <div class="cover">
            <h1>GREAT EASTERN MEDICAL SCHOOL &amp; HOSPITAL</h1>
            <h2>Promoted by Aditya Educational Society</h2>
            <div class="meta-box">
                OCR EXTRACTION REPORT<br/>
                <span style="font-size:13px">{client_name}</span>
            </div>
            <p style="font-size:9px;color:#888;margin-top:12px">
                Generated on {time.strftime('%d %B %Y at %I:%M %p')} &nbsp;|&nbsp; Confidential — For Medical Records Only
            </p>
        </div>
        """

        footer = """
        <div class="footer-note">
            This extraction was auto-generated from scanned case file documents using Keppler AI (OCR + LLM).
            Verify all clinical data against original records before use.
        </div>
        """
        
        html = f"<html><head><meta charset='utf-8'/><style>{pdf_css}</style></head><body>{cover}{html_body}{footer}</body></html>"
        out = io.BytesIO()
        status = pisa.CreatePDF(io.StringIO(html), dest=out, encoding="utf-8")
        return out.getvalue() if not status.err else f"PDF Error: {status.err}"
    except Exception as e:
        return f"PDF Error: {e}"

def generate_docx(md_text: str, client_name: str) -> bytes | str:
    try:
        doc = Document()
        
        # Page margins
        for section in doc.sections:
            section.top_margin    = Inches(0.8)
            section.bottom_margin = Inches(0.8)
            section.left_margin   = Inches(1.0)
            section.right_margin  = Inches(1.0)
            
        # Cover heading
        title = doc.add_heading("GREAT EASTERN MEDICAL SCHOOL & HOSPITAL", 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.runs[0].font.color.rgb = RGBColor(0x1a, 0x52, 0x76)
        
        sub = doc.add_paragraph("OCR EXTRACTION REPORT")
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.runs[0].bold = True
        sub.runs[0].font.size = Pt(13)
        
        info = doc.add_paragraph(f"{client_name}")
        info.alignment = WD_ALIGN_PARAGRAPH.CENTER
        info.runs[0].font.size = Pt(10)
        
        date_p = doc.add_paragraph(
            f"Generated: {time.strftime('%d %B %Y at %I:%M %p')} | Confidential"
        )
        date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        date_p.runs[0].font.size = Pt(8)
        date_p.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        doc.add_paragraph()
        
        clean = re.sub(r'<\|.*?\|>', '', md_text)
        in_table = False
        table    = None
        
        for line in clean.split('\n'):
            line = line.strip()
            if not line:
                if not in_table:
                    doc.add_paragraph()
                continue
            
            if line.startswith('## '):
                in_table = False
                h = doc.add_heading(line[3:], level=1)
                h.runs[0].font.color.rgb = RGBColor(0x1a, 0x52, 0x76)
            elif line.startswith('### '):
                in_table = False
                h = doc.add_heading(line[4:], level=2)
                h.runs[0].font.color.rgb = RGBColor(0x1a, 0x52, 0x76)
            elif line.startswith('- ') or line.startswith('* '):
                in_table = False
                p = doc.add_paragraph(style='List Bullet')
                text = line[2:].strip()
                parts = re.split(r'\*\*(.+?)\*\*', text)
                for i, part in enumerate(parts):
                    run = p.add_run(part)
                    if i % 2 == 1: run.bold = True
            elif line.startswith('|'):
                if '---' in line:
                    continue
                cells = [c.strip() for c in line.strip('|').split('|')]
                cells = [c for c in cells if c]
                if not cells:
                    continue
                if not in_table:
                    table = doc.add_table(rows=1, cols=len(cells))
                    table.style = 'Table Grid'
                    hdr = table.rows[0]
                    for i, c in enumerate(cells):
                        cell = hdr.cells[i]
                        cell.text = c
                        run = cell.paragraphs[0].runs[0] if cell.paragraphs[0].runs else cell.paragraphs[0].add_run(c)
                        run.bold = True
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        cell._tc.get_or_add_tcPr()
                    in_table = True
                else:
                    row = table.add_row()
                    for i, c in enumerate(cells):
                        if i < len(row.cells):
                            row.cells[i].text = c
            elif line.startswith('---'):
                in_table = False
            else:
                in_table = False
                p = doc.add_paragraph()
                parts = re.split(r'\*\*(.+?)\*\*', line)
                for i, part in enumerate(parts):
                    run = p.add_run(part)
                    if i % 2 == 1: run.bold = True
                    run.font.size = Pt(10)
        
        doc.add_paragraph()
        note = doc.add_paragraph(
            "⚠ This extraction was auto-generated by Keppler AI from scanned case file documents. "
            "Verify all clinical data against original records before use."
        )
        note.runs[0].font.size = Pt(8)
        note.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        
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
def process_single_page(raw_img: Image.Image, label: str, idx: int, total_pages: int,
                         client: str, progress_cb=None) -> dict:
    """
    Run the full single-page pipeline (layout detection -> reading order ->
    async region OCR -> table extraction -> medical correction -> confidence
    fusion) on one already-loaded page image.

    This is the unit of work the Celery OCR chord fans out per-page (see
    workers/celery_app.py) so a multi-thousand-page document is processed as
    many independent, retryable tasks across workers instead of one long
    sequential loop in a single process. `run_ocr_pipeline` below is a thin
    sequential wrapper around this for direct/synchronous callers.

    progress_cb, if given, is called with a float in [0, 1] scoped to *this
    page only* (0.0 at start, ~0.85 once correction is queued).

    Returns {"label": str, "text": str, "predictions": list[dict]}.
    """
    if progress_cb: progress_cb(0.02)

    raw_img = apply_orientation(raw_img)

    if progress_cb: progress_cb(0.05)

    page_info = f"{label} of {total_pages}" if total_pages > 1 else ""
    prompt = build_prompt(client, page_info)

    # Layout Detection Layer
    if progress_cb: progress_cb(0.15)
    detector = DocLayoutDetector()
    regions = detector.detect_regions(raw_img)

    # Reading Order Reconstruction
    if progress_cb: progress_cb(0.30)
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
    if progress_cb: progress_cb(0.45)
    async_ocr = AsyncRegionOCR(max_concurrent=5, model_name="qwen2.5-vl-7b")
    table_extractor = TableExtractor()

    structured_results = asyncio.run(async_ocr.process_page_regions(
        regions=non_table_regions,
        raw_img=raw_img,
        page_num=idx + 1,
        prompt=prompt
    ))

    # Table Extraction (TATR)
    if progress_cb: progress_cb(0.65)
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
    page_preds = []

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
                # Grounding (Phase 5): trace which OCR engine actually produced
                # this region's text and how confident that read was, separate
                # from the entity-resolution confidence above.
                pred["ocr_confidence"] = res.get("ocr_confidence", 0.0)
                pred["ocr_model_used"] = res.get("ocr_model_used", "unknown")
                pred["region_id"] = res.get("region_id", "")
                pred["region_type"] = res.get("region_type", "Unknown")
                page_preds.append(pred)

    if success_count > 0:
        final_page_text = "\n\n".join(page_extracted_parts)

        # Medical Correction Layer
        if progress_cb: progress_cb(0.85)
        med_corrector = MedicalCorrector()
        correction_result = asyncio.run(med_corrector.correct_text(final_page_text))

        corrected_page_text = correction_result["corrected_text"]

        for c in correction_result.get("corrections", []):
            sem_conf = float(c.get('confidence', 0.0))
            final_conf = ConfidenceEngine.calculate_final_confidence(1.0, sem_conf)
            page_preds.append({
                "Original Text": c["original"],
                "Predicted Code": "CORRECTION",
                "Predicted Name": c["corrected"],
                "Type": "Medical Typo",
                "Confidence": f"{final_conf:.2f}",
                "page": idx + 1,
                "bbox": [],
                "ocr_confidence": sem_conf,
                "ocr_model_used": "medical_corrector",
                "region_id": "",
                "region_type": "Correction",
            })

        page_text = corrected_page_text
    else:
        page_text = f"*[{label}: Extraction failed — content too short or empty]*"

    return {"label": label, "text": page_text, "predictions": page_preds}


def run_ocr_pipeline(pages: list[Image.Image], client: str, progress_cb=None) -> dict:
    """
    Sequential wrapper around process_single_page for direct/synchronous callers
    (tests, small documents processed in-process). The distributed path
    (workers/celery_app.py) calls process_single_page directly, one page per
    Celery task, instead of using this loop.

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

        def page_progress_cb(p, base_pct=base_pct, page_slice=page_slice):
            if progress_cb: progress_cb(base_pct + p * page_slice)

        result = process_single_page(raw_img, label, idx, total_pages, client, progress_cb=page_progress_cb)
        all_pages_text.append((result["label"], result["text"]))
        all_preds.extend(result["predictions"])

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

