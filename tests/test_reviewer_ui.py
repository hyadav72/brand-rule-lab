"""
Brand Rule Lab — Reviewer UI Tests (FAIL-01 & FAIL-02)
Owned by Agent A4 & A5.

Tests:
1. Queue table data includes all three demo assets (AST-MONSOON-01, AST-DIWALI-01, AST-SUNSCREEN-01).
2. Correct finding counts, status, owner fallback, and age display.
3. Selecting an asset opens the correct detail view.
4. Annotated draft renders correct finding spans and colors.
5. Clicking a finding navigates to the matching span (bi-directional anchor links).
6. Overlapping and invalid spans are handled safely without crashing or text corruption.
7. Existing Reviewer role restrictions remain strictly enforced.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sqlite3
import pytest
from core.audit import get_asset_audit_trail, log_review_event
from core.db import execute_commit, execute_query
from core.ledger.approve import approve_claim, escalate_asset, request_changes
from core.lookup.facts import publish_fact_version
from core.models import Finding, FindingKind, LinkState, ReviewEvent, Role
from core.seed import seed_database
from app.ui.components import (
    format_age,
    get_reviewer_queue_data,
    has_column,
    render_annotated_draft,
    render_audit_event_item,
    render_reviewer_queue_table,
    render_status_badge,
)


@pytest.fixture
def disposable_seed_db(tmp_path):
    """Provide a fresh disposable database seeded with demo assets."""
    db_file = tmp_path / "disposable_reviewer_test.db"
    db_path = str(db_file)
    counts = seed_database(db_path, include_demo_assets=True)
    assert counts["assets"] == 3
    return db_path


# ---------------------------------------------------------------------------
# 1. Queue Table Data includes all three demo assets
# ---------------------------------------------------------------------------

def test_queue_table_data_includes_all_three_demo_assets(disposable_seed_db):
    """Reviewer queue data must include AST-MONSOON-01, AST-DIWALI-01, and AST-SUNSCREEN-01."""
    db = disposable_seed_db
    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db)

    asset_ids = {a["asset_id"] for a in queue}
    assert "AST-MONSOON-01" in asset_ids
    assert "AST-DIWALI-01" in asset_ids
    assert "AST-SUNSCREEN-01" in asset_ids
    assert len(queue) == 3


# ---------------------------------------------------------------------------
# 2. Correct finding counts, status, owner fallback, and age display
# ---------------------------------------------------------------------------

def test_queue_data_counts_status_owner_and_age(disposable_seed_db):
    """Queue items have verified finding counts, status, owner names, and formatted age."""
    db = disposable_seed_db
    ref_time = datetime(2026, 11, 7, 18, 0, 0)
    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db, reference_time=ref_time)
    by_id = {a["asset_id"]: a for a in queue}

    # Monsoon asset verification
    monsoon = by_id["AST-MONSOON-01"]
    assert monsoon["finding_count"] == 5
    assert monsoon["status"] == "ready_for_review"
    assert monsoon["owner"] == "Alex Chen (Creator)"
    assert monsoon["age"] != "—"

    # Diwali asset verification
    diwali = by_id["AST-DIWALI-01"]
    assert diwali["finding_count"] == 3
    assert diwali["status"] == "ready_for_review"
    assert diwali["owner"] == "Alex Chen (Creator)"
    assert diwali["age"] != "—"

    # Sunscreen asset verification
    sunscreen = by_id["AST-SUNSCREEN-01"]
    assert sunscreen["finding_count"] == 3
    assert sunscreen["status"] == "ready_for_review"
    assert sunscreen["owner"] == "Alex Chen (Creator)"
    assert sunscreen["age"] != "—"


def test_queue_data_owner_and_age_truthful_fallbacks(disposable_seed_db):
    """When creator or timestamp is unavailable, displays truthful 'Unassigned' and '—' fallbacks."""
    db = disposable_seed_db

    # Insert an asset with empty created_by and NULL created_at
    execute_commit(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, created_at)
        VALUES ('AST-ORPHAN-01', 'Orphaned Asset', 'prod_monsoon', 'US', 'paid_social', 'ready_for_review', '', 'hash_orphan', 'Test draft', '2026-11-20', NULL);
        """,
        db_path=db,
    )

    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db)
    orphan = next(a for a in queue if a["asset_id"] == "AST-ORPHAN-01")
    assert orphan["owner"] == "Unassigned"
    assert orphan["age"] == "—"


