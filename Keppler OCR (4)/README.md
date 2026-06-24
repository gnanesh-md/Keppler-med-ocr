---
title: Keppler AI Portal - Medical OCR & RAG Agent
emoji: 🧠
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 8501
---

# 🧠 Keppler AI Portal (Medical OCR & RAG Agent)

Welcome to the **Keppler AI Portal**! This project is a comprehensive local AI system built for hospitals and medical professionals. It combines advanced Vision Models (OCR) and Large Language Models (LLMs) to automatically read scanned hospital documents, generate structured clinical summaries, and allow users to chat with their documents securely.

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
├── app.py                     # 🚀 MAIN ENTRY POINT: The core Streamlit router & UI layout.
├── requirements.txt           # 📦 Python dependencies (Streamlit, PyPDF2, Ollama, etc.)
├── Dockerfile                 # 🐳 Docker configuration for containerized deployment.
├── .env                       # 🔐 Environment variables (API Keys, Configurations).
│
├── modules/                   # 🧠 CORE AI ENGINES:
│   ├── pdf_summarizer.py      #   - Reads multi-page PDFs & builds clinical summaries.
│   ├── precision_ocr.py       #   - Handles single-page universal OCR extraction.
│   ├── rag_chatbot.py         #   - The local Knowledge Graph chatbot (LightRAG).
│   ├── admin_panel.py         #   - Admin dashboard for user/data management.
│   ├── frequency_resolver.py  #   - Data resolution logic.
│   ├── itemmaster_resolver.py #   - Data resolution logic.
│   └── unified_resolver.py    #   - TF-IDF/ML-based data mapping algorithms.
│
├── database/                  # 💾 LOCAL STORAGE:
│   ├── db_utils.py            #   - SQLite database initialization & query functions.
│   ├── ai_portal.db           #   - The actual SQLite database file (created on runtime).
│   └── rag_workspace_user_*/  #   - Folders containing the local Knowledge Graphs per user.
│
├── components/                # 🧩 UI COMPONENTS:
│   └── auth_ui.py             #   - The Login / Registration screen UI.
│
├── datasets/                  # 📊 DATA FILES:
│   └── *.xlsx / *.jsonl       #   - Reference Excel files used by the RAG bot to learn context.
│
└── temp_uploads/              # 🗑️ TEMPORARY FOLDER: Used to temporarily hold files during upload.
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

Once everything is installed, you start the app using Streamlit:

```bash
streamlit run app.py
```

1. The terminal will provide a local URL (usually `http://localhost:8501`).
2. Open that URL in your web browser.
3. Log in using your credentials (if it's the first time, you may need to register an account or use `admin`).

---

## 📖 How to Use the App

### 1. Universal OCR
- Navigate to **Universal OCR** from the sidebar.
- Upload an image or PDF page.
- The system will use the Vision Model to extract all text exactly as written.

### 2. PDF Summarizer
- Navigate to **PDF Summarizer** from the sidebar.
- Upload a patient case file (PDF up to 50 pages).
- Click **Generate Summary**.
- The system splits the PDF into 5-page chunks, processes them, and produces a comprehensive Master Summary and a detailed breakdown.
- Download the final report as a PDF, DOCX (Word), or Markdown file.

### 3. Document Vault & RAG
- Go to **Document Vault**. Here you'll find everything you previously extracted using the OCR.
- Select specific documents and click **Load Selected Documents into RAG Chatbot**.
- In the **Knowledge RAG** module, you can type questions into the chatbox (e.g., *"What is the patient's Morse Fall risk?"*). The AI will answer based purely on the documents you loaded.

---

## 🐛 Troubleshooting

- **`sqlite3.OperationalError`**: If you get a database error, delete the `database/ai_portal.db` file. The system will recreate a fresh one automatically the next time you run `app.py`.
- **Model Offline / Connection Refused**: Make sure the Ollama application is actively running in the background before you start Streamlit.
- **Out of Memory / Very Slow Generation**: The `qwen2.5vl:32b` model requires significant memory. If your computer crashes, edit `app.py` and `modules/pdf_summarizer.py` to use a smaller model like `qwen2.5vl:7b` instead.