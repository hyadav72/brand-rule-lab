"""
Brand Rule Lab — Environment & Core Dependencies Smoke Test
Ensures all required third-party libraries and runtime binaries load correctly.
"""

import importlib.metadata
import io
import sqlite3


def test_core_package_imports():
    """Verify that all core libraries can be imported without error."""
    import streamlit as st
    import fitz  # PyMuPDF
    import PIL.Image
    import docx
    import pytest
    import dotenv
    import requests

    assert st is not None
    assert fitz is not None
    assert PIL.Image is not None
    assert docx is not None
    assert pytest is not None
    assert dotenv is not None
    assert requests is not None


def test_package_versions_and_metadata():
    """Verify that package versions meet pinned specifications."""
    # Note: python-dotenv does not provide a module-level __version__ attribute;
    # importlib.metadata is the canonical standard library way to inspect distribution versions.
    dotenv_version = importlib.metadata.version("python-dotenv")
    assert dotenv_version is not None

    import streamlit as st
    import fitz
    import PIL
    import docx
    import pytest
    import requests

    assert st.__version__.startswith("1.")
    assert fitz.__version__.startswith("1.24")
    assert PIL.__version__.startswith("10.")
    assert docx.__version__.startswith("1.1")
    assert pytest.__version__.startswith("8.")
    assert requests.__version__.startswith("2.")


def test_functional_pdf_processing():
    """Verify PyMuPDF can synthesize and extract text in-memory."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Brand Rule Lab - Automated Verification")
    pdf_bytes = doc.tobytes()

    doc_read = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = doc_read[0].get_text()
    assert "Brand Rule Lab - Automated Verification" in extracted_text


def test_functional_docx_processing():
    """Verify python-docx can synthesize and extract text in-memory."""
    import docx

    doc = docx.Document()
    doc.add_paragraph("Brand Rule Lab - Paragraph Verification")
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    doc_read = docx.Document(buffer)
    assert doc_read.paragraphs[0].text == "Brand Rule Lab - Paragraph Verification"


def test_functional_image_processing():
    """Verify Pillow can synthesize and encode image bytes in-memory."""
    from PIL import Image

    img = Image.new("RGB", (120, 80), color=(11, 110, 106))  # Brand Teal #0B6E6A
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    assert len(buffer.getvalue()) > 0


def test_functional_sqlite_and_pragma():
    """Verify SQLite supports foreign keys and parameterized transactions."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT);")
    cursor.execute(
        "CREATE TABLE facts (fact_id TEXT, product_id TEXT, FOREIGN KEY(product_id) REFERENCES products(product_id));"
    )
    cursor.execute("INSERT INTO products VALUES (?, ?);", ("prod_monsoon", "Monsoon Clear Skin"))
    cursor.execute("INSERT INTO facts VALUES (?, ?);", ("F-112", "prod_monsoon"))
    conn.commit()

    res = cursor.execute("SELECT name FROM products WHERE product_id = ?", ("prod_monsoon",)).fetchone()
    assert res[0] == "Monsoon Clear Skin"
