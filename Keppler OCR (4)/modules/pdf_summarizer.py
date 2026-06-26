# modules/pdf_summarizer.py  — Medical Case Summary Engine v1.0
"""
Reads a multi-page hospital case file PDF (images or text),
sends each page through the vision model (qwen2.5vl:32b),
builds a structured clinical summary, and exports it as a
professionally styled 4-5 page PDF, DOCX, or Markdown file.
"""

import streamlit as st
import fitz          # PyMuPDF
from openai import OpenAI
import base64
import io
import re
import time
import json
import markdown as md_lib
from PIL import Image
from xhtml2pdf import pisa
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
import concurrent.futures
from streamlit.runtime.scriptrunner import add_script_run_ctx

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
OCR_MODEL     = "qwen2.5-vl-7b"   # vision model for reading scanned pages
SUMMARY_MODEL = "qwen2.5-vl-7b"      # text model for summarising
MAX_IMG_DIM   = 1024               # High resolution image extraction
JPEG_QUALITY  = 75

client = OpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Extract text from each PDF page using vision model
# ─────────────────────────────────────────────────────────────────────────────

def _page_to_image_bytes(page: fitz.Page) -> bytes:
    mat = fitz.Matrix(2.0, 2.0)           # 2x zoom = ~150 DPI effective
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    w, h = img.size
    if max(w, h) > MAX_IMG_DIM:
        scale = MAX_IMG_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def extract_page_text(page_img_bytes: bytes, page_num: int) -> str:
    prompt = (
        f"This is page {page_num} of a hospital medical case file. "
        "Extract ALL text exactly as written including handwritten notes, "
        "table values, checkboxes (mark as [x] or [ ]), dates, vitals, "
        "drug names and doses. Output plain text only, no commentary."
    )
    try:
        base64_img = base64.b64encode(page_img_bytes).decode('utf-8')
        resp = client.chat.completions.create(
            model=OCR_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            temperature=0,
            max_tokens=1024,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[Page {page_num} extraction failed: {e}]"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Enterprise Summarization Pipeline
# ─────────────────────────────────────────────────────────────────────────────

# (Replaced old generate_structured_summary with modules.summarizer package)



# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Export to PDF (styled, 4-5 pages)
# ─────────────────────────────────────────────────────────────────────────────

PDF_CSS = """
@page {
    size: A4 portrait;
    margin: 1.8cm 1.5cm 1.8cm 1.5cm;
}
body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10px;
    color: #222;
    line-height: 1.5;
}
.cover {
    text-align: center;
    padding: 30px 0 20px;
    border-bottom: 3px solid #1a5276;
    margin-bottom: 20px;
}
.cover h1 {
    font-size: 18px;
    color: #1a5276;
    margin: 0 0 4px;
    letter-spacing: 1px;
}
.cover h2 {
    font-size: 13px;
    color: #444;
    margin: 0 0 16px;
    font-weight: normal;
}
.cover .meta-box {
    display: inline-block;
    background: #eaf2ff;
    border: 1px solid #1a5276;
    border-radius: 6px;
    padding: 10px 30px;
    font-size: 11px;
    color: #1a5276;
    font-weight: bold;
}
h1 { font-size: 16px; color: #1a5276; border-bottom: 2px solid #1a5276;
     padding-bottom: 3px; margin-top: 18px; margin-bottom: 6px; }
h2 { font-size: 13px; color: #1a5276; background: #eaf2ff;
     padding: 4px 8px; border-left: 4px solid #1a5276;
     margin-top: 14px; margin-bottom: 6px; }
h3 { font-size: 11px; color: #1a5276; margin-top: 10px; margin-bottom: 4px; }
table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 12px;
    font-size: 9.5px;
    page-break-inside: avoid;
}
th {
    background: #1a5276;
    color: white;
    padding: 5px 7px;
    text-align: left;
    font-weight: bold;
}
td {
    border: 1px solid #bbb;
    padding: 4px 7px;
    vertical-align: top;
}
tr:nth-child(even) td { background: #f4f8ff; }
p { margin: 3px 0; }
ul { margin: 3px 0 6px 16px; padding: 0; }
li { margin: 1px 0; }
strong { color: #1a5276; }
.section-divider {
    border: none;
    border-top: 1px dashed #aaa;
    margin: 10px 0;
}
.footer-note {
    font-size: 8px;
    color: #888;
    text-align: center;
    margin-top: 20px;
    border-top: 1px solid #ddd;
    padding-top: 6px;
}
"""


def _md_to_html(summary_md: str, patient_name: str, ip_no: str) -> str:
    safe = re.sub(r'<\|.*?\|>', '', summary_md)
    body_html = md_lib.markdown(safe, extensions=['tables', 'nl2br'])

    cover = f"""
    <div class="cover">
        <h1>GREAT EASTERN MEDICAL SCHOOL &amp; HOSPITAL</h1>
        <h2>Promoted by Aditya Educational Society</h2>
        <div class="meta-box">
            PATIENT CASE SUMMARY<br/>
            <span style="font-size:13px">{patient_name}</span><br/>
            IP No: {ip_no}
        </div>
        <p style="font-size:9px;color:#888;margin-top:12px">
            Generated on {time.strftime('%d %B %Y at %I:%M %p')} &nbsp;|&nbsp; Confidential — For Medical Records Only
        </p>
    </div>
    """

    footer = """
    <div class="footer-note">
        This summary was auto-generated from scanned case file documents using Keppler AI (OCR + LLM).
        Verify all clinical data against original records before use.
    </div>
    """

    return f"""<html>
<head><meta charset="utf-8"/>
<style>{PDF_CSS}</style>
</head>
<body>
{cover}
{body_html}
{footer}
</body></html>"""


def generate_summary_pdf(summary_md: str, patient_name: str, ip_no: str) -> bytes | str:
    try:
        html = _md_to_html(summary_md, patient_name, ip_no)
        out = io.BytesIO()
        status = pisa.CreatePDF(io.StringIO(html), dest=out, encoding="utf-8")
        return out.getvalue() if not status.err else f"PDF Error: {status.err}"
    except Exception as e:
        return f"PDF Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Export to DOCX (styled Word document)
# ─────────────────────────────────────────────────────────────────────────────

def generate_summary_docx(summary_md: str, patient_name: str, ip_no: str) -> bytes | str:
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

        sub = doc.add_paragraph("PATIENT CASE SUMMARY")
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.runs[0].bold = True
        sub.runs[0].font.size = Pt(13)

        info = doc.add_paragraph(f"Patient: {patient_name}   |   IP No: {ip_no}")
        info.alignment = WD_ALIGN_PARAGRAPH.CENTER
        info.runs[0].font.size = Pt(10)

        date_p = doc.add_paragraph(
            f"Generated: {time.strftime('%d %B %Y at %I:%M %p')} | Confidential"
        )
        date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        date_p.runs[0].font.size = Pt(8)
        date_p.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        doc.add_paragraph()

        # Parse and write markdown sections
        clean = re.sub(r'<\|.*?\|>', '', summary_md)
        in_table = False
        table_obj = None

        for line in clean.split('\n'):
            line = line.rstrip()

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
                # Handle **bold** inline
                parts = re.split(r'\*\*(.+?)\*\*', text)
                for i, part in enumerate(parts):
                    run = p.add_run(part)
                    if i % 2 == 1:
                        run.bold = True

            elif line.startswith('|'):
                if '---' in line:
                    continue
                cells = [c.strip() for c in line.strip('|').split('|')]
                cells = [c for c in cells if c]
                if not cells:
                    continue
                if not in_table:
                    table_obj = doc.add_table(rows=1, cols=len(cells))
                    table_obj.style = 'Table Grid'
                    hdr = table_obj.rows[0]
                    for i, c in enumerate(cells):
                        cell = hdr.cells[i]
                        cell.text = c
                        run = cell.paragraphs[0].runs[0] if cell.paragraphs[0].runs else cell.paragraphs[0].add_run(c)
                        run.bold = True
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        cell._tc.get_or_add_tcPr()
                    in_table = True
                else:
                    row = table_obj.add_row()
                    for i, c in enumerate(cells):
                        if i < len(row.cells):
                            row.cells[i].text = c

            elif line.strip() == '' or line.startswith('---'):
                in_table = False
                if line.strip() == '':
                    doc.add_paragraph()

            else:
                in_table = False
                p = doc.add_paragraph()
                parts = re.split(r'\*\*(.+?)\*\*', line)
                for i, part in enumerate(parts):
                    run = p.add_run(part)
                    if i % 2 == 1:
                        run.bold = True
                    run.font.size = Pt(10)

        # Footer note
        doc.add_paragraph()
        note = doc.add_paragraph(
            "⚠ This summary was auto-generated by Keppler AI from scanned case file documents. "
            "Verify all clinical data against original records before use."
        )
        note.runs[0].font.size = Pt(8)
        note.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()
    except Exception as e:
        return f"DOCX Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

def _extract_patient_meta(summary_md: str) -> tuple[str, str]:
    """Try to pull patient name and IP number from the summary text."""
    name = "Patient"
    ip   = "—"
    name_m = re.search(r'(?:name|patient)[:\s*_]+([A-Z][A-Z\s]+)', summary_md, re.I)
    ip_m   = re.search(r'IP\s*(?:No|Number)?[:\s._]+([A-Z0-9]+)', summary_md, re.I)
    if name_m:
        name = name_m.group(1).strip().title()
    if ip_m:
        ip = ip_m.group(1).strip()
    return name, ip


def render_pdf_summarizer():
    st.header("📋 Medical Case File Summarizer")
    st.caption("Upload a hospital case file PDF → Get a structured 4–5 page clinical summary → Download as PDF / Word / Markdown")

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 📤 Upload Case File")
        uploaded = st.file_uploader(
            "Upload PDF (up to 50 pages)",
            type=["pdf"],
            key="case_summary_uploader"
        )
        st.divider()
        st.markdown("**⚙️ Settings**")
        show_raw = st.toggle("Show raw OCR text per page", value=False)
        clear_cache = st.toggle("Force fresh restart (clear cache)", value=False)
        st.caption("Model: qwen2.5vl:32b (OCR) + qwen2.5:7b (Summary)")
        st.divider()
        run_btn = st.button("🚀 Generate Summary", type="primary", width="stretch",
                            disabled=(uploaded is None))

    # ── Previous result (show without re-running) ─────────────────────────
    if "case_summary_md" in st.session_state and not run_btn:
        _render_results(
            st.session_state["case_summary_md"],
            st.session_state["case_summary_pages"],
            st.session_state["case_summary_filename"],
            show_raw
        )
        return

    if not uploaded:
        st.info("👈 Upload a hospital case file PDF from the sidebar to get started.")
        _show_sample_note()
        return

    if not run_btn:
        st.info("👈 Click **Generate Summary** in the sidebar to begin.")
        return

    # ── PIPELINE ──────────────────────────────────────────────────────────────
    pdf_bytes = uploaded.read()

    # Step 1: Open PDF and count pages
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    st.success(f"✅ Loaded **{total_pages} pages** from `{uploaded.name}`")

    # Step 2: OCR each page
    st.markdown("### 🔍 Step 1 — Reading each page...")
    page_texts = {}
    ocr_progress = st.progress(0, text="Starting OCR...")

    images_to_process = {}
    for i in range(total_pages):
        page = doc[i]
        images_to_process[i + 1] = _page_to_image_bytes(page)
    doc.close()

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for pg_num, img_bytes in images_to_process.items():
            future = executor.submit(extract_page_text, img_bytes, pg_num)
            add_script_run_ctx(future)
            futures[future] = pg_num

        for future in concurrent.futures.as_completed(futures):
            pg_num = futures[future]
            text = future.result()
            page_texts[pg_num] = text
            completed += 1
            ocr_progress.progress(
                completed / total_pages,
                text=f"📖 Reading pages concurrently... ({completed}/{total_pages})"
            )

    ocr_progress.progress(1.0, text="✅ All pages read!")
    time.sleep(0.3)
    ocr_progress.empty()

    # Step 3: Map-Reduce Enterprise Summarization
    st.markdown("### 🧠 Step 2 — Building Enterprise Structured Summary...")
    
    page_strings = [page_texts[pg] for pg in sorted(page_texts.keys())]
    
    from modules.summarizer.chunker import TextChunker
    from modules.summarizer.hierarchical import HierarchicalSummarizer
    from modules.summarizer.aggregator import MasterAggregator
    
    chunker = TextChunker(pages=page_strings, chunk_size=1, document_id=uploaded.name)
    
    if clear_cache:
        chunker.clear_cache()
        
    hierarchical = HierarchicalSummarizer(model_name=SUMMARY_MODEL)
    
    sum_progress = st.progress(0, text="Summarizing chunks (Map-Reduce)...")
    
    def update_progress(current, total):
        sum_progress.progress(current / total, text=f"Summarizing chunk {current} of {total}...")
        
    master_data = hierarchical.process_chunks(chunker, progress_callback=update_progress)
    sum_progress.progress(1.0, text="✅ All chunks summarized!")
    time.sleep(0.3)
    sum_progress.empty()
    
    with st.spinner("Generating Overall Clinical Narrative..."):
        overall_summary = hierarchical.generate_overall_summary(master_data.get("page_summaries", []))
        master_data["overall_summary"] = overall_summary
    
    with st.spinner("Aggregating Master Clinical Summary..."):
        summary_md = MasterAggregator.build_markdown_report(master_data)

    # Cache in session state
    st.session_state["case_summary_md"]       = summary_md
    st.session_state["case_summary_pages"]    = page_texts
    st.session_state["case_summary_filename"] = uploaded.name

    st.success("✅ Summary generated!")
    _render_results(summary_md, page_texts, uploaded.name, show_raw)


def _render_results(summary_md: str, page_texts: dict, filename: str, show_raw: bool):
    patient_name, ip_no = _extract_patient_meta(summary_md)

    # ── SUMMARY DISPLAY ───────────────────────────────────────────────────────
    st.divider()
    col_title, col_badge = st.columns([3, 1])
    with col_title:
        st.markdown(f"## 🏥 Case Summary — {patient_name}")
    with col_badge:
        st.markdown(f"**IP No:** `{ip_no}`")

    # Split summary into sections for dropdowns
    sections = re.split(r'\n(## \d+\. .+)', summary_md)

    if len(sections) <= 1:
        # Fallback: show full summary
        st.markdown(summary_md)
    else:
        # Show section 1 (patient ID) expanded, rest as dropdowns
        full_sections = []
        i = 1
        while i < len(sections) - 1:
            title = sections[i].strip()
            body  = sections[i + 1].strip() if (i + 1) < len(sections) else ""
            full_sections.append((title, body))
            i += 2

        # Always show overall summary at top (last section)
        for title, body in full_sections:
            if "OVERALL" in title.upper() or "CLINICAL SUMMARY" in title.upper():
                st.info(body)
                break

        st.divider()
        st.markdown("### 📂 Detailed Sections")

        for title, body in full_sections:
            # First section (Patient ID) expanded by default
            expanded = ("PATIENT IDENTIFICATION" in title.upper() or
                        "DIAGNOSIS" in title.upper())
            with st.expander(title, expanded=expanded):
                st.markdown(body)

    # ── RAW OCR PER PAGE ─────────────────────────────────────────────────────
    if show_raw:
        st.divider()
        st.markdown("### 📄 Raw OCR Text Per Page")
        for pg, txt in page_texts.items():
            with st.expander(f"Page {pg}", expanded=False):
                st.text(txt)

    # ── DOWNLOAD BUTTONS ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 💾 Download Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.spinner("Building PDF..."):
            pdf_bytes = generate_summary_pdf(summary_md, patient_name, ip_no)
        if isinstance(pdf_bytes, bytes):
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name=f"CaseSummary_{ip_no}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.error(pdf_bytes)

    with col2:
        with st.spinner("Building Word doc..."):
            docx_bytes = generate_summary_docx(summary_md, patient_name, ip_no)
        if isinstance(docx_bytes, bytes):
            st.download_button(
                label="📥 Download Word",
                data=docx_bytes,
                file_name=f"CaseSummary_{ip_no}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        else:
            st.error(docx_bytes)

    with col3:
        st.download_button(
            label="📥 Download Markdown",
            data=summary_md,
            file_name=f"CaseSummary_{ip_no}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    st.caption("⚠️ Auto-generated summary — verify all clinical data against original records before use.")


def _show_sample_note():
    with st.expander("ℹ️ What sections does the summary include?", expanded=False):
        st.markdown("""
The summary covers **12 structured sections** across 4–5 pages:

1. **Patient Identification** — Name, Age, IP No, UMR, Ward, Doctor, Admission Date
2. **Diagnosis & Procedure** — Surgery, IOL power, Pre-op vitals
3. **Admission Vitals** — Temp, Pulse, RR, BP, SpO2, Ht, Wt (table)
4. **Risk Assessments** — Braden, Morse Fall, MEWS, Pain, Acuity scores
5. **Nursing Assessment** — Mobility, ADL, allergies, nutrition, skin
6. **Nursing Care Plan** — Diagnosis → Intervention → Rationale → Evaluation
7. **Treatment Chart** — All drugs, doses, routes, frequencies (table)
8. **Investigations** — Lab tests, dates, results (table)
9. **Nurses Notes Timeline** — Date/Time/Shift/Entry (table)
10. **Patient Movement & Handover** — ISBAR summary, safety checks
11. **Patient Education** — Topics covered, nurse, date
12. **Overall Clinical Summary** — Full admission narrative (5–8 sentences)
        """)
