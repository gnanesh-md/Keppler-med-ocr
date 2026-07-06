import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import settings
from database.db_utils import initialize_extended_schema
from api.routers import assistant, auth, dashboard, ocr, summarizer, vault

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)


@app.on_event("startup")
async def on_startup():
    # Ensures the users/chat_history/universal_docs tables exist.
    initialize_extended_schema()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ocr.router)
app.include_router(summarizer.router)
app.include_router(vault.router)
app.include_router(assistant.router)
app.include_router(dashboard.router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


# Serve the built React frontend (Frontend OCR/dist) if present — e.g. in the
# Docker image, where it's built in a separate stage. In local dev, run the
# Vite dev server separately instead (npm run dev); this mount is skipped.
_FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Frontend OCR", "dist"
)
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
