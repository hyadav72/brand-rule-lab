"""
Brand Rule Lab — PDF Ingestion
Owned by Agent A1 (Backend & Data Engineer).
"""

from __future__ import annotations
import hashlib
import fitz  # PyMuPDF
from core.models import ExtractedDoc


def ingest_pdf(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """Ingest PDF draft using PyMuPDF with per-page text and image extraction."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages_text: list[str] = []
    extracted_images: list[bytes] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text("text").strip()
        pages_text.append(text)

        # Extract embedded raster images
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image.get("image")
            if image_bytes:
                extracted_images.append(image_bytes)

    full_text = "\n\n".join(t for t in pages_text if t)
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    return ExtractedDoc(
        text=full_text,
        pages=pages_text,
        images=extracted_images,
        ocr_used=False,
        source_filename=filename,
        source_hash=source_hash,
    )
