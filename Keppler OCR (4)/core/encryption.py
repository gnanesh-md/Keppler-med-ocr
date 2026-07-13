"""
Encryption at rest for uploads/ (Phase 6). Every new upload is written as a
Fernet token instead of plaintext; PDFs/images already on disk from before
this feature (uploads/ had ~90 real files pre-Phase-6) are NOT re-encrypted
in place — read_encrypted_upload() transparently falls back to returning the
raw bytes when Fernet decryption fails (not a valid token), so old files
keep working without a migration step.
"""
from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

_fernet = Fernet(settings.UPLOAD_ENCRYPTION_KEY.encode())


def write_encrypted_upload(file_path: str, data: bytes):
    with open(file_path, "wb") as f:
        f.write(_fernet.encrypt(data))


def read_encrypted_upload(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        raw = f.read()
    try:
        return _fernet.decrypt(raw)
    except InvalidToken:
        # Pre-Phase-6 plaintext upload — not a Fernet token, return as-is.
        return raw