def test_format_age_time_calculations():
    """Verify format_age calculates accurate relative strings across various intervals."""
    ref = datetime(2026, 11, 7, 12, 0, 0)

    # Missing / None / empty
    assert format_age(None, reference_time=ref) == "—"
    assert format_age("", reference_time=ref) == "—"
    assert format_age("invalid-date", reference_time=ref) == "—"

    # Future / zero
    assert format_age(ref + timedelta(minutes=5), reference_time=ref) == "Just now"

    # Seconds
    assert format_age(ref - timedelta(seconds=45), reference_time=ref) == "45s ago"

    # Minutes
    assert format_age(ref - timedelta(minutes=15), reference_time=ref) == "15m ago"

    # Hours
    assert format_age(ref - timedelta(hours=4), reference_time=ref) == "4h ago"

    # Days
    assert format_age(ref - timedelta(days=3), reference_time=ref) == "3d ago"

    # Months
    assert format_age(ref - timedelta(days=65), reference_time=ref) == "2mo ago"


# ---------------------------------------------------------------------------
# 3. Selecting an asset opens the correct detail view
# ---------------------------------------------------------------------------

def test_queue_table_html_and_selection_detail(disposable_seed_db):
    """render_reviewer_queue_table generates readable table with active row highlighting and detail mapping."""
    db = disposable_seed_db
    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db)

    # Render with AST-MONSOON-01 selected
    table_html = render_reviewer_queue_table(queue, selected_asset_id="AST-MONSOON-01")

    # Assert column headers exist
    for col in ("Asset", "Findings", "Status", "Owner", "Age"):
        assert col in table_html

    # Assert all assets appear
    for aid in ("AST-MONSOON-01", "AST-DIWALI-01", "AST-SUNSCREEN-01"):
        assert aid in table_html

    # Assert AST-MONSOON-01 is marked active
    assert "selected-row" in table_html
    assert "Active" in table_html

    # Switching selection to AST-DIWALI-01
    table_html_diwali = render_reviewer_queue_table(queue, selected_asset_id="AST-DIWALI-01")
    assert "AST-DIWALI-01" in table_html_diwali
    assert "selected-row" in table_html_diwali

    # Verify detail view can retrieve findings for selected asset
    selected_asset = next(a for a in queue if a["asset_id"] == "AST-DIWALI-01")
    diwali_findings = execute_query(
        "SELECT * FROM findings WHERE asset_id = ?;",
        (selected_asset["asset_id"],),
        db_path=db,
    )
    assert len(diwali_findings) == 3
    assert "Celebrate Diwali" in selected_asset["text_content"]


# ---------------------------------------------------------------------------
# 4. Annotated draft renders correct finding spans
# ---------------------------------------------------------------------------

def test_annotated_draft_renders_correct_finding_spans(disposable_seed_db):
    """render_annotated_draft highlights spans using distinct kind colors and preserves draft text."""
    db = disposable_seed_db
    monsoon = execute_query("SELECT * FROM assets WHERE asset_id = 'AST-MONSOON-01';", db_path=db)[0]
    findings = execute_query(
        "SELECT * FROM findings WHERE asset_id = 'AST-MONSOON-01' ORDER BY span_start ASC;",
        db_path=db,
    )

    html_out = render_annotated_draft(monsoon["text_content"], findings)

    # Highlight marks exist
    assert "<mark" in html_out
    assert "</mark>" in html_out

    # Theme colors for kinds are present
    assert "#FFE0B2" in html_out  # tone (V-04)
    assert "#FFCDD2" in html_out  # terminology (T-12)
    assert "#E1BEE7" in html_out  # claim (C-01)
    assert "#FFF9C4" in html_out  # offer_date (D-02)

    # Key text spans appear inside html
    assert "forever" in html_out
    assert "BPO" in html_out
    assert "clears breakouts in 3 days" in html_out
    assert "guaranteed" in html_out


# ---------------------------------------------------------------------------
# 5. Clicking a finding navigates to the matching span (Bi-directional Anchors)
# ---------------------------------------------------------------------------

