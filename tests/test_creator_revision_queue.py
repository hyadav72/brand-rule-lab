"""
Brand Rule Lab — Creator Revision Queue Workflow (BLK-02) Regression Tests
Owned by Agent A4 & A1.

Tests required by BLK-02:
1. Selecting a revision-queue asset loads the correct draft.
2. The correct current-cycle findings are loaded.
3. Previously saved decisions and edited wording are restored.
4. Finding IDs and review-cycle identity remain unchanged during loading.
5. A Creator can revise and resubmit successfully.
6. A non-Creator cannot perform Creator actions.
7. Failed loading or failed submission does not leave partially updated state.
8. Existing review-cycle and atomic-submission tests remain passing.
"""

import pytest
import sqlite3
import shutil
from pathlib import Path

from core.audit import apply_creator_decision, get_asset_audit_trail
from core.cycles import get_asset_review_cycle, load_revision_asset, start_revision_cycle
from core.db import get_connection
from core.maintenance import MaintenanceManager
from core.migrations.runner import MigrationRunner
from core.models import (
    CreatorActionState,
    ExtractedDoc,
    Finding,
    FindingKind,
    LinkState,
    Role,
    Severity,
)
from core.reconstruct import get_reconstruction_base_text, reconstruct_submitted_text
from core.snapshots import (
    get_effective_snapshot,
    get_original_snapshot,
    get_submission,
    save_effective_snapshot,
    save_original_snapshot,
    submit_draft,
)


PROD_DB_PATH = Path("data/brand_rule_lab.db")


@pytest.fixture
def disposable_db(tmp_path):
    """Provide a fresh disposable copy of production database migrated through 004."""
    disp_db = tmp_path / "disposable_rev_test.db"
    shutil.copy2(PROD_DB_PATH, disp_db)

    mgr = MaintenanceManager(db_path=str(disp_db))
    token = mgr.enable(reason="Running Revision Queue BLK-02 tests on disposable copy")

    runner = MigrationRunner(db_path=str(disp_db), maintenance_mgr=mgr)
    runner.run(require_maintenance=True, maintenance_token=token)

    mgr.disable(token)
    return str(disp_db)


def test_revision_queue_loads_correct_draft(disposable_db):
    """Selecting a revision-queue asset loads the correct draft text and metadata."""
    db = disposable_db
    asset_id = "AST-REV-DRAFT-01"
    effective_text = "Gentle daily wash for clearer-looking skin! Our 2.5% Benzoyl Peroxide wash."

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, ?, ?, ?, ?, 'changes_requested', 'Alex Chen (Creator)', 'hash_rev_01', ?, '2026-11-15', 1);
            """,
            (asset_id, "Monsoon Revision Draft", "prod_monsoon", "US", "paid_social", effective_text),
        )
        conn.commit()

    loaded = load_revision_asset(asset_id, db_path=db)

    assert loaded["asset"]["asset_id"] == asset_id
    assert loaded["asset"]["status"] == "changes_requested"
    assert loaded["doc"].text == effective_text
    assert loaded["context"]["product"] == "prod_monsoon"
    assert loaded["context"]["market"] == "US"
    assert loaded["context"]["channel"] == "paid_social"
    assert loaded["context"]["planned_publish_date"] == "2026-11-15"
    assert loaded["review_cycle"] == 1


def test_revision_queue_loads_current_cycle_findings(disposable_db):
    """The correct current-cycle findings are loaded for the asset."""
    db = disposable_db
    asset_id = "AST-REV-FINDINGS-01"

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'Cycle Test', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen (Creator)', 'h1', 'Text', '2026-11-15', 2);
            """,
            (asset_id,),
        )
        # Cycle 1 finding
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, link_state, message, next_step, suggested_rewrite, creator_action, review_cycle
            ) VALUES ('FND-C1-01', ?, 'tone', 'block', 0, 5, 'word1', 'V-04', 'UNLINKED', 'msg1', 'step1', 'rew1', 'accepted', 1);
            """,
            (asset_id,),
        )
        # Cycle 2 findings
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, link_state, message, next_step, suggested_rewrite, creator_action, review_cycle
            ) VALUES
            ('FND-C2-01', ?, 'tone', 'block', 0, 5, 'word2', 'V-04', 'UNLINKED', 'msg2', 'step2', 'rew2', 'edited', 2),
            ('FND-C2-02', ?, 'terminology', 'block', 10, 15, 'word3', 'T-12', 'UNLINKED', 'msg3', 'step3', 'rew3', 'pending', 2);
            """,
            (asset_id, asset_id),
        )
        conn.commit()

    loaded = load_revision_asset(asset_id, db_path=db)
    findings = loaded["findings"]

    # Must load cycle 2 findings, not cycle 1
    assert len(findings) == 2
    fids = [f.finding_id for f in findings]
    assert "FND-C2-01" in fids
    assert "FND-C2-02" in fids
    assert "FND-C1-01" not in fids

    for f in findings:
        assert f.review_cycle == 2


