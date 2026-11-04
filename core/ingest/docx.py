"""
Brand Rule Lab — DOCX Ingestion
Owned by Agent A1 (Backend & Data Engineer).
"""

from __future__ import annotations
import hashlib
import io
import docx
from core.models import ExtractedDoc


def ingest_docx(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """Ingest Microsoft Word .docx draft preserving paragraphs and image count."""
    doc = docx.Document(io.BytesIO(file_bytes))
    paragraphs: list[str] = []
    for p in doc.paragraphs:
        stripped = p.text.strip()
        if stripped:
            paragraphs.append(stripped)

    # Also capture table cell text
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paragraphs.append(row_text)

    full_text = "\n\n".join(paragraphs)
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    # Extract inline images if present
    extracted_images: list[bytes] = []
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            try:
                extracted_images.append(rel.target_part.blob)
            except Exception:
                pass

    return ExtractedDoc(
        text=full_text,
        pages=paragraphs,
        images=extracted_images,
        ocr_used=False,
        source_filename=filename,
        source_hash=source_hash,
    )