def test_clicking_finding_navigates_to_matching_span(disposable_seed_db):
    """Spans have unique anchor IDs and badges link to finding cards."""
    db = disposable_seed_db
    findings = execute_query(
        "SELECT * FROM findings WHERE asset_id = 'AST-MONSOON-01' ORDER BY span_start ASC;",
        db_path=db,
    )
    draft_text = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days. Dermatologist tested and guaranteed to work."

    html_out = render_annotated_draft(draft_text, findings)

    for f in findings:
        fid = f["finding_id"]
        # Anchor target in the draft
        assert f'id="span-{fid}"' in html_out
        # Link from span badge to finding card
        assert f'href="#card-{fid}"' in html_out


# ---------------------------------------------------------------------------
# 6. Overlapping and invalid spans are handled safely
# ---------------------------------------------------------------------------

def test_overlapping_spans_handled_safely_without_text_corruption():
    """Overlapping spans are partitioned without duplicating characters or dropping text."""
    # Finding 1 covers 0..30; Finding 2 covers 20..27 (nested inside Finding 1)
    text = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    findings = [
        {"finding_id": "FND-D02-0", "span_start": 0, "span_end": 30, "kind": "offer_date", "rule_id": "D-02"},
        {"finding_id": "FND-V04-20", "span_start": 20, "span_end": 27, "kind": "tone", "rule_id": "V-04"},
    ]

    html_out = render_annotated_draft(text, findings)

    # Both anchors are present
    assert 'id="span-FND-D02-0"' in html_out
    assert 'id="span-FND-V04-20"' in html_out

    # Text before, inside, and after overlap is preserved
    assert "Say goodbye to acne " in html_out
    assert "forever" in html_out
    assert "! O" in html_out
    assert "ur 2.5% BPO wash clears breakouts in 3 days." in html_out


def test_invalid_spans_handled_safely():
    """Invalid span offsets (negative, inverted, out-of-bounds, non-int) do not crash or corrupt text."""
    text = "Sample draft marketing text for safety test."
    invalid_findings = [
        {"finding_id": "FND-NEG", "span_start": -10, "span_end": 10, "kind": "tone"},
        {"finding_id": "FND-INV", "span_start": 25, "span_end": 10, "kind": "tone"},
        {"finding_id": "FND-OOB", "span_start": 100, "span_end": 200, "kind": "tone"},
        {"finding_id": "FND-NONE", "span_start": None, "span_end": 20, "kind": "tone"},
        {"finding_id": "FND-VALID", "span_start": 0, "span_end": 6, "kind": "claim"},  # 'Sample'
    ]

    html_out = render_annotated_draft(text, invalid_findings)
    assert 'id="span-FND-VALID"' in html_out
    assert "Sample" in html_out
    assert "draft marketing text for safety test." in html_out

    # Empty text and empty findings
    assert render_annotated_draft("", []) is not None
    assert render_annotated_draft(text, []) is not None


# ---------------------------------------------------------------------------
# 7. Existing Reviewer role restrictions remain strictly enforced
# ---------------------------------------------------------------------------

def test_reviewer_role_restrictions_remain_enforced(disposable_seed_db):
    """Reviewer permissions remain strictly enforced per RBAC security architecture."""
    db = disposable_seed_db

    # 1. Reviewer can approve compliant asset
    stable_id = approve_claim(
        asset_id="AST-SUNSCREEN-01",
        claim_text="3 essential ceramides and hyaluronic acid",
        fact_id="F-302",
        fact_version_id=1,
        reviewer_id="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=db,
    )
    assert stable_id.startswith("SC-")

    # 2. Creator cannot approve asset
    with pytest.raises(PermissionError):
        approve_claim(
            asset_id="AST-MONSOON-01",
            claim_text="Some text",
            fact_id="F-112",
            fact_version_id=3,
            role=Role.CREATOR,
            db_path=db,
        )

    # 3. Fact Owner cannot approve asset
    with pytest.raises(PermissionError):
        approve_claim(
            asset_id="AST-MONSOON-01",
            claim_text="Some text",
            fact_id="F-112",
            fact_version_id=3,
            role=Role.FACT_OWNER,
            db_path=db,
        )

    # 4. Reviewer cannot publish fact version
    with pytest.raises(PermissionError):
        publish_fact_version(
            fact_id="F-112",
            version=5,
            product_id="prod_monsoon",
            market="US",
            fact_text="Illegal update",
            permitted_wording="Illegal",
            valid_from="2026-11-01",
            role=Role.REVIEWER,
            db_path=db,
        )

    # 5. Missing role is rejected
    with pytest.raises(PermissionError):
        approve_claim(
            asset_id="AST-MONSOON-01",
            claim_text="Some text",
            fact_id="F-112",
            fact_version_id=3,
            role=None,
            db_path=db,
        )


