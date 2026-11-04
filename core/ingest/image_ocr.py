"""
Brand Rule Lab — Image Ingestion and OCR
Owned by Agent A1 (Backend & Data Engineer).

Processes raster images (PNG, JPG, JPEG, WEBP).
Uses Tesseract OCR if available, with graceful degradation if tesseract is absent.
"""

from __future__ import annotations
import hashlib
import io
import os
import shutil
from pathlib import Path
from PIL import Image
import pytesseract
from core.models import ExtractedDoc

TESSERACT_ENV_PATH = os.getenv("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def is_tesseract_available() -> bool:
    """Check if tesseract executable is accessible in PATH or configured location."""
    if os.path.exists(TESSERACT_ENV_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_ENV_PATH
        return True
    which_cmd = shutil.which("tesseract")
    if which_cmd:
        pytesseract.pytesseract.tesseract_cmd = which_cmd
        return True
    return False


def ingest_image(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """Ingest image draft, running OCR if engine is available."""
    img = Image.open(io.BytesIO(file_bytes))
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    extracted_text = ""
    ocr_successful = False

    if is_tesseract_available():
        try:
            extracted_text = pytesseract.image_to_string(img).strip()
            ocr_successful = True
        except Exception:
            extracted_text = ""
            ocr_successful = False

    if not extracted_text:
        extracted_text = f"[Image Asset: {filename} ({img.width}x{img.height} {img.format})]"

    return ExtractedDoc(
        text=extracted_text,
        pages=[extracted_text],
        images=[file_bytes],
        ocr_used=ocr_successful,
        source_filename=filename,
        source_hash=source_hash,
    )
