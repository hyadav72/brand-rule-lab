"""
Brand Rule Lab — Plain Text Ingestion
Owned by Agent A1 (Backend & Data Engineer).
"""

from __future__ import annotations
import hashlib
from core.models import ExtractedDoc


def ingest_txt(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """Ingest plain text or markdown draft."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")

    source_hash = hashlib.sha256(file_bytes).hexdigest()
    return ExtractedDoc(
        text=text,
        pages=[text],
        images=[],
        ocr_used=False,
        source_filename=filename,
        source_hash=source_hash,
    )
