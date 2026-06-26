import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Core Platform Configuration Settings"""
    
    # Platform Metadata
    APP_NAME: str = "Keppler Medical Document Intelligence Platform"
    APP_VERSION: str = "2.0.0"
    
    # Inference Endpoints
    VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8700/v1")
    QWEN_OCR_MODEL: str = os.getenv("QWEN_OCR_MODEL", "qwen2.5-vl-7b")
    
    # Infrastructure (Redis + Celery)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./keppler_platform.db")
    
    # File Storage
    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")

    class Config:
        env_file = ".env"

# Initialize global singleton
settings = Settings()

# Ensure critical directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
