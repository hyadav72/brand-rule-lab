"""
Brand Rule Lab — Phase 2 Regression & Invariant Test Suite
Tests:
1. Finding identity format, asset-scoping, and cycle-scoping.
2. Atomic CAS review-cycle transitions (concurrency & idempotency).
3. AST-ffed5f provenance, findings reconstruction, F-112 v3 linkage.
4. Effective submission snapshot creation and trigger immutability.
5. Creator decision audit logging with fingerprint deduplication.
6. Human-approved text integrity (capitalization and punctuation preservation).
"""

import concurrent.futures
import datetime
import hashlib
import shutil
import sqlite3
import pytest
from pathlib import Path

from core.audit import apply_creator_decision, get_asset_audit_trail, log_creator_decision, log_review_event
from core.cycles import get_asset_review_cycle, start_revision_cycle
from core.db import get_connection
from core.maintenance import MaintenanceManager
from core.migrations.runner import MigrationRunner
from core.models import ClaimSpan, ExtractedDoc, Finding, FindingKind, LinkState, Role, Severity
from core.reconstruct import reconstruct_submitted_text
from core.rules.engine import RuleEngine, make_finding_id
from core.snapshots import (
    create_submission,
    get_effective_snapshot,
    get_submission,
    save_effective_snapshot,
    save_original_snapshot,
    submit_draft,
)

PROD_DB_PATH = Path("data/brand_rule_lab.db")
EXPECTED_PROD_SHA256 = "3f6b4e75955408e044d2195e48002a8f774dec452f4e81ead29ae292f4bd2ecb"


@pytest.fixture
def disposable_migrated_db(tmp_path):
    """Provides a fresh disposable copy of production database migrated through 004."""
    disp_db = tmp_path / "disposable_test.db"
    shutil.copy2(PROD_DB_PATH, disp_db)

    mgr = MaintenanceManager(db_path=str(disp_db))
    token = mgr.enable(reason="Running Phase 2 tests on disposable copy")

    runner = MigrationRunner(db_path=str(disp_db), maintenance_mgr=mgr)
    runner.run(require_maintenance=True, maintenance_token=token)

    mgr.disable(token)
    return disp_db


# ============================================================================
# 1. FINDING IDENTITY SPECIFICATION & UNIQUENESS
# ============================================================================

def test_make_finding_id_format():
    """Verify finding IDs are correctly formatted with clean rule, span, asset, and cycle."""
    fid1 = make_finding_id("V-04", 20, "AST-MONSOON-01", review_cycle=1)
    assert fid1 == "FND-V04-20-MONSOON01-C1"

    fid2 = make_finding_id("T-12", 38, "AST-ffed5f", review_cycle=1)
    assert fid2 == "FND-T12-38-ffed5f-C1"

    fid3 = make_finding_id("C-01", 47, "AST-ffed5f", review_cycle=2)
    assert fid3 == "FND-C01-47-ffed5f-C2"

    fid4 = make_finding_id("D-02", 0, "AST-MONSOON-01", review_cycle=1)
    assert fid4 == "FND-D02-0-MONSOON01-C1"


def test_finding_identity_eliminates_cross_asset_collisions():
    """Identical rules at identical text spans on different assets must produce distinct finding IDs."""
    fid_asset_a = make_finding_id("T-12", 38, "AST-ASSET-AAA", review_cycle=1)
    fid_asset_b = make_finding_id("T-12", 38, "AST-ASSET-BBB", review_cycle=1)

    assert fid_asset_a != fid_asset_b
    assert "ASSETAAA" in fid_asset_a
    assert "ASSETBBB" in fid_asset_b


def test_finding_identity_preserves_historical_cycles():
    """A finding from review cycle 1 must have a different ID from review cycle 2."""
    fid_c1 = make_finding_id("V-04", 0, "AST-ffed5f", review_cycle=1)
    fid_c2 = make_finding_id("V-04", 0, "AST-ffed5f", review_cycle=2)

    assert fid_c1 != fid_c2
    assert fid_c1.endswith("-C1")
    assert fid_c2.endswith("-C2")


