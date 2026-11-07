"""
Brand Rule Lab — Creator Upload Requirements Tests
Validates Section 9, Page 7 and Section 13, Page 11 of the Build Plan.
"""

import io
import os
from pathlib import Path
import docx
import fitz
from PIL import Image
import pytest

from core.audit import apply_creator_decision, log_review_event
from core.db import execute_commit, execute_query, get_connection, init_db
from core.ingest import MAX_UPLOAD_SIZE_BYTES, ingest, validate_upload
from core.models import (
    AssetStatus,
    CreatorActionState,
    ExtractedDoc,
    Finding,
    FindingKind,
    LinkState,
    Role,
    Severity,
)
from core.rules.engine import RuleEngine
from app.ui.components import render_annotated_draft


@pytest.fixture
def test_db(tmp_path):
    """Provide clean isolated test database with necessary schema and baseline data."""
    db_file = tmp_path / "test_creator_req.db"
    db_path = str(db_file)
    init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO products VALUES ('prod_monsoon', 'Monsoon Clear Skin', '[]', 'US');")
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
            ) VALUES ('AST-TEST-01', 'Monsoon Test Draft', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen (Creator)', 'hash123', 'Sample draft', '2026-11-10');
            """
        )
    return db_path


# -----------------------------------------------------------------------------
# 1. Upload & Validation Tests
# -----------------------------------------------------------------------------

def test_upload_supported_formats():
    """Verify PDF, DOCX, TXT, PNG, and JPG ingestion succeeds."""
    # 1. TXT
    txt_doc = ingest(b"Monsoon Clear Skin helps reduce blemishes.", "draft.txt")
    assert "Monsoon Clear Skin" in txt_doc.text

    # 2. DOCX
    d = docx.Document()
    d.add_paragraph("Clear skin in 4 weeks.")
    docx_buf = io.BytesIO()
    d.save(docx_buf)
    docx_doc = ingest(docx_buf.getvalue(), "draft.docx")
    assert "Clear skin in 4 weeks." in docx_doc.text

    # 3. PDF
    pdf = fitz.open()
    p = pdf.new_page()
    p.insert_text((72, 72), "Approved brand claims for Monsoon wash.")
    pdf_bytes = pdf.tobytes()
    pdf_doc = ingest(pdf_bytes, "draft.pdf")
    assert "Approved brand claims for Monsoon wash." in pdf_doc.text

    # 4. PNG
    img_png = Image.new("RGB", (100, 50), color=(255, 255, 255))
    png_buf = io.BytesIO()
    img_png.save(png_buf, format="PNG")
    png_doc = ingest(png_buf.getvalue(), "draft.png")
    assert png_doc.source_filename == "draft.png"
    assert len(png_doc.images) == 1

    # 5. JPG
    img_jpg = Image.new("RGB", (100, 50), color=(200, 200, 200))
    jpg_buf = io.BytesIO()
    img_jpg.save(jpg_buf, format="JPEG")
    jpg_doc = ingest(jpg_buf.getvalue(), "draft.jpg")
    assert jpg_doc.source_filename == "draft.jpg"
    assert len(jpg_doc.images) == 1


def test_upload_max_size_enforcement():
    """Verify strict 10 MB maximum is enforced before and during ingestion."""
    assert MAX_UPLOAD_SIZE_BYTES == 10 * 1024 * 1024

    oversized_bytes = b"X" * (10 * 1024 * 1024 + 1)  # 10 MB + 1 byte
    with pytest.raises(ValueError) as exc:
        validate_upload(oversized_bytes, "oversized.txt")
    assert "exceeds maximum allowed size of 10 MB" in str(exc.value)

    with pytest.raises(ValueError) as exc2:
        ingest(oversized_bytes, "oversized.txt")
    assert "exceeds maximum allowed size of 10 MB" in str(exc2.value)


def test_upload_invalid_format_rejection():
    """Verify unsupported extensions raise clear, helpful error messages."""
    for bad_file in ["script.exe", "data.xlsx", "bundle.zip", "test.py"]:
        with pytest.raises(ValueError) as exc:
            ingest(b"dummy content", bad_file)
        assert "Unsupported file format" in str(exc.value)


def test_upload_pdf_parse_failure_exact_error():
    """
    Verify corrupt or unreadable PDF raises exact friendly message:
    'We could not read this PDF. Try DOCX or TXT'
    """
    corrupt_pdf_bytes = b"%PDF-1.4 corrupt content that cannot be parsed by PyMuPDF \x00\xff"
    with pytest.raises(ValueError) as exc:
        ingest(corrupt_pdf_bytes, "corrupt.pdf")
    assert str(exc.value) == "We could not read this PDF. Try DOCX or TXT"

    # Also verify empty/blank PDF with zero extractable text raises the exact friendly message
    blank_pdf = fitz.open()
    blank_pdf.new_page()  # Page without text or images
    with pytest.raises(ValueError) as exc_blank:
        ingest(blank_pdf.tobytes(), "blank.pdf")
    assert str(exc_blank.value) == "We could not read this PDF. Try DOCX or TXT"


# -----------------------------------------------------------------------------
# 2. Draft Context & Bi-directional Navigation Tests
# -----------------------------------------------------------------------------

def test_annotated_findings_navigation_and_anchors():
    """
    Verify render_annotated_draft generates anchor targets for spans and
    links to corresponding finding cards.
    """
    text = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    findings = [
        Finding(
            finding_id="FND-001",
            asset_id="AST-TEST-01",
            kind=FindingKind.TONE,
            severity=Severity.BLOCK,
            span_start=0,
            span_end=28,
            source_text="Say goodbye to acne forever!",
            rule_id="V-04",
            message="Absolute guarantee violates brand tone.",
            next_step="Softens absolute promise to realistic timeframe.",
        ),
        Finding(
            finding_id="FND-002",
            asset_id="AST-TEST-01",
            kind=FindingKind.CLAIM,
            severity=Severity.BLOCK,
            span_start=66,
            span_end=72,
            source_text="3 days",
            fact_id="F-112",
            fact_version_id=3,
            message="Clinical trial supports 4 weeks, not 3 days.",
            next_step="Align timeframe with approved fact version F-112 v3.",
        ),
    ]

    html = render_annotated_draft(text, findings)

    # 1. Contains anchor targets for spans
    assert 'id="span-FND-001"' in html
    assert 'id="span-FND-002"' in html

    # 2. Contains links pointing to finding cards
    assert 'href="#card-FND-001"' in html
    assert 'href="#card-FND-002"' in html

    # 3. Contains kind-specific highlight styling
    assert "#FFE0B2" in html  # soft orange for Tone
    assert "#E1BEE7" in html  # soft purple for Claim


# -----------------------------------------------------------------------------
# 3. Creator Decisions Tests (Accept, Edit, Dismiss, Gate)
# -----------------------------------------------------------------------------

def test_creator_decision_accept(test_db):
    """Verify accepting a proposed rewrite persists decision and audit record."""
    finding = Finding(
        finding_id="FND-ACC-TEST",
        asset_id="AST-TEST-01",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=15,
        source_text="Say goodbye",
        rule_id="V-04",
        suggested_rewrite="Helps manage blemishes",
    )

    evt = apply_creator_decision(
        finding=finding,
        action="accepted",
        new_text="Helps manage blemishes",
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        asset_id="AST-TEST-01",
        review_cycle=1,
        db_path=test_db,
    )

    assert evt is not None
    assert evt.action == "accept_rewrite"
    assert evt.new_action == "accepted"

    # Verify findings row
    rows = execute_query(
        "SELECT creator_action, suggested_rewrite FROM findings WHERE finding_id = ?",
        ("FND-ACC-TEST",),
        db_path=test_db,
    )
    assert len(rows) == 1
    assert rows[0]["creator_action"] == "accepted"
    assert rows[0]["suggested_rewrite"] == "Helps manage blemishes"


def test_creator_decision_edit(test_db):
    """Verify custom edit persists decision and audit record."""
    finding = Finding(
        finding_id="FND-EDT-TEST",
        asset_id="AST-TEST-01",
        kind=FindingKind.TERMINOLOGY,
        severity=Severity.BLOCK,
        span_start=10,
        span_end=20,
        source_text="clears breakouts",
        rule_id="T-12",
    )

    evt = apply_creator_decision(
        finding=finding,
        action="edited",
        new_text="reduces the appearance of breakouts",
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        asset_id="AST-TEST-01",
        review_cycle=1,
        db_path=test_db,
    )

    assert evt is not None
    assert evt.action == "edit_rewrite"
    assert evt.new_action == "edited"

    rows = execute_query(
        "SELECT creator_action, suggested_rewrite FROM findings WHERE finding_id = ?",
        ("FND-EDT-TEST",),
        db_path=test_db,
    )
    assert len(rows) == 1
    assert rows[0]["creator_action"] == "edited"
    assert rows[0]["suggested_rewrite"] == "reduces the appearance of breakouts"


def test_creator_decision_dismissal_requires_mandatory_reason(test_db):
    """Verify dismissal requires a non-empty standard reason."""
    finding = Finding(
        finding_id="FND-DIS-TEST",
        asset_id="AST-TEST-01",
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=5,
        span_end=15,
        source_text="special case",
        rule_id="C-01",
    )

    # Empty dismissal reason must raise ValueError
    with pytest.raises(ValueError) as exc:
        apply_creator_decision(
            finding=finding,
            action="dismissed",
            dismiss_reason="",
            actor="Alex Chen (Creator)",
            role=Role.CREATOR,
            asset_id="AST-TEST-01",
            review_cycle=1,
            db_path=test_db,
        )
    assert "mandatory standard reason" in str(exc.value).lower()

    # Valid dismissal with reason and optional note succeeds
    valid_reason = "Approved Exception Granted | VP Brand sign-off on legal packaging exemption"
    evt = apply_creator_decision(
        finding=finding,
        action="dismissed",
        dismiss_reason=valid_reason,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        asset_id="AST-TEST-01",
        review_cycle=1,
        db_path=test_db,
    )

    assert evt is not None
    assert evt.action == "dismiss_finding"
    assert evt.new_action == "dismissed"

    rows = execute_query(
        "SELECT creator_action, dismiss_reason FROM findings WHERE finding_id = ?",
        ("FND-DIS-TEST",),
        db_path=test_db,
    )
    assert len(rows) == 1
    assert rows[0]["creator_action"] == "dismissed"
    assert rows[0]["dismiss_reason"] == valid_reason


def test_deterministic_recheck_blocks_violating_rewrites():
    """Verify RuleEngine.check_rewrite rejects proposed rewrites violating rules."""
    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US", "channel": "paid_social"}

    # Violating text: contains absolute claim "clears breakouts forever"
    is_clean, violations = engine.check_rewrite("This wash clears breakouts forever!", context)
    assert not is_clean
    assert len(violations) > 0

    # Compliant text: permitted wording for Fact F-112 v3
    clean_text = "Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use."
    is_clean2, violations2 = engine.check_rewrite(clean_text, context)
    assert is_clean2
    assert len(violations2) == 0


# -----------------------------------------------------------------------------
# 4. Mandatory Footer & UI Verification
# -----------------------------------------------------------------------------

def test_mandatory_footer_present_in_creator_page():
    """Verify exact mandatory footer note from Build Plan Section 9 is present."""
    creator_page_path = Path("app/pages/1_Creator.py")
    assert creator_page_path.exists()
    content = creator_page_path.read_text(encoding="utf-8")

    expected_footer = "AI-assisted review: suggestions are drafts; the model receives claim text and approved fact fields only."
    assert expected_footer in content, f"Mandatory footer text '{expected_footer}' not found in 1_Creator.py"


# -----------------------------------------------------------------------------
# 5. Accessibility & State Indicator Tests (Priority 1)
# -----------------------------------------------------------------------------

def test_state_chips_canonical_definitions_and_accessibility():
    """Verify CURRENT, REVIEW_REQUIRED, EXPIRED, UNLINKED, NOT_OBSERVED chips and tooltips."""
    from app.ui.components import render_state_chip
    from core.models import DriftStatus, LinkState

    states = [
        ("CURRENT", "chip-current"),
        ("REVIEW_REQUIRED", "chip-review-required"),
        ("EXPIRED", "chip-expired"),
        ("UNLINKED", "chip-unlinked"),
        ("NOT_OBSERVED", "chip-not-observed"),
    ]

    for state_name, expected_class in states:
        html = render_state_chip(state_name)
        assert expected_class in html, f"Missing class {expected_class} for {state_name}"
        assert f'>{state_name}</span>' in html
        assert 'title="' in html, f"Missing title tooltip for {state_name}"
        assert 'aria-label="' in html, f"Missing aria-label for {state_name}"
        assert 'tabindex="0"' in html, f"Missing keyboard tabindex for {state_name}"


def test_wcag_aa_contrast_ratios():
    """Verify status badges and state chips meet WCAG AA contrast threshold (>= 4.5:1)."""
    def rel_lum(hex_col: str) -> float:
        rgb = [int(hex_col[i:i+2], 16) / 255.0 for i in (1, 3, 5)]
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    def contrast(c1: str, c2: str) -> float:
        l1 = rel_lum(c1)
        l2 = rel_lum(c2)
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

    elements = [
        ("chip-current", "#107C41", "#E8F5E9"),
        ("chip-review-required", "#B4521A", "#FFF3E0"),
        ("chip-expired", "#C62828", "#FFEBEE"),
        ("chip-unlinked", "#455A64", "#ECEFF1"),
        ("chip-not-observed", "#512DA8", "#EDE7F6"),
        ("badge-ready", "#0B6E6A", "#E0F2F1"),
        ("badge-changes", "#A34010", "#FBE9E7"),
        ("badge-approved", "#107C41", "#E8F5E9"),
        ("badge-escalated", "#13171A", "#ECEFF1"),
    ]

    for name, fg, bg in elements:
        cr = contrast(fg, bg)
        assert cr >= 4.5, f"Element {name} fails WCAG AA: {cr:.2f}:1 < 4.5:1"


def test_streamlit_pages_load_cleanly():
    """Verify Creator, Reviewer, Fact Owner and Home load with zero unhandled exceptions."""
    from streamlit.testing.v1 import AppTest

    for page in ["app/Home.py", "app/pages/1_Creator.py", "app/pages/2_Reviewer.py", "app/pages/3_Fact_Owner.py"]:
        at = AppTest.from_file(page, default_timeout=10)
        at.run()
        assert not at.exception, f"Exception in {page}: {at.exception}"