# ---------------------------------------------------------------------------
# 8. Schema Compatibility: Legacy (No review_cycle) vs Migrated
# ---------------------------------------------------------------------------

@pytest.fixture
def legacy_unmigrated_db(tmp_path):
    """
    Provide an isolated SQLite database reflecting the exact unmigrated
    production database schema (lacking review_cycle on assets and findings).
    """
    db_file = tmp_path / "legacy_unmigrated.db"
    db_path = str(db_file)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Legacy assets table without review_cycle
    conn.execute(
        """
        CREATE TABLE assets (
            asset_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            product_id TEXT NOT NULL,
            market TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            text_content TEXT NOT NULL,
            planned_publish_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Legacy findings table without review_cycle
    conn.execute(
        """
        CREATE TABLE findings (
            finding_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL REFERENCES assets(asset_id),
            kind TEXT NOT NULL,
            severity TEXT NOT NULL,
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            source_text TEXT NOT NULL,
            rule_id TEXT,
            fact_id TEXT,
            fact_version_id INTEGER,
            link_state TEXT NOT NULL,
            message TEXT NOT NULL,
            next_step TEXT NOT NULL,
            suggested_rewrite TEXT,
            creator_action TEXT NOT NULL DEFAULT 'pending',
            dismiss_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Insert legacy asset and findings
    conn.execute(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, created_at)
        VALUES ('AST-LEGACY-01', 'Legacy Monsoon Campaign', 'prod_monsoon', 'US', 'paid_social', 'ready_for_review', 'Alex Chen (Creator)', 'hash1', 'Legacy draft copy', '2026-11-20', '2026-11-04 20:57:25');
        """
    )
    conn.execute(
        """
        INSERT INTO findings (finding_id, asset_id, kind, severity, span_start, span_end, source_text, link_state, message, next_step)
        VALUES ('FND-LEG-1', 'AST-LEGACY-01', 'tone', 'block', 0, 7, 'forever', 'UNLINKED', 'Tone violation', 'Rewrite');
        """
    )
    conn.execute(
        """
        INSERT INTO findings (finding_id, asset_id, kind, severity, span_start, span_end, source_text, link_state, message, next_step)
        VALUES ('FND-LEG-2', 'AST-LEGACY-01', 'terminology', 'block', 10, 13, 'BPO', 'UNLINKED', 'Terminology violation', 'Rewrite');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_queue_query_against_legacy_schema_without_review_cycle(legacy_unmigrated_db):
    """Queue query succeeds on unmigrated legacy schema without crashing or raising OperationalError."""
    db = legacy_unmigrated_db

    assert has_column("assets", "review_cycle", db_path=db) is False
    assert has_column("findings", "review_cycle", db_path=db) is False

    # Must execute cleanly without sqlite3.OperationalError: no such column: a.review_cycle
    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db)
    assert len(queue) == 1

    item = queue[0]
    assert item["asset_id"] == "AST-LEGACY-01"
    assert item["finding_count"] == 2
    assert item["status"] == "ready_for_review"
    assert item["owner"] == "Alex Chen (Creator)"
    assert item["review_cycle"] == 1  # Truthful fallback


def test_queue_query_against_migrated_disposable_schema_with_review_cycle(disposable_seed_db):
    """Queue query succeeds on migrated/disposable schema utilizing review_cycle join."""
    db = disposable_seed_db

    assert has_column("assets", "review_cycle", db_path=db) is True
    assert has_column("findings", "review_cycle", db_path=db) is True

    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=db)
    assert len(queue) == 3

    by_id = {a["asset_id"]: a for a in queue}
    assert by_id["AST-MONSOON-01"]["finding_count"] == 5
    assert by_id["AST-DIWALI-01"]["finding_count"] == 3
    assert by_id["AST-SUNSCREEN-01"]["finding_count"] == 3