def test_previously_saved_decisions_and_edited_wording_restored(disposable_db):
    """Previously saved creator decisions (accepted, edited, dismissed) and wording are fully restored."""
    db = disposable_db
    asset_id = "AST-REV-ACTIONS-01"

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'Action Test', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen (Creator)', 'h1', 'Text', '2026-11-15', 1);
            """,
            (asset_id,),
        )
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, fact_id, fact_version_id, link_state, message, next_step,
                suggested_rewrite, creator_action, dismiss_reason, review_cycle
            ) VALUES
            ('FND-ACT-01', ?, 'tone', 'block', 0, 7, 'forever', 'V-04', NULL, NULL, 'UNLINKED', 'msg', 'step', 'long-term', 'accepted', NULL, 1),
            ('FND-ACT-02', ?, 'terminology', 'block', 10, 13, 'BPO', 'T-12', NULL, NULL, 'UNLINKED', 'msg', 'step', 'Benzoyl Peroxide Wash 2.5%', 'edited', NULL, 1),
            ('FND-ACT-03', ?, 'claim', 'block', 20, 30, 'guaranteed', 'C-01', 'F-112', 3, 'LINKED', 'msg', 'step', NULL, 'dismissed', 'Approved Exception Granted | Note from legal', 1);
            """,
            (asset_id, asset_id, asset_id),
        )
        conn.commit()

    loaded = load_revision_asset(asset_id, db_path=db)
    actions = loaded["actions"]

    # FND-ACT-01: Accepted
    assert actions["FND-ACT-01"]["action"] == "accepted"
    assert actions["FND-ACT-01"]["text"] == "long-term"

    # FND-ACT-02: Custom edited
    assert actions["FND-ACT-02"]["action"] == "edited"
    assert actions["FND-ACT-02"]["text"] == "Benzoyl Peroxide Wash 2.5%"

    # FND-ACT-03: Dismissed with rationale
    assert actions["FND-ACT-03"]["action"] == "dismissed"
    assert "Approved Exception Granted" in actions["FND-ACT-03"]["dismiss_reason"]


def test_finding_ids_and_review_cycle_identity_unchanged_during_loading(disposable_db):
    """Finding IDs and review-cycle identity remain completely unchanged during loading with zero mutations."""
    db = disposable_db
    asset_id = "AST-REV-IMMUTABLE-ID"

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'Immutable ID Test', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen', 'h', 'Text', '2026-11-15', 2);
            """,
            (asset_id,),
        )
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, link_state, message, next_step, suggested_rewrite, creator_action, review_cycle
            ) VALUES ('FND-V04-0-IMMUTABLEID-C2', ?, 'tone', 'block', 0, 7, 'forever', 'V-04', 'UNLINKED', 'msg', 'step', 'long-term', 'accepted', 2);
            """,
            (asset_id,),
        )
        conn.commit()

    # Load asset
    loaded = load_revision_asset(asset_id, db_path=db)
    finding = loaded["findings"][0]

    assert finding.finding_id == "FND-V04-0-IMMUTABLEID-C2"
    assert finding.review_cycle == 2
    assert finding.asset_id == asset_id

    # Verify no write mutations occurred on database during load
    with get_connection(db) as conn:
        db_f = conn.execute("SELECT * FROM findings WHERE finding_id = 'FND-V04-0-IMMUTABLEID-C2'").fetchone()
        assert db_f["finding_id"] == "FND-V04-0-IMMUTABLEID-C2"
        assert db_f["review_cycle"] == 2
        assert db_f["creator_action"] == "accepted"


