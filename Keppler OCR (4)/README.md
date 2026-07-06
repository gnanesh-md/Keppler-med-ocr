---
title: Keppler AI Portal - Medical OCR & RAG Agent
emoji: 🧠
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 8000
---

# 🧠 Keppler AI Portal (Medical OCR & RAG Agent)

Welcome to the **Keppler AI Portal**! This project is a comprehensive local AI system built for hospitals and medical professionals. It combines advanced Vision Models (OCR) and Large Language Models (LLMs) to automatically read scanned hospital documents, generate structured clinical summaries, and allow users to chat with their documents securely.

The app is a **FastAPI backend** (`api/`) paired with a **React frontend** (`Frontend OCR/`) — the backend wraps the same OCR/summarization/CDSS/RAG pipelines described below and exposes them as a REST API; the frontend is the browser UI.

> **Privacy First**: All AI processing happens completely offline on your local machine using **Ollama**. No patient data is sent to the cloud.

---

## 🌟 Key Features

1. **Universal OCR**: Upload scanned medical records, invoices, or forms. The local vision model extracts text with flawless spatial accuracy.
2. **Medical Case Summarizer**: Upload large, multi-page patient case files (PDFs). The system chunks the document, reads every page, and produces a structured 5-page clinical summary (exportable to PDF, Word, and Markdown).
3. **Knowledge RAG Chatbot**: Combines your extracted documents into a local "Knowledge Graph". You can ask the AI questions across multiple documents in multiple languages (English, Spanish, Hindi, Telugu, etc.).
4. **Document Vault**: Safely stores past extracted texts, confidence scores, and chat histories in a local SQLite database.
5. **Admin Console**: Manage system users, inspect extracted data logs, and monitor usage.

---

## 📂 Project Structure

Here is a breakdown of what each folder and file does:

```text
Keppler OCR (4)/
│
├── api/                        # 🚀 MAIN ENTRY POINT: FastAPI app (api/main.py) + routers/
│   ├── main.py                 #   - App assembly, CORS, static frontend mount.
│   └── routers/                #   - auth, ocr, summarizer, cdss, vault, assistant, dashboard.
├── requirements.txt            # 📦 Python dependencies (FastAPI, PyPDF2, Ollama client, etc.)
├── Dockerfile                  # 🐳 Multi-stage build: builds the frontend, then the API image.
├── .env                        # 🔐 Environment variables (API Keys, Configurations).
│
├── Frontend OCR/                # 🖥️ REACT FRONTEND: Vite + React + Tailwind UI.
│   └── src/app/                 #   - App.tsx (screens), lib/api.ts (backend client).
│
├── modules/                    # 🧠 CORE AI ENGINES:
│   ├── pdf_summarizer.py       #   - Reads multi-page PDFs & builds clinical summaries.
│   ├── precision_ocr.py        #   - Handles single-page universal OCR extraction.
│   ├── drug_cdss.py            #   - Clinical Decision Support rule engine.
│   ├── rag_chatbot.py          #   - The local Knowledge Graph chatbot (LightRAG).
│   ├── admin_panel.py          #   - Admin data-fetching functions (metrics, audit log).
│   ├── frequency_resolver.py   #   - Data resolution logic.
│   ├── itemmaster_resolver.py  #   - Data resolution logic.
│   └── unified_resolver.py     #   - TF-IDF/ML-based data mapping algorithms.
│
├── database/                   # 💾 LOCAL STORAGE:
│   ├── db_utils.py             #   - SQLite database initialization & query functions.
│   ├── models.py               #   - SQLAlchemy job-tracking tables (Document, ExtractionJob).
│   ├── ai_portal.db            #   - The actual SQLite database file (created on runtime).
│   └── rag_workspace_user_*/   #   - Folders containing the local Knowledge Graphs per user.
│
├── datasets/                   # 📊 DATA FILES:
│   └── *.xlsx / *.jsonl        #   - Reference Excel files used by the RAG bot to learn context.
│
└── temp_uploads/ / uploads/     # 🗑️ TEMPORARY FOLDERS: Hold files during upload/processing.
```

