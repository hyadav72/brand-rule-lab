"""
Brand Rule Lab — Ingestion Pipeline Tests
Owned by Agent A5 (QA Engineer).
"""

import io
import fitz
import docx
from PIL import Image
import pytest
from core.ingest import ingest


def test_ingest_txt():
    """Verify TXT ingestion returns ExtractedDoc with hash and text."""
    content = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    file_bytes = content.encode("utf-8")
    doc = ingest(file_bytes, "draft.txt")

    assert doc.text == content
    assert len(doc.pages) == 1
    assert not doc.ocr_used
    assert len(doc.source_hash) == 64  # SHA-256


def test_ingest_docx():
    """Verify DOCX ingestion extracts paragraphs."""
    doc_docx = docx.Document()
    doc_docx.add_paragraph("Headline: Clear Skin Today")
    doc_docx.add_paragraph("Body: 2.5% Benzoyl Peroxide wash.")
    buf = io.BytesIO()
    doc_docx.save(buf)

    doc = ingest(buf.getvalue(), "copy.docx")
    assert "Headline: Clear Skin Today" in doc.text
    assert "2.5% Benzoyl Peroxide wash." in doc.text
    assert len(doc.pages) == 2


def test_ingest_pdf():
    """Verify PDF ingestion extracts text from pages."""
    pdf = fitz.open()
    p1 = pdf.new_page()
    p1.insert_text((72, 72), "Monsoon Clear Skin Campaign Draft")
    pdf_bytes = pdf.tobytes()

    doc = ingest(pdf_bytes, "campaign.pdf")
    assert "Monsoon Clear Skin Campaign Draft" in doc.text
    assert len(doc.pages) == 1


def test_ingest_image_graceful_fallback():
    """Verify image ingestion handles absent OCR engine without crashing."""
    img = Image.new("RGB", (200, 100), color=(11, 110, 106))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = ingest(buf.getvalue(), "banner.png")
    assert doc.source_filename == "banner.png"
    assert len(doc.images) == 1
    assert len(doc.text) > 0


def test_ingest_empty_file_raises():
    """Verify empty upload raises ValueError."""
    with pytest.raises(ValueError) as exc:
        ingest(b"", "empty.txt")
    assert "empty" in str(exc.value).lower()


def test_ingest_unsupported_extension_raises():
    """Verify unsupported file types return user-friendly error message."""
    with pytest.raises(ValueError) as exc:
        ingest(b"some binary data", "archive.zip")
    assert "Unsupported file format" in str(exc.value)
