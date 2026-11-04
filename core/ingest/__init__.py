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


def ingest(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """
    Ingest marketing draft bytes and return unified ExtractedDoc.
    Validates file format and handles errors gracefully.
    """
    if not file_bytes:
        raise ValueError(f"Uploaded file '{filename}' is empty (0 bytes).")

    ext = Path(filename).suffix.lower()
    parser = SUPPORTED_EXTENSIONS.get(ext)
    if not parser:
        supported_list = ", ".join(sorted(SUPPORTED_EXTENSIONS.keys()))
        raise ValueError(
            f"Unsupported file format '{ext}'. Brand Rule Lab accepts: {supported_list}"
        )

    return parser(file_bytes, filename)


__all__ = ["ingest", "ingest_txt", "ingest_docx", "ingest_pdf", "ingest_image"]