---

## 🛠️ Step-by-Step Installation Guide (For Beginners)

Follow these steps to get the system running on your computer.

### Step 1: Install Python
Ensure you have **Python 3.10 or newer** installed.
- **Windows / Mac / Linux**: Download from [python.org](https://www.python.org/downloads/).

### Step 2: Install Ollama (Local AI Engine)
Ollama runs the AI models locally on your computer.
1. Download Ollama from [ollama.com](https://ollama.com/download) and install it.
2. Open your Terminal (or Command Prompt) and pull the required models by running these commands one by one:
   ```bash
   ollama pull qwen2.5vl:32b     # The vision model used for OCR (reads images)
   ollama pull qwen2.5:7b        # The text model used for summarization
   ollama pull nomic-embed-text  # The embedding model used for the RAG chatbot
   ```
   *(Note: The `32b` model is large and requires a capable GPU. If you have limited RAM/VRAM, you may need to substitute it in the code with a smaller vision model like `llama3.2-vision`.)*

### Step 3: Setup the Python Environment
Open your Terminal, navigate to the project folder (`Keppler OCR (4)`), and create an isolated environment:

**For Mac/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**For Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

### Step 4: Install Dependencies
With your virtual environment activated, install all required Python libraries:
```bash
pip install -r requirements.txt
```

---

## 🚀 Running the Application

The app runs as two processes in development: the FastAPI backend and the React frontend.

**Terminal 1 — start the backend:**
```bash
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — start the frontend:**
```bash
cd "Frontend OCR"
npm install   # first time only
npm run dev
```

1. The frontend terminal will provide a local URL (usually `http://localhost:5173`). Open that URL in your web browser — it's already configured to proxy API calls to the backend on port 8000 (see `Frontend OCR/vite.config.ts`).
2. Register an account from the login screen the first time you run it, then sign in.

For a single-container production build, `docker build` uses the included multi-stage `Dockerfile` (builds the frontend, then serves both the API and the built frontend from `uvicorn` on port 8000).

---

## 📖 How to Use the App

### 1. OCR Workspace
- Navigate to **OCR Workspace** from the sidebar.
- Upload an image or PDF.
- The system will use the Vision Model to extract all text exactly as written, then walk you through Processing and the structured Result view (with export to Markdown/PDF/Word/Excel/JSON).

### 2. PDF Summarizer
- Navigate to **PDF Summarizer** from the sidebar.
- Upload a patient case file PDF.
- The system OCRs every page, then produces a comprehensive structured clinical summary.
- Download the final report as a PDF, DOCX (Word), or Markdown file.

### 3. Document Vault & AI Assistant
- Go to **Document Vault**. Here you'll find everything you previously extracted using the OCR or PDF Summarizer.
- Click the sparkle icon on a document to **load it into the AI Assistant's knowledge graph**.
- In **AI Assistant**, type questions into the chatbox (e.g., *"What is the patient's Morse Fall risk?"*). The AI answers based purely on the documents you've loaded.

---

## 🐛 Troubleshooting

- **`sqlite3.OperationalError`**: If you get a database error, delete the `database/ai_portal.db` file. The system will recreate a fresh one automatically the next time you start the backend.
- **Model Offline / Connection Refused**: Make sure the Ollama application is actively running in the background before you start the backend.
- **Out of Memory / Very Slow Generation**: The `qwen2.5vl:32b` model requires significant memory. If your computer crashes, edit `modules/precision_ocr.py` and `modules/pdf_summarizer.py` to use a smaller model like `qwen2.5vl:7b` instead.
- **Frontend can't reach the API**: Confirm the backend is running on port 8000 and check `Frontend OCR/vite.config.ts`'s dev proxy target.