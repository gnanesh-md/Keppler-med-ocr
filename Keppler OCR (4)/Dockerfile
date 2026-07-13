# ── Stage 1: build the React frontend ───────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY ["Frontend OCR/package.json", "Frontend OCR/package-lock.json", "./"]
RUN npm install
COPY ["Frontend OCR/", "./"]
RUN npm run build

# ── Stage 2: Python API (serves the API and the built frontend) ────────────
FROM python:3.11-slim

WORKDIR /app

# 🚀 CRITICAL SYSTEM DEPENDENCIES
# - build-essential/pkg-config/libcairo2-dev: xhtml2pdf's native deps.
# - libgl1/libglib2.0-0: cv2 (opencv) needs libGL.so.1 even via the
#   "headless" package, pulled in transitively by ultralytics/other deps —
#   this bit us for real: the host dev machine has these from its desktop
#   GPU drivers, masking the missing dependency until the first container
#   run (ImportError: libGL.so.1: cannot open shared object file).
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    pkg-config \
    libcairo2-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy your requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Copy the built frontend static assets — api/main.py mounts this directory if present
COPY --from=frontend-build ["/frontend/dist", "./Frontend OCR/dist"]

# Expose the FastAPI gateway's port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