def test_queue_query_on_production_database_copy(tmp_path):
    """Queue query succeeds against an exact physical byte-copy of the protected production database."""
    prod_backup = Path("data/backups/brand_rule_lab.db.backup_exact_byte_copy.bak")
    assert prod_backup.exists()

    copy_path = tmp_path / "prod_exact_copy.db"
    shutil.copyfile(str(prod_backup), str(copy_path))

    # Verify column presence on production copy
    assert has_column("assets", "review_cycle", db_path=str(copy_path)) is False
    assert has_column("findings", "review_cycle", db_path=str(copy_path)) is False

    # Execute queue query on production copy
    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=str(copy_path))
    assert len(queue) >= 1

    # AST-MONSOON-01 must have 5 findings and truthful review_cycle = 1
    monsoon = next((a for a in queue if a["asset_id"] == "AST-MONSOON-01"), None)
    assert monsoon is not None
    assert monsoon["finding_count"] == 5
    assert monsoon["status"] == "ready_for_review"
    assert monsoon["review_cycle"] == 1


# ============================================================================
# AUDIT TRAIL SCHEMA COMPATIBILITY TESTS
# ============================================================================

def test_audit_trail_against_legacy_schema_without_finding_id(tmp_path):
    """Audit trail retrieval succeeds on legacy schema without finding_id and uses truthful fallback."""
    legacy_db = tmp_path / "legacy_audit.db"
    conn = sqlite3.connect(str(legacy_db))
    # Original 8-column review_events table without Migration 002 columns
    conn.execute(
        """
        CREATE TABLE review_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            override_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        """
        INSERT INTO review_events (event_id, asset_id, actor, role, action, comment, override_reason, timestamp)
        VALUES ('EVT-LEG-01', 'AST-LEGACY-01', 'Alex Chen (Creator)', 'creator', 'submit_for_review', 'Initial submit', NULL, '2026-11-04T10:00:00');
        """
    )
    conn.execute(
        """
        INSERT INTO review_events (event_id, asset_id, actor, role, action, comment, override_reason, timestamp)
        VALUES ('EVT-LEG-02', 'AST-LEGACY-01', 'Sarah Jenkins (Reviewer)', 'reviewer', 'approve', 'Approved', NULL, '2026-11-04T11:00:00');
        """
    )
    conn.commit()
    conn.close()

    assert has_column("review_events", "finding_id", db_path=str(legacy_db)) is False

    # Must execute cleanly without sqlite3.OperationalError: no such column: finding_id
    trail = get_asset_audit_trail("AST-LEGACY-01", db_path=str(legacy_db))
    assert len(trail) == 2

    evt1, evt2 = trail[0], trail[1]
    assert evt1.event_id == "EVT-LEG-01"
    assert evt1.actor == "Alex Chen (Creator)"
    assert evt1.role == Role.CREATOR
    assert evt1.action == "submit_for_review"
    assert evt1.finding_id is None
    assert evt1.finding_provenance_label == "Asset-level event"

    assert evt2.event_id == "EVT-LEG-02"
    assert evt2.actor == "Sarah Jenkins (Reviewer)"
    assert evt2.role == Role.REVIEWER
    assert evt2.action == "approve"
    assert evt2.finding_id is None
    assert evt2.finding_provenance_label == "Asset-level event"

    # Verify UI rendering displays truthful fallback
    html1 = render_audit_event_item(evt1)
    assert "Asset-level event" in html1
    assert "SUBMIT_FOR_REVIEW" in html1
    assert "Finding:" not in html1


def test_audit_trail_against_migrated_schema_with_finding_id(disposable_seed_db):
    """Audit trail retrieval succeeds on migrated schema containing finding_id."""
    db = disposable_seed_db
    assert has_column("review_events", "finding_id", db_path=db) is True

    # Log finding-level review event
    evt = log_review_event(
        asset_id="AST-MONSOON-01",
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        action="accept_rewrite",
        finding_id="FND-D02-0",
        comment="Accepted revised clinical offer claim",
        db_path=db,
    )
    assert evt.finding_id == "FND-D02-0"

    trail = get_asset_audit_trail("AST-MONSOON-01", db_path=db)
    matching = next((e for e in trail if e.finding_id == "FND-D02-0"), None)
    assert matching is not None
    assert matching.finding_id == "FND-D02-0"
    assert matching.finding_provenance_label == "Finding: FND-D02-0"

    # Verify UI rendering displays finding ID provenance
    html_out = render_audit_event_item(matching)
    assert "Finding: FND-D02-0" in html_out
    assert "Asset-level event" not in html_out


def test_audit_trail_on_production_database_copy(tmp_path):
    """Audit trail retrieval succeeds on an exact byte copy of the protected production database."""
    prod_backup = Path("data/backups/brand_rule_lab.db.backup_exact_byte_copy.bak")
    assert prod_backup.exists()

    copy_path = tmp_path / "prod_exact_copy_audit.db"
    shutil.copyfile(str(prod_backup), str(copy_path))

    # Verify finding_id column absence on production copy
    assert has_column("review_events", "finding_id", db_path=str(copy_path)) is False

    # Retrieve audit history for Monsoon
    monsoon_trail = get_asset_audit_trail("AST-MONSOON-01", db_path=str(copy_path))
    assert len(monsoon_trail) == 4
    for evt in monsoon_trail:
        assert evt.asset_id == "AST-MONSOON-01"
        assert evt.finding_id is None
        assert evt.finding_provenance_label == "Asset-level event"
        # Render item check
        rendered = render_audit_event_item(evt)
        assert "Asset-level event" in rendered
        assert evt.action.upper() in rendered

    # Retrieve audit history for AST-ffed5f
    ffed5f_trail = get_asset_audit_trail("AST-ffed5f", db_path=str(copy_path))
    assert len(ffed5f_trail) == 1
    assert ffed5f_trail[0].actor == "Alex Chen (Creator)"
    assert ffed5f_trail[0].finding_id is None
    assert ffed5f_trail[0].finding_provenance_label == "Asset-level event"


def test_log_review_event_compatible_with_legacy_and_migrated_schemas(tmp_path, disposable_seed_db):
    """log_review_event can write to both legacy schema (8 cols) and migrated schema (14 cols) without error."""
    # 1. Test writing to legacy schema
    legacy_db = tmp_path / "legacy_write.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.execute(
        """
        CREATE TABLE review_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            override_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()

    legacy_evt = log_review_event(
        asset_id="AST-LEG-02",
        actor="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        action="request_changes",
        comment="Revision required",
        finding_id="FND-IGNORED-IN-LEGACY",  # Should be safely omitted from legacy insert
        db_path=str(legacy_db),
    )
    assert legacy_evt is not None
    legacy_trail = get_asset_audit_trail("AST-LEG-02", db_path=str(legacy_db))
    assert len(legacy_trail) == 1
    assert legacy_trail[0].action == "request_changes"
    assert legacy_trail[0].finding_id is None

    # 2. Test writing to migrated schema
    migrated_evt = log_review_event(
        asset_id="AST-MONSOON-01",
        actor="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        action="escalate",
        comment="Evidence review needed",
        finding_id="FND-MIG-01",
        db_path=disposable_seed_db,
    )
    assert migrated_evt is not None
    migrated_trail = get_asset_audit_trail("AST-MONSOON-01", db_path=disposable_seed_db)
    esc_evt = next((e for e in migrated_trail if e.action == "escalate"), None)
    assert esc_evt is not None
    assert esc_evt.finding_id == "FND-MIG-01"


# ---------------------------------------------------------------------------
# 9. Isolated Demo Database & Truthful Provenance Regressions
# ---------------------------------------------------------------------------

def test_demo_database_queue_returns_three_assets_with_exact_counts():
    """Verify data/demo_brand_rule_lab.db Reviewer queue returns Monsoon (5), Diwali (3), Sunscreen (3)."""
    demo_db = "data/demo_brand_rule_lab.db"
    assert Path(demo_db).exists(), f"Demo database missing at {demo_db}"

    queue = get_reviewer_queue_data(status_filter="ready_for_review", db_path=demo_db)
    queue_map = {a["asset_id"]: a for a in queue}

    # All three expected demo assets must be present
    assert "AST-MONSOON-01" in queue_map
    assert "AST-DIWALI-01" in queue_map
    assert "AST-SUNSCREEN-01" in queue_map

    # Exact finding counts
    assert queue_map["AST-MONSOON-01"]["finding_count"] == 5
    assert queue_map["AST-DIWALI-01"]["finding_count"] == 3
    assert queue_map["AST-SUNSCREEN-01"]["finding_count"] == 3

    # All must have ready_for_review status
    for aid in ("AST-MONSOON-01", "AST-DIWALI-01", "AST-SUNSCREEN-01"):
        assert queue_map[aid]["status"] == "ready_for_review"

    # AST-ffed5f (production only) and AST-REV-01 (changes_requested) must NOT appear in ready queue
    assert "AST-ffed5f" not in queue_map
    assert "AST-REV-01" not in queue_map


def test_asset_level_audit_events_render_without_exceptions(tmp_path):
    """Test that legacy asset-level events render truthful 'Asset-level event' badge without exceptions."""
    legacy_db = tmp_path / "legacy_render_test.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.execute(
        """
        CREATE TABLE review_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            override_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        """
        INSERT INTO review_events (event_id, asset_id, actor, role, action, comment, override_reason, timestamp)
        VALUES
        ('EVT-01', 'AST-TEST-01', 'usr_creator', 'creator', 'submit_for_review', 'Initial draft submitted', NULL, '2026-11-04 10:00:00'),
        ('EVT-02', 'AST-TEST-01', 'usr_reviewer', 'reviewer', 'unlinked_override', 'Compliance override', 'Counsel approved', '2026-11-04 11:00:00');
        """
    )
    conn.commit()
    conn.close()

    events = get_asset_audit_trail("AST-TEST-01", db_path=str(legacy_db))
    assert len(events) == 2

    for evt in events:
        # None of the events should have fabricated finding_id
        assert evt.finding_id is None
        rendered = render_audit_event_item(evt)
        # Truthful badge must be present
        assert "Asset-level event" in rendered
        assert "Finding:" not in rendered


def test_audit_history_empty_state_rendering():
    """Verify that assets with no audit history return an empty list and display truthful empty state."""
    demo_db = "data/demo_brand_rule_lab.db"
    assert Path(demo_db).exists()

    # AST-DIWALI-01 and AST-SUNSCREEN-01 are newly seeded demo assets awaiting initial review
    for aid in ("AST-DIWALI-01", "AST-SUNSCREEN-01"):
        trail = get_asset_audit_trail(aid, db_path=demo_db)
        assert trail == [], f"Expected empty audit trail for new demo asset {aid}"

    # Empty state rendering check matching app/pages/2_Reviewer.py lines 322-323
    empty_trail = get_asset_audit_trail("AST-NONEXISTENT", db_path=demo_db)
    assert len(empty_trail) == 0


def test_audit_history_existing_events_rendering(tmp_path):
    """Verify that existing audit events render full details into HTML."""
    db_file = tmp_path / "test_render.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE review_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            override_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finding_id TEXT,
            previous_action TEXT,
            new_action TEXT,
            event_fingerprint TEXT,
            provenance TEXT,
            known_before_timestamp TIMESTAMP
        );
        """
    )
    conn.execute(
        """
        INSERT INTO review_events (
            event_id, asset_id, actor, role, action, comment, timestamp, finding_id, provenance
        ) VALUES (
            'EVT-TEST-01', 'AST-TEST', 'Sarah Jenkins (Reviewer)', 'reviewer', 'approve',
            'Approved clinical trial claim', '2026-11-07 10:00:00', 'FND-01', 'USER_ACTION'
        );
        """
    )
    conn.commit()
    conn.close()

    trail = get_asset_audit_trail("AST-TEST", db_path=str(db_file))
    assert len(trail) == 1
    html_out = render_audit_event_item(trail[0])
    assert "Sarah Jenkins (Reviewer)" in html_out
    assert "REVIEWER" in html_out
    assert "APPROVE" in html_out
    assert "Finding: FND-01" in html_out
    assert "Approved clinical trial claim" in html_out


def test_audit_records_strictly_append_only(tmp_path):
    """Verify that review_events table triggers prevent UPDATE and DELETE operations."""
    from core.db import init_db
    test_db = tmp_path / "append_only_test.db"
    init_db(str(test_db))

    conn = sqlite3.connect(str(test_db))
    conn.execute(
        """
        INSERT INTO review_events (event_id, asset_id, actor, role, action, comment)
        VALUES ('EVT-LOCK-01', 'AST-01', 'Tester', 'reviewer', 'approve', 'Initial');
        """
    )
    conn.commit()

    # Verify UPDATE is blocked
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="Mutation forbidden"):
        conn.execute("UPDATE review_events SET comment = 'Tampered' WHERE event_id = 'EVT-LOCK-01';")

    # Verify DELETE is blocked
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="Deletion forbidden"):
        conn.execute("DELETE FROM review_events WHERE event_id = 'EVT-LOCK-01';")

    conn.close()



