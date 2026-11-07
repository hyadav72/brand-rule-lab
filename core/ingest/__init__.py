"""
Brand Rule Lab — Unified Ingestion Module
Owned by Agent A1 (Backend & Data Engineer).

Dispatches file bytes to appropriate parser based on file extension.
Supported formats: PDF, DOCX, TXT, PNG, JPG, JPEG, WEBP.
"""

from __future__ import annotations
from pathlib import Path
from core.models import ExtractedDoc
from core.ingest.docx import ingest_docx
from core.ingest.image_ocr import ingest_image
from core.ingest.pdf import ingest_pdf
from core.ingest.txt import ingest_txt

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB strict limit

SUPPORTED_EXTENSIONS = {
    ".txt": ingest_txt,
    ".md": ingest_txt,
    ".docx": ingest_docx,
    ".pdf": ingest_pdf,
    ".png": ingest_image,
    ".jpg": ingest_image,
    ".jpeg": ingest_image,
    ".webp": ingest_image,
}


def validate_upload(file_bytes: bytes, filename: str, max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES) -> None:
    """
    Validate marketing draft bytes and filename before ingestion.
    Enforces non-empty content, strict 10 MB maximum, and allowed extensions.
    """
    if not file_bytes:
        raise ValueError(f"Uploaded file '{filename}' is empty (0 bytes).")

    if len(file_bytes) > max_size_bytes:
        size_mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(
            f"File '{filename}' exceeds maximum allowed size of 10 MB ({size_mb:.1f} MB)."
        )

    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported_list = ", ".join(sorted(SUPPORTED_EXTENSIONS.keys()))
        raise ValueError(
            f"Unsupported file format '{ext}'. Brand Rule Lab accepts: {supported_list}"
        )


def ingest(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """
    Ingest marketing draft bytes and return unified ExtractedDoc.
    Validates file format and handles errors gracefully.
    """
    validate_upload(file_bytes, filename)
    ext = Path(filename).suffix.lower()
    parser = SUPPORTED_EXTENSIONS[ext]
    return parser(file_bytes, filename)


__all__ = [
    "ingest",
    "validate_upload",
    "MAX_UPLOAD_SIZE_BYTES",
    "SUPPORTED_EXTENSIONS",
    "ingest_txt",
    "ingest_docx",
    "ingest_pdf",
    "ingest_image",
]