def test_creator_can_revise_and_resubmit_successfully(disposable_db):
    """Full workflow: transition asset from changes_requested to draft, load, edit finding, and resubmit atomically."""
    db = disposable_db
    asset_id = "AST-REV-E2E-01"
    initial_text = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'E2E Revise Asset', 'prod_monsoon', 'US', 'paid_social', 'changes_requested', 'Alex Chen (Creator)', 'orig_hash', ?, '2026-11-20', 1);
            """,
            (asset_id, initial_text),
        )
        conn.commit()

    # Original snapshot
    save_original_snapshot(asset_id, initial_text, "Alex Chen (Creator)", db_path=db)

    # Findings in cycle 1
    f1 = Finding(
        finding_id=f"FND-V04-20-{asset_id}-C1",
        asset_id=asset_id,
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=20,
        span_end=27,
        source_text="forever",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Tone issue",
        suggested_rewrite="for clearer-looking skin",
        creator_action=CreatorActionState.ACCEPTED,
        review_cycle=1,
    )
    f2 = Finding(
        finding_id=f"FND-T12-38-{asset_id}-C1",
        asset_id=asset_id,
        kind=FindingKind.TERMINOLOGY,
        severity=Severity.BLOCK,
        span_start=38,
        span_end=41,
        source_text="BPO",
        rule_id="T-12",
        link_state=LinkState.UNLINKED,
        message="BPO disallowed",
        suggested_rewrite="Benzoyl Peroxide",
        creator_action=CreatorActionState.ACCEPTED,
        review_cycle=1,
    )
    apply_creator_decision(finding=f1, action="accepted", role=Role.CREATOR, db_path=db)
    apply_creator_decision(finding=f2, action="accepted", role=Role.CREATOR, db_path=db)

    # 1. Creator initiates revision cycle (CAS transition)
    cas_success = start_revision_cycle(asset_id, db_path=db)
    assert cas_success is True

    cycle_after_cas = get_asset_review_cycle(asset_id, db_path=db)
    assert cycle_after_cas == 2

    # 2. Load revision workspace
    loaded = load_revision_asset(asset_id, db_path=db)
    assert loaded["asset"]["status"] == "draft"
    assert loaded["review_cycle"] == 2
    assert len(loaded["findings"]) == 2

    # 3. Creator edits finding in cycle 2
    f_edit = loaded["findings"][0]
    new_custom_text = "with regular daily use"
    apply_creator_decision(
        finding=f_edit,
        action="edited",
        new_text=new_custom_text,
        role=Role.CREATOR,
        review_cycle=2,
        db_path=db,
    )

    # Update actions
    loaded_actions = loaded["actions"]
    loaded_actions[f_edit.finding_id]["action"] = "edited"
    loaded_actions[f_edit.finding_id]["text"] = new_custom_text

    # 4. Reconstruct and submit draft
    base_text = get_reconstruction_base_text(asset_id, loaded["doc"].text, loaded["findings"], db_path=db)
    submitted_copy = reconstruct_submitted_text(base_text, loaded["findings"], loaded_actions)
    assert "with regular daily use" in submitted_copy

    res = submit_draft(
        asset_id=asset_id,
        original_text=base_text,
        submitted_text=submitted_copy,
        findings=loaded["findings"],
        actions=loaded_actions,
        actor_name="Alex Chen (Creator)",
        role=Role.CREATOR,
        review_cycle=2,
        db_path=db,
    )

    assert "submission_id" in res
    assert res["submission_id"] == f"SUB-{asset_id}-C2"
    assert res["review_cycle"] == 2

    # Verify database state after submission
    with get_connection(db) as conn:
        a_row = conn.execute("SELECT status, review_cycle, text_content FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        assert a_row["status"] == "ready_for_review"
        assert a_row["review_cycle"] == 2
        assert a_row["text_content"] == submitted_copy

        eff_row = conn.execute("SELECT effective_text FROM asset_effective_snapshots WHERE asset_id = ? AND review_cycle = 2", (asset_id,)).fetchone()
        assert eff_row is not None
        assert eff_row["effective_text"] == submitted_copy


def test_non_creator_cannot_perform_creator_actions(disposable_db):
    """Reviewer, Fact Owner, or unauthenticated callers cannot perform Creator actions."""
    db = disposable_db
    asset_id = "AST-REV-RBAC-01"

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'RBAC Test', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'h', 'Text', '2026-11-20', 1);
            """,
            (asset_id,),
        )
        conn.commit()

    f = Finding(
        finding_id=f"FND-V04-0-{asset_id}-C1",
        asset_id=asset_id,
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=4,
        source_text="Test",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Msg",
        suggested_rewrite="Rew",
        creator_action=CreatorActionState.PENDING,
        review_cycle=1,
    )

    # 1. Reviewer role rejected on apply_creator_decision
    with pytest.raises(PermissionError):
        apply_creator_decision(finding=f, action="accepted", role=Role.REVIEWER, db_path=db)

    # 2. Fact Owner role rejected on apply_creator_decision
    with pytest.raises(PermissionError):
        apply_creator_decision(finding=f, action="accepted", role=Role.FACT_OWNER, db_path=db)

    # 3. None/missing role rejected on apply_creator_decision
    with pytest.raises(PermissionError):
        apply_creator_decision(finding=f, action="accepted", role=None, db_path=db)

    # 4. Reviewer role rejected on submit_draft
    with pytest.raises(PermissionError):
        submit_draft(
            asset_id=asset_id,
            original_text="Text",
            submitted_text="Text",
            findings=[f],
            actions={},
            role=Role.REVIEWER,
            db_path=db,
        )

    # 5. Fact Owner role rejected on submit_draft
    with pytest.raises(PermissionError):
        submit_draft(
            asset_id=asset_id,
            original_text="Text",
            submitted_text="Text",
            findings=[f],
            actions={},
            role=Role.FACT_OWNER,
            db_path=db,
        )

    # 6. None/missing role rejected on submit_draft
    with pytest.raises(PermissionError):
        submit_draft(
            asset_id=asset_id,
            original_text="Text",
            submitted_text="Text",
            findings=[f],
            actions={},
            role=None,
            db_path=db,
        )