def test_rule_engine_emits_cycle_aware_finding_ids():
    """RuleEngine must emit asset- and cycle-aware finding IDs during evaluation."""
    engine = RuleEngine()
    demo_copy = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    doc = ExtractedDoc(text=demo_copy, pages=[demo_copy])
    claims = [
        ClaimSpan(text="clears breakouts in 3 days", start=48, end=74, product_alias="Monsoon Clear Skin")
    ]
    context = {
        "asset_id": "AST-CYCLE-TEST",
        "product": "prod_monsoon",
        "market": "US",
        "channel": "paid_social",
        "review_cycle": 3,
    }

    findings = engine.run_rules(doc, claims, context)
    assert len(findings) == 3

    for f in findings:
        assert "CYCLETEST" in f.finding_id
        assert f.finding_id.endswith("-C3")
        assert f.review_cycle == 3


# ============================================================================
# 2. ATOMIC CAS REVIEW CYCLE TRANSITIONS
# ============================================================================

def test_atomic_cas_transition_succeeds_for_changes_requested(disposable_migrated_db):
    """start_revision_cycle transitions 'changes_requested' to 'draft' and increments review_cycle."""
    with get_connection(str(disposable_migrated_db)) as conn:
        conn.execute(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-TEST-CAS', 'CAS Test', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen', 'hash', 'sample text', '2026-11-10', 1);
            """
        )
        conn.commit()

    success = start_revision_cycle("AST-TEST-CAS", db_path=str(disposable_migrated_db))
    assert success is True

    with get_connection(str(disposable_migrated_db)) as conn:
        row = conn.execute("SELECT status, review_cycle FROM assets WHERE asset_id = 'AST-TEST-CAS'").fetchone()
        assert row["status"] == "draft"
        assert row["review_cycle"] == 2


def test_atomic_cas_transition_fails_if_not_changes_requested(disposable_migrated_db):
    """Calling start_revision_cycle on an asset in 'draft' or 'approved' must fail and not increment cycle."""
    with get_connection(str(disposable_migrated_db)) as conn:
        conn.execute(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-TEST-DRAFT', 'Draft Test', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'hash', 'sample text', '2026-11-10', 1);
            """
        )
        conn.commit()

    # Must return False
    success = start_revision_cycle("AST-TEST-DRAFT", db_path=str(disposable_migrated_db))
    assert success is False

    with get_connection(str(disposable_migrated_db)) as conn:
        row = conn.execute("SELECT status, review_cycle FROM assets WHERE asset_id = 'AST-TEST-DRAFT'").fetchone()
        assert row["status"] == "draft"
        assert row["review_cycle"] == 1  # Unchanged!