def test_failed_loading_does_not_leave_partially_updated_state(disposable_db):
    """Failed loading raises an explicit error and leaves caller state completely untouched."""
    db = disposable_db
    fake_asset = "AST-DOES-NOT-EXIST-999"

    # In-memory session-state representation
    session_state = {
        "active_asset_id": "PREVIOUS_ASSET",
        "active_doc": "PREVIOUS_DOC",
        "findings": ["PREVIOUS_FINDING"],
        "finding_actions": {"f": "prev"},
    }

    # Attempt to load non-existent asset
    with pytest.raises(ValueError, match="not found"):
        data = load_revision_asset(fake_asset, db_path=db)
        # Would only assign if successful:
        session_state["active_asset_id"] = data["asset"]["asset_id"]

    # State is completely preserved
    assert session_state["active_asset_id"] == "PREVIOUS_ASSET"
    assert session_state["active_doc"] == "PREVIOUS_DOC"
    assert session_state["findings"] == ["PREVIOUS_FINDING"]


def test_failed_submission_leaves_no_partial_database_state(disposable_db):
    """Failed submission rolls back the entire SQLite transaction without partial records."""
    db = disposable_db
    asset_id = "AST-REV-FAIL-TX-01"
    initial_text = "Some draft text"

    with get_connection(db) as conn:
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by,
                source_hash, text_content, planned_publish_date, review_cycle
            ) VALUES (?, 'Tx Fail Test', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'h', ?, '2026-11-20', 2);
            """,
            (asset_id, initial_text),
        )
        conn.commit()

    f = Finding(
        finding_id=f"FND-FAIL-01",
        asset_id=asset_id,
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=4,
        source_text="Some",
        rule_id="V-04",
        link_state=LinkState.UNLINKED,
        message="Msg",
        suggested_rewrite="Good",
        creator_action=CreatorActionState.ACCEPTED,
        review_cycle=2,
    )

    # Force simulated failure at stage 4 (effective snapshot)
    with pytest.raises(RuntimeError, match="Simulated failure at Stage 4"):
        submit_draft(
            asset_id=asset_id,
            original_text=initial_text,
            submitted_text="Good draft text",
            findings=[f],
            actions={f.finding_id: {"action": "accepted", "text": "Good"}},
            role=Role.CREATOR,
            review_cycle=2,
            db_path=db,
            _fail_at_stage=4,
        )

    # Confirm zero partial submission records created
    with get_connection(db) as conn:
        sub = conn.execute("SELECT * FROM asset_submissions WHERE asset_id = ?", (asset_id,)).fetchone()
        assert sub is None

        eff = conn.execute("SELECT * FROM asset_effective_snapshots WHERE asset_id = ?", (asset_id,)).fetchone()
        assert eff is None

        asset = conn.execute("SELECT status, text_content FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        assert asset["status"] == "draft"  # Not changed to ready_for_review
        assert asset["text_content"] == initial_text