def test_concurrent_cas_transitions_prevent_duplicate_increments(disposable_migrated_db):
    """Multiple concurrent revision requests must result in exactly one successful increment."""
    with get_connection(str(disposable_migrated_db)) as conn:
        conn.execute(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-CONC-CAS', 'Concurrent CAS', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen', 'hash', 'sample text', '2026-11-10', 1);
            """
        )
        conn.commit()

    results = []

    def _call_cas():
        return start_revision_cycle("AST-CONC-CAS", db_path=str(disposable_migrated_db))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_call_cas) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Exactly one must succeed
    assert results.count(True) == 1
    assert results.count(False) == 7

    # Final cycle must be 2, not 9
    with get_connection(str(disposable_migrated_db)) as conn:
        row = conn.execute("SELECT status, review_cycle FROM assets WHERE asset_id = 'AST-CONC-CAS'").fetchone()
        assert row["status"] == "draft"
        assert row["review_cycle"] == 2


# ============================================================================
# 3. AST-ffed5f PROVENANCE & LINEAGE RECONSTRUCTION
# ============================================================================

def test_ast_ffed5f_findings_reconstructed_and_linked(disposable_migrated_db):
    """Migration 004 must restore missing findings for AST-ffed5f and link C-01 to F-112 v3."""
    with get_connection(str(disposable_migrated_db)) as conn:
        findings = conn.execute(
            "SELECT * FROM findings WHERE asset_id = 'AST-ffed5f' ORDER BY span_start ASC"
        ).fetchall()

    assert len(findings) == 3

    # V-04 Finding
    f_v04 = findings[0]
    assert f_v04["finding_id"] == "FND-V04-0-ffed5f-C1"
    assert f_v04["rule_id"] == "V-04"
    assert f_v04["creator_action"] == "accepted"
    assert f_v04["review_cycle"] == 1

    # T-12 Finding
    f_t12 = findings[1]
    assert f_t12["finding_id"] == "FND-T12-38-ffed5f-C1"
    assert f_t12["rule_id"] == "T-12"
    assert f_t12["source_text"] == "BPO"
    assert f_t12["suggested_rewrite"] == "Benzoyl Peroxide"
    assert f_t12["creator_action"] == "accepted"
    assert f_t12["review_cycle"] == 1

    # C-01 Finding (Linked to F-112 v3)
    f_c01 = findings[2]
    assert f_c01["finding_id"] == "FND-C01-47-ffed5f-C1"
    assert f_c01["rule_id"] == "C-01"
    assert f_c01["fact_id"] == "F-112"
    assert f_c01["fact_version_id"] == 3
    assert f_c01["link_state"] == "LINKED"
    assert f_c01["suggested_rewrite"] == "Reduces breakouts in 4 weeks with twice-daily use."
    assert f_c01["creator_action"] == "edited"
    assert f_c01["review_cycle"] == 1


def test_ast_ffed5f_effective_snapshot_and_submission(disposable_migrated_db):
    """Migration 004 must record submission and effective snapshot for AST-ffed5f with exact provenance."""
    # Submission record
    sub = get_submission("AST-ffed5f", review_cycle=1, db_path=str(disposable_migrated_db))
    assert sub is not None
    assert sub["submission_id"] == "SUB-AST-ffed5f-C1"
    assert sub["submitted_by"] == "Alex Chen (Creator)"
    assert sub["submitted_at"] == "2026-11-05T18:49:29.564783"

    # Effective snapshot record
    eff = get_effective_snapshot("AST-ffed5f", review_cycle=1, db_path=str(disposable_migrated_db))
    assert eff is not None
    assert eff["snapshot_id"] == "SNAP-EFF-REC-AST-ffed5f-C1"
    assert eff["submission_id"] == "SUB-AST-ffed5f-C1"
    assert eff["captured_by"] == "MIGRATION_RECONSTRUCTION"
    assert eff["content_hash"] == "1b7e597d753eb44a649adb5d18d971c25915a2eaad7b2fb8efe5688d81fe73bc"

    # captured_at must NOT be the historical 2026-11-05 timestamp
    assert eff["captured_at"] != "2026-11-05T18:49:29.564783"


def test_ast_ffed5f_reconstructed_review_events(disposable_migrated_db):
    """Reconstructed audit events must possess provenance='MIGRATION_RECONSTRUCTION' and historical boundary."""
    trail = get_asset_audit_trail("AST-ffed5f", db_path=str(disposable_migrated_db))
    rec_events = [e for e in trail if e.provenance == "MIGRATION_RECONSTRUCTION"]

    assert len(rec_events) == 3

    for e in rec_events:
        assert e.actor == "Alex Chen (Creator)"
        assert e.role == Role.CREATOR
        assert e.action in ("accept_rewrite", "edit_rewrite")
        assert e.provenance == "MIGRATION_RECONSTRUCTION"
        assert e.known_before_timestamp == "2026-11-05T18:49:29.564783"
        # Actual timestamp is recent reconstruction time, not historical
        assert e.timestamp != "2026-11-05T18:49:29.564783"


# ============================================================================
# 4. HUMAN-APPROVED TEXT INTEGRITY
# ============================================================================

def test_ast_ffed5f_reconstructed_text_exact_match(disposable_migrated_db):
    """Reconstructed text from AST-ffed5f findings matches the effective text verbatim."""
    with get_connection(str(disposable_migrated_db)) as conn:
        # Get original text from snapshot
        orig_row = conn.execute(
            "SELECT original_text FROM asset_original_snapshots WHERE asset_id = 'AST-ffed5f'"
        ).fetchone()
        original_text = orig_row["original_text"]

        # Get findings
        findings_rows = conn.execute(
            "SELECT * FROM findings WHERE asset_id = 'AST-ffed5f' ORDER BY span_start ASC"
        ).fetchall()

    from core.models import Finding
    findings = [
        Finding(
            finding_id=r["finding_id"],
            asset_id=r["asset_id"],
            kind=FindingKind(r["kind"]),
            severity=Severity(r["severity"]),
            span_start=r["span_start"],
            span_end=r["span_end"],
            source_text=r["source_text"],
            rule_id=r["rule_id"],
            fact_id=r["fact_id"],
            fact_version_id=r["fact_version_id"],
            link_state=LinkState(r["link_state"]),
            message=r["message"],
            next_step=r["next_step"],
            suggested_rewrite=r["suggested_rewrite"],
            creator_action=r["creator_action"],
            dismiss_reason=r["dismiss_reason"],
            review_cycle=r["review_cycle"],
        )
        for r in findings_rows
    ]

    actions = {
        f.finding_id: {"action": f.creator_action, "text": f.suggested_rewrite}
        for f in findings
    }

    reconstructed = reconstruct_submitted_text(original_text, findings, actions)

    # Verbatim expected text: capital 'R' on Reduces, trailing '..'
    expected = (
        "Gentle daily wash for clearer-looking skin! "
        "Our 2.5% Benzoyl Peroxide wash "
        "Reduces breakouts in 4 weeks with twice-daily use.."
    )
    assert reconstructed == expected
    expected_hash = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert expected_hash == "1b7e597d753eb44a649adb5d18d971c25915a2eaad7b2fb8efe5688d81fe73bc"


# ============================================================================
# 5. CREATOR DECISION AUDIT LOGGING & DEDUPLICATION
# ============================================================================

def test_log_creator_decision_idempotent(disposable_migrated_db):
    """Calling log_creator_decision with identical fingerprint must not produce duplicate records."""
    event1 = log_creator_decision(
        asset_id="AST-ffed5f",
        actor="Alex Chen (Creator)",
        action="accept_rewrite",
        finding_id="FND-V04-0-ffed5f-C1",
        previous_action="pending",
        new_action="accepted",
        comment="Test accept",
        event_fingerprint="FPR-TEST-DEDUP-001",
        db_path=str(disposable_migrated_db),
    )
    assert event1 is not None

    # Call again with identical fingerprint
    event2 = log_creator_decision(
        asset_id="AST-ffed5f",
        actor="Alex Chen (Creator)",
        action="accept_rewrite",
        finding_id="FND-V04-0-ffed5f-C1",
        previous_action="pending",
        new_action="accepted",
        comment="Test accept duplicate",
        event_fingerprint="FPR-TEST-DEDUP-001",
        db_path=str(disposable_migrated_db),
    )
    assert event2 is None  # Skipped!

    with get_connection(str(disposable_migrated_db)) as conn:
        count = conn.execute(
            "SELECT count(*) FROM review_events WHERE event_fingerprint = 'FPR-TEST-DEDUP-001'"
        ).fetchone()[0]
        assert count == 1


# ============================================================================
# 6. IMMUTABILITY TRIGGER INTEGRITY
# ============================================================================

def test_effective_snapshots_table_is_immutable(disposable_migrated_db):
    """Mutating or deleting records in asset_effective_snapshots must raise an SQLite ABORT exception."""
    with get_connection(str(disposable_migrated_db)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="Mutation forbidden"):
            conn.execute(
                "UPDATE asset_effective_snapshots SET effective_text = 'tampered' WHERE asset_id = 'AST-ffed5f';"
            )

        with pytest.raises(sqlite3.DatabaseError, match="Deletion forbidden"):
            conn.execute(
                "DELETE FROM asset_effective_snapshots WHERE asset_id = 'AST-ffed5f';"
            )


def test_asset_submissions_table_is_immutable(disposable_migrated_db):
    """Mutating or deleting records in asset_submissions must raise an SQLite ABORT exception."""
    with get_connection(str(disposable_migrated_db)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="Mutation forbidden"):
            conn.execute(
                "UPDATE asset_submissions SET submitted_by = 'tampered' WHERE asset_id = 'AST-ffed5f';"
            )

        with pytest.raises(sqlite3.DatabaseError, match="Deletion forbidden"):
            conn.execute(
                "DELETE FROM asset_submissions WHERE asset_id = 'AST-ffed5f';"
            )


# ============================================================================
# 7. TRANSACTION ATOMICITY & WORKFLOW INTEGRITY
# ============================================================================

def test_creator_action_updates_finding_and_audit_event_together(disposable_migrated_db):
    """
    Creator accept, edit and dismiss must update the findings row and record the matching
    review_events audit entry inside the same SQLite transaction.
    """
    db = str(disposable_migrated_db)

    # 1. Accept action
    finding_acc = Finding(
        finding_id="FND-V04-0-ffed5f-C1",
        asset_id="AST-ffed5f",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=28,
        source_text="Say goodbye to acne forever!",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Tone violation",
        suggested_rewrite="Gentle daily wash for clearer-looking skin!",
        creator_action="pending",
        review_cycle=1,
    )
    evt_acc = apply_creator_decision(
        finding=finding_acc,
        action="accepted",
        new_text=finding_acc.suggested_rewrite,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        db_path=db,
    )
    assert evt_acc is not None
    assert evt_acc.action == "accept_rewrite"
    assert evt_acc.new_action == "accepted"

    with get_connection(db) as conn:
        f_row = conn.execute("SELECT creator_action, suggested_rewrite FROM findings WHERE finding_id = 'FND-V04-0-ffed5f-C1'").fetchone()
        assert f_row["creator_action"] == "accepted"
        assert f_row["suggested_rewrite"] == "Gentle daily wash for clearer-looking skin!"
        e_row = conn.execute("SELECT action, new_action FROM review_events WHERE finding_id = 'FND-V04-0-ffed5f-C1' AND new_action = 'accepted'").fetchone()
        assert e_row is not None
        assert e_row["action"] == "accept_rewrite"

    # 2. Edit action
    finding_edit = Finding(
        finding_id="FND-C01-47-ffed5f-C1",
        asset_id="AST-ffed5f",
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=47,
        span_end=73,
        source_text="clears breakouts in 3 days",
        rule_id="C-01",
        fact_id="F-112",
        fact_version_id=3,
        link_state=LinkState.LINKED,
        message="Claim mismatch",
        suggested_rewrite="reduces breakouts in 4 weeks",
        creator_action="pending",
        review_cycle=1,
    )
    custom_edit = "Reduces breakouts in 4 weeks with twice-daily use."
    evt_edit = apply_creator_decision(
        finding=finding_edit,
        action="edited",
        new_text=custom_edit,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        db_path=db,
    )
    assert evt_edit is not None
    assert evt_edit.action == "edit_rewrite"
    assert evt_edit.new_action == "edited"

    with get_connection(db) as conn:
        f_row = conn.execute("SELECT creator_action, suggested_rewrite FROM findings WHERE finding_id = 'FND-C01-47-ffed5f-C1'").fetchone()
        assert f_row["creator_action"] == "edited"
        assert f_row["suggested_rewrite"] == custom_edit
        e_row = conn.execute("SELECT action, new_action FROM review_events WHERE finding_id = 'FND-C01-47-ffed5f-C1' AND new_action = 'edited'").fetchone()
        assert e_row is not None
        assert e_row["action"] == "edit_rewrite"

    # 3. Dismiss action
    finding_dism = Finding(
        finding_id="FND-T12-38-ffed5f-C1",
        asset_id="AST-ffed5f",
        kind=FindingKind.TERMINOLOGY,
        severity=Severity.BLOCK,
        span_start=38,
        span_end=41,
        source_text="BPO",
        rule_id="T-12",
        link_state=LinkState.UNLINKED,
        message="Prohibited abbreviation",
        suggested_rewrite="Benzoyl Peroxide",
        creator_action="pending",
        review_cycle=1,
    )
    dismiss_note = "Approved Exception Granted | Medical director sign-off on packaging"
    evt_dism = apply_creator_decision(
        finding=finding_dism,
        action="dismissed",
        dismiss_reason=dismiss_note,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        db_path=db,
    )
    assert evt_dism is not None
    assert evt_dism.action == "dismiss_finding"
    assert evt_dism.new_action == "dismissed"

    with get_connection(db) as conn:
        f_row = conn.execute("SELECT creator_action, dismiss_reason FROM findings WHERE finding_id = 'FND-T12-38-ffed5f-C1'").fetchone()
        assert f_row["creator_action"] == "dismissed"
        assert f_row["dismiss_reason"] == dismiss_note
        e_row = conn.execute("SELECT action, new_action FROM review_events WHERE finding_id = 'FND-T12-38-ffed5f-C1' AND new_action = 'dismissed'").fetchone()
        assert e_row is not None
        assert e_row["action"] == "dismiss_finding"


def test_creator_action_rollback_on_failure(disposable_migrated_db):
    """
    If a failure occurs during an individual Creator action, both the finding mutation
    and the review event audit log write must be rolled back completely.
    """
    db = str(disposable_migrated_db)

    with get_connection(db) as conn:
        f_before = conn.execute("SELECT * FROM findings WHERE finding_id = 'FND-V04-0-ffed5f-C1'").fetchone()
        evt_count_before = conn.execute("SELECT count(*) FROM review_events WHERE finding_id = 'FND-V04-0-ffed5f-C1'").fetchone()[0]

    finding = Finding(
        finding_id="FND-V04-0-ffed5f-C1",
        asset_id="AST-ffed5f",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=28,
        source_text="Say goodbye to acne forever!",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Tone violation",
        suggested_rewrite="Gentle daily wash for clearer-looking skin!",
        creator_action="pending",
        review_cycle=1,
    )

    with pytest.raises(RuntimeError, match="Simulated failure after finding update"):
        apply_creator_decision(
            finding=finding,
            action="accepted",
            new_text="Should never persist",
            actor="Alex Chen (Creator)",
            role=Role.CREATOR,
            db_path=db,
            _fail_after_finding=True,
        )

    with get_connection(db) as conn:
        f_after = conn.execute("SELECT * FROM findings WHERE finding_id = 'FND-V04-0-ffed5f-C1'").fetchone()
        evt_count_after = conn.execute("SELECT count(*) FROM review_events WHERE finding_id = 'FND-V04-0-ffed5f-C1'").fetchone()[0]

        assert f_after["creator_action"] == f_before["creator_action"]
        assert f_after["suggested_rewrite"] == f_before["suggested_rewrite"]
        assert evt_count_after == evt_count_before


def test_submission_pipeline_rollback_at_every_stage(disposable_migrated_db):
    """
    Simulate a failure at every stage of the 6-stage submission pipeline:
    1. Finding inserts/updates
    2. Original snapshot creation
    3. Submission record creation
    4. Effective snapshot creation
    5. Asset text and status update
    6. Submission audit event
    Every failure must roll back all preceding writes, leaving zero orphaned records.
    """
    db = str(disposable_migrated_db)

    with get_connection(db) as conn:
        conn.execute("""
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-ATOMIC-TEST', 'Atomic Test Asset', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen (Creator)', 'orig_hash', 'Original text before submit', '2026-11-10', 1);
        """)

    sample_finding = Finding(
        finding_id="FND-V04-0-ATOMIC-C1",
        asset_id="AST-ATOMIC-TEST",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=10,
        source_text="Violating",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Violation",
        suggested_rewrite="Clean text",
        creator_action="pending",
        review_cycle=1,
    )
    actions = {sample_finding.finding_id: {"action": "accepted", "text": "Clean text"}}

    # Test failure at each of the 6 stages
    for stage in [1, 2, 3, 4, 5, 6]:
        with pytest.raises(RuntimeError, match=f"Simulated failure at Stage {stage}"):
            submit_draft(
                asset_id="AST-ATOMIC-TEST",
                original_text="Original text before submit",
                submitted_text="Reconstructed submitted text",
                findings=[sample_finding],
                actions=actions,
                actor_name="Alex Chen (Creator)",
                role=Role.CREATOR,
                review_cycle=1,
                db_path=db,
                _fail_at_stage=stage,
            )

        # Verify absolute rollback across all tables
        with get_connection(db) as conn:
            f_count = conn.execute("SELECT count(*) FROM findings WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()[0]
            assert f_count == 0, f"Stage {stage} failure left findings un-rolled back!"

            snap_orig = conn.execute("SELECT count(*) FROM asset_original_snapshots WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()[0]
            assert snap_orig == 0, f"Stage {stage} failure left original snapshot committed!"

            sub_count = conn.execute("SELECT count(*) FROM asset_submissions WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()[0]
            assert sub_count == 0, f"Stage {stage} failure left submission record committed!"

            snap_eff = conn.execute("SELECT count(*) FROM asset_effective_snapshots WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()[0]
            assert snap_eff == 0, f"Stage {stage} failure left effective snapshot committed!"

            asset_row = conn.execute("SELECT status, text_content FROM assets WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()
            assert asset_row["status"] == "draft", f"Stage {stage} failure modified asset status!"
            assert asset_row["text_content"] == "Original text before submit", f"Stage {stage} failure modified asset text!"

            evt_count = conn.execute("SELECT count(*) FROM review_events WHERE asset_id = 'AST-ATOMIC-TEST'").fetchone()[0]
            assert evt_count == 0, f"Stage {stage} failure left audit event committed!"


def test_successful_submission_persists_all_records(disposable_migrated_db):
    """
    A successful submission must persist all 6 stages atomically:
    findings, original snapshot, submission, effective snapshot, asset status, and review event.
    """
    db = str(disposable_migrated_db)

    with get_connection(db) as conn:
        conn.execute("""
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-SUCCESS-TEST', 'Success Asset', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen (Creator)', 'orig_hash', 'Original raw text', '2026-11-10', 1);
        """)

    sample_finding = Finding(
        finding_id="FND-V04-0-SUCCESS-C1",
        asset_id="AST-SUCCESS-TEST",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=10,
        source_text="Bad tone text",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Tone issue",
        suggested_rewrite="Gentle tone text",
        creator_action="pending",
        review_cycle=1,
    )
    actions = {sample_finding.finding_id: {"action": "accepted", "text": "Gentle tone text"}}

    res = submit_draft(
        asset_id="AST-SUCCESS-TEST",
        original_text="Original raw text",
        submitted_text="Gentle tone text",
        findings=[sample_finding],
        actions=actions,
        actor_name="Alex Chen (Creator)",
        role=Role.CREATOR,
        review_cycle=1,
        db_path=db,
    )

    assert res["submission_id"] == "SUB-AST-SUCCESS-TEST-C1"
    assert res["orig_snapshot_id"] == "SNAP-AST-SUCCESS-TEST"
    assert res["eff_snapshot_id"] == "SNAP-EFF-AST-SUCCESS-TEST-C1"
    assert res["review_cycle"] == 1

    with get_connection(db) as conn:
        # 1. Findings
        f_row = conn.execute("SELECT creator_action, suggested_rewrite FROM findings WHERE finding_id = 'FND-V04-0-SUCCESS-C1'").fetchone()
        assert f_row["creator_action"] == "accepted"
        assert f_row["suggested_rewrite"] == "Gentle tone text"

        # 2. Original snapshot
        orig_row = conn.execute("SELECT original_text, content_hash FROM asset_original_snapshots WHERE asset_id = 'AST-SUCCESS-TEST'").fetchone()
        assert orig_row["original_text"] == "Original raw text"
        assert orig_row["content_hash"] == hashlib.sha256("Original raw text".encode("utf-8")).hexdigest()

        # 3. Submission
        sub_row = conn.execute("SELECT review_cycle, submitted_by FROM asset_submissions WHERE asset_id = 'AST-SUCCESS-TEST'").fetchone()
        assert sub_row["review_cycle"] == 1
        assert sub_row["submitted_by"] == "Alex Chen (Creator)"

        # 4. Effective snapshot
        eff_row = conn.execute("SELECT effective_text, content_hash FROM asset_effective_snapshots WHERE asset_id = 'AST-SUCCESS-TEST'").fetchone()
        assert eff_row["effective_text"] == "Gentle tone text"
        assert eff_row["content_hash"] == hashlib.sha256("Gentle tone text".encode("utf-8")).hexdigest()

        # 5. Asset status & copy
        asset_row = conn.execute("SELECT status, text_content FROM assets WHERE asset_id = 'AST-SUCCESS-TEST'").fetchone()
        assert asset_row["status"] == "ready_for_review"
        assert asset_row["text_content"] == "Gentle tone text"

        # 6. Audit event
        evt_row = conn.execute("SELECT action, role, actor FROM review_events WHERE asset_id = 'AST-SUCCESS-TEST' AND action = 'submit_for_review'").fetchone()
        assert evt_row["role"] == "creator"
        assert evt_row["actor"] == "Alex Chen (Creator)"


def test_creator_decision_streamlit_rerun_deduplication(disposable_migrated_db):
    """
    Streamlit page reruns must not create duplicate audit events.
    The first invocation records the decision; the second is cleanly skipped.
    """
    db = str(disposable_migrated_db)
    finding = Finding(
        finding_id="FND-V04-0-ffed5f-C1",
        asset_id="AST-ffed5f",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=28,
        source_text="Say goodbye to acne forever!",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Tone violation",
        suggested_rewrite="Gentle daily wash for clearer-looking skin!",
        creator_action="pending",
        review_cycle=1,
    )

    evt1 = apply_creator_decision(
        finding=finding,
        action="accepted",
        new_text=finding.suggested_rewrite,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        event_fingerprint="FPR-RERUN-TEST-UNIQUE",
        db_path=db,
    )
    assert evt1 is not None

    # Simulate immediate Streamlit rerun
    evt2 = apply_creator_decision(
        finding=finding,
        action="accepted",
        new_text=finding.suggested_rewrite,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        event_fingerprint="FPR-RERUN-TEST-UNIQUE",
        db_path=db,
    )
    assert evt2 is None

    with get_connection(db) as conn:
        count = conn.execute("SELECT count(*) FROM review_events WHERE event_fingerprint = 'FPR-RERUN-TEST-UNIQUE'").fetchone()[0]
        assert count == 1


def test_revision_cycle_and_historical_findings_preserved(disposable_migrated_db):
    """
    Existing revision-cycle behavior and historical findings must remain fully intact.
    Transitioning cycle increments review_cycle, and findings from prior cycles coexist.
    """
    db = str(disposable_migrated_db)

    with get_connection(db) as conn:
        conn.execute("""
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date, review_cycle)
            VALUES ('AST-HIST-PRESERVE', 'Preserve Test Asset', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen (Creator)', 'orig_hash', 'Cycle 1 copy', '2026-11-10', 1);
        """)

    # Cycle 1 finding
    f_c1 = Finding(
        finding_id="FND-V04-0-PRESERVE-C1",
        asset_id="AST-HIST-PRESERVE",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=10,
        source_text="Tone 1",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Cycle 1 tone",
        suggested_rewrite="Cycle 1 rewrite",
        creator_action="accepted",
        review_cycle=1,
    )
    apply_creator_decision(finding=f_c1, action="accepted", role=Role.CREATOR, db_path=db)

    # Explicit revision request
    transitioned = start_revision_cycle("AST-HIST-PRESERVE", db_path=db)
    assert transitioned is True

    new_cycle = get_asset_review_cycle("AST-HIST-PRESERVE", db_path=db)
    assert new_cycle == 2

    # Cycle 2 finding
    f_c2 = Finding(
        finding_id="FND-V04-0-PRESERVE-C2",
        asset_id="AST-HIST-PRESERVE",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=10,
        source_text="Tone 2",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Cycle 2 tone",
        suggested_rewrite="Cycle 2 rewrite",
        creator_action="edited",
        review_cycle=2,
    )
    apply_creator_decision(finding=f_c2, action="edited", new_text="Cycle 2 rewrite custom", role=Role.CREATOR, db_path=db)

    with get_connection(db) as conn:
        rows = conn.execute("SELECT finding_id, review_cycle, creator_action, suggested_rewrite FROM findings WHERE asset_id = 'AST-HIST-PRESERVE' ORDER BY review_cycle ASC").fetchall()
        assert len(rows) == 2
        assert rows[0]["finding_id"] == "FND-V04-0-PRESERVE-C1"
        assert rows[0]["review_cycle"] == 1
        assert rows[0]["creator_action"] == "accepted"
        assert rows[1]["finding_id"] == "FND-V04-0-PRESERVE-C2"
        assert rows[1]["review_cycle"] == 2
        assert rows[1]["creator_action"] == "edited"
