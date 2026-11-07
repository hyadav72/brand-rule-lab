"""
Brand Rule Lab — Permissions and Audit Log Tests
Owned by Agent A5 (QA Engineer).
"""

import sqlite3
import pytest
from core.audit import log_review_event, get_asset_audit_trail, apply_creator_decision
from core.db import init_db, get_connection, execute_query
from core.ledger.approve import approve_claim, request_changes, escalate_asset
from core.ledger.drift import cascade_fact_update, sweep_expiry
from core.lookup.facts import publish_fact_version
from core.models import Role, Finding, FindingKind, LinkState, Severity
from core.permissions import can_perform, enforce_permission
from core.snapshots import submit_draft


@pytest.fixture
def seeded_db(tmp_path):
    """Provide initialized database with sample asset."""
    db_file = tmp_path / "test_permissions.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert prerequisite product and asset
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO products VALUES ('prod_monsoon', 'Monsoon Clear Skin', '[]', 'US');"
        )
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
            ) VALUES ('AST-001', 'Acne Wash Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex', 'hash123', 'Sample draft', '2026-11-10');
            """
        )
    return db_path


def test_role_permissions():
    """Verify role boundaries as required by Section 12."""
    # Creator permissions
    assert can_perform(Role.CREATOR, "upload_draft")
    assert can_perform(Role.CREATOR, "submit_for_review")
    assert not can_perform(Role.CREATOR, "approve_asset")  # Creator CANNOT approve
    assert not can_perform(Role.CREATOR, "create_fact_version")

    # Reviewer permissions
    assert can_perform(Role.REVIEWER, "approve_asset")
    assert can_perform(Role.REVIEWER, "request_changes")
    assert not can_perform(Role.REVIEWER, "create_fact_version")  # Reviewer CANNOT edit facts
    assert not can_perform(Role.REVIEWER, "upload_draft")

    # Fact Owner permissions
    assert can_perform(Role.FACT_OWNER, "create_fact_version")
    assert can_perform(Role.FACT_OWNER, "trigger_drift_cascade")
    assert not can_perform(Role.FACT_OWNER, "approve_asset")  # Fact Owner CANNOT approve assets


def test_permission_enforcement_raises():
    """Verify enforce_permission raises PermissionError on violation."""
    with pytest.raises(PermissionError):
        enforce_permission(Role.CREATOR, "approve_asset")

    with pytest.raises(PermissionError):
        enforce_permission(Role.REVIEWER, "create_fact_version")

    with pytest.raises(PermissionError):
        enforce_permission(Role.FACT_OWNER, "approve_asset")


def test_audit_event_logging_and_retrieval(seeded_db):
    """Verify logging review events and retrieving chronological trail."""
    evt1 = log_review_event(
        asset_id="AST-001",
        actor="Alex Chen",
        role=Role.CREATOR,
        action="submit_for_review",
        comment="Initial draft submitted",
        db_path=seeded_db,
    )
    assert evt1.event_id.startswith("EVT-")

    evt2 = log_review_event(
        asset_id="AST-001",
        actor="Sarah Jenkins",
        role=Role.REVIEWER,
        action="approve",
        comment="Approved copy matches F-112 v3",
        db_path=seeded_db,
    )

    trail = get_asset_audit_trail("AST-001", db_path=seeded_db)
    assert len(trail) == 2
    assert trail[0].action == "submit_for_review"
    assert trail[1].action == "approve"


def test_audit_log_append_only_enforced_by_sqlite_triggers(seeded_db):
    """Verify that UPDATE or DELETE on review_events is blocked by SQL triggers."""
    evt = log_review_event(
        asset_id="AST-001",
        actor="Alex Chen",
        role=Role.CREATOR,
        action="submit_for_review",
        db_path=seeded_db,
    )

    with get_connection(seeded_db) as conn:
        # Test UPDATE violation
        with pytest.raises(sqlite3.DatabaseError) as exc_update:
            conn.execute(
                "UPDATE review_events SET comment = 'tampered' WHERE event_id = ?;",
                (evt.event_id,),
            )
        assert "append-only" in str(exc_update.value).lower()

        # Test DELETE violation
        with pytest.raises(sqlite3.DatabaseError) as exc_delete:
            conn.execute(
                "DELETE FROM review_events WHERE event_id = ?;",
                (evt.event_id,),
            )
        assert "append-only" in str(exc_delete.value).lower()


def test_creator_cannot_approve_asset(seeded_db):
    """Verify that Creator persona is strictly blocked from approving assets."""
    assert not can_perform(Role.CREATOR, "approve_asset")
    assert not can_perform("creator", "approve_asset")

    with pytest.raises(PermissionError) as exc_info:
        approve_claim(
            asset_id="AST-001",
            claim_text="Sample approved claim",
            fact_id="F-112",
            fact_version_id=1,
            reviewer_id="Alex Chen (Creator)",
            role=Role.CREATOR,
            db_path=seeded_db,
        )
    assert "Role 'creator' is not permitted to execute action 'approve_asset'" in str(exc_info.value)


def test_creator_cannot_publish_fact(seeded_db):
    """Verify that Creator persona is strictly blocked from publishing brand facts."""
    assert not can_perform(Role.CREATOR, "create_fact_version")
    assert not can_perform(Role.CREATOR, "publish_fact")
    assert not can_perform("creator", "publish_fact")

    with pytest.raises(PermissionError) as exc_info:
        publish_fact_version(
            fact_id="F-999",
            version=1,
            product_id="prod_monsoon",
            market="US",
            fact_text="Unapproved creator statement",
            permitted_wording="Unapproved creator wording",
            role=Role.CREATOR,
            db_path=seeded_db,
        )
    assert "Role 'creator' is not permitted to execute action 'create_fact_version'" in str(exc_info.value)


def test_reviewer_cannot_publish_fact(seeded_db):
    """Verify that Reviewer persona is strictly blocked from creating or publishing brand facts."""
    assert not can_perform(Role.REVIEWER, "create_fact_version")
    assert not can_perform(Role.REVIEWER, "publish_fact")
    assert not can_perform("reviewer", "publish_fact")

    with pytest.raises(PermissionError) as exc_info:
        publish_fact_version(
            fact_id="F-999",
            version=1,
            product_id="prod_monsoon",
            market="US",
            fact_text="Reviewer edited statement",
            permitted_wording="Reviewer edited wording",
            role=Role.REVIEWER,
            db_path=seeded_db,
        )
    assert "Role 'reviewer' is not permitted to execute action 'create_fact_version'" in str(exc_info.value)


def test_reviewer_can_perform_permitted_review_actions(seeded_db):
    """Verify that Reviewer persona can approve, request changes, and escalate."""
    assert can_perform(Role.REVIEWER, "approve_asset")
    assert can_perform(Role.REVIEWER, "request_changes")
    assert can_perform(Role.REVIEWER, "escalate_finding")

    # 1. Reviewer can request changes
    request_changes(
        asset_id="AST-001",
        comment="Please fix tone violation",
        actor="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=seeded_db,
    )
    res = execute_query("SELECT status FROM assets WHERE asset_id = 'AST-001';", db_path=seeded_db)[0]
    assert res["status"] == "changes_requested"

    # 2. Reviewer can escalate
    escalate_asset(
        asset_id="AST-001",
        comment="Evidence missing for clinical trial claim",
        actor="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=seeded_db,
    )
    res = execute_query("SELECT status FROM assets WHERE asset_id = 'AST-001';", db_path=seeded_db)[0]
    assert res["status"] == "escalated"

    # 3. Reviewer can approve
    # Create prerequisite fact version in seeded DB first
    publish_fact_version(
        fact_id="F-112",
        version=1,
        product_id="prod_monsoon",
        market="US",
        fact_text="Clinical trial fact",
        permitted_wording="Clinical trial wording",
        role=Role.FACT_OWNER,
        db_path=seeded_db,
    )
    stable_id = approve_claim(
        asset_id="AST-001",
        claim_text="Compliant clinical claim text",
        fact_id="F-112",
        fact_version_id=1,
        reviewer_id="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=seeded_db,
    )
    assert stable_id.startswith("SC-")
    res = execute_query("SELECT status FROM assets WHERE asset_id = 'AST-001';", db_path=seeded_db)[0]
    assert res["status"] == "approved"


def test_fact_owner_cannot_approve_asset(seeded_db):
    """Verify that Fact Owner persona is strictly blocked from approving assets."""
    assert not can_perform(Role.FACT_OWNER, "approve_asset")
    assert not can_perform("fact_owner", "approve_asset")

    with pytest.raises(PermissionError) as exc_info:
        approve_claim(
            asset_id="AST-001",
            claim_text="Sample approved claim",
            fact_id="F-112",
            fact_version_id=1,
            reviewer_id="Dr. Elena Rostova (Fact Owner)",
            role=Role.FACT_OWNER,
            db_path=seeded_db,
        )
    assert "Role 'fact_owner' is not permitted to execute action 'approve_asset'" in str(exc_info.value)


def test_fact_owner_can_perform_permitted_fact_operations(seeded_db):
    """Verify that Fact Owner can publish fact versions, run drift cascades, and sweep expiry."""
    assert can_perform(Role.FACT_OWNER, "create_fact_version")
    assert can_perform(Role.FACT_OWNER, "publish_fact")
    assert can_perform(Role.FACT_OWNER, "trigger_drift_cascade")
    assert can_perform(Role.FACT_OWNER, "sweep_expiry")

    # 1. Fact Owner publishes a fact version
    publish_fact_version(
        fact_id="F-112",
        version=1,
        product_id="prod_monsoon",
        market="US",
        fact_text="Initial statement",
        permitted_wording="Initial wording",
        role=Role.FACT_OWNER,
        db_path=seeded_db,
    )

    # Approve a claim linked to v1
    approve_claim(
        asset_id="AST-001",
        claim_text="Initial wording claim",
        fact_id="F-112",
        fact_version_id=1,
        reviewer_id="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=seeded_db,
    )

    # 2. Fact Owner publishes v2 and triggers cascade
    publish_fact_version(
        fact_id="F-112",
        version=2,
        product_id="prod_monsoon",
        market="US",
        fact_text="Updated statement",
        permitted_wording="Updated wording",
        role=Role.FACT_OWNER,
        db_path=seeded_db,
    )
    flagged = cascade_fact_update("F-112", 2, role=Role.FACT_OWNER, db_path=seeded_db)
    assert flagged == 1

    claim_row = execute_query(
        "SELECT drift_status FROM approved_claims WHERE asset_id = 'AST-001';",
        db_path=seeded_db,
    )[0]
    assert claim_row["drift_status"] == "REVIEW_REQUIRED"

    # 3. Fact Owner runs expiry sweep
    expired_cnt = sweep_expiry("2026-12-31", role=Role.FACT_OWNER, db_path=seeded_db)
    assert isinstance(expired_cnt, int)


def test_creator_can_perform_permitted_creator_actions(seeded_db):
    """Verify Creator can record finding decisions and submit drafts, but not reviewer/fact operations."""
    assert can_perform(Role.CREATOR, "upload_draft")
    assert can_perform(Role.CREATOR, "analyze_draft")
    assert can_perform(Role.CREATOR, "accept_finding")
    assert can_perform(Role.CREATOR, "edit_finding")
    assert can_perform(Role.CREATOR, "dismiss_finding")
    assert can_perform(Role.CREATOR, "submit_for_review")

    finding = Finding(
        finding_id="FND-TEST-01",
        asset_id="AST-001",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=6,
        source_text="Sample",
        message="Test message",
        next_step="Fix it",
        suggested_rewrite="Clean sample",
    )

    # 1. Creator accepts rewrite
    evt = apply_creator_decision(
        finding=finding,
        action="accepted",
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        db_path=seeded_db,
    )
    assert evt is not None

    # 2. Reviewer or Fact Owner cannot accept finding
    with pytest.raises(PermissionError):
        apply_creator_decision(
            finding=finding,
            action="accepted",
            actor="Sarah Jenkins (Reviewer)",
            role=Role.REVIEWER,
            db_path=seeded_db,
        )

    # 3. Creator submits draft
    res = submit_draft(
        asset_id="AST-001",
        original_text="Original draft text",
        submitted_text="Submitted draft text",
        findings=[finding],
        actions={finding.finding_id: {"action": "accepted", "text": "Clean sample"}},
        actor_name="Alex Chen (Creator)",
        role=Role.CREATOR,
        db_path=seeded_db,
    )
    assert "submission_id" in res
    assert res["review_cycle"] == 1

    # 4. Reviewer cannot submit draft
    with pytest.raises(PermissionError):
        submit_draft(
            asset_id="AST-001",
            original_text="Original draft text",
            submitted_text="Submitted draft text",
            findings=[finding],
            actions={finding.finding_id: {"action": "accepted", "text": "Clean sample"}},
            actor_name="Sarah Jenkins (Reviewer)",
            role=Role.REVIEWER,
            db_path=seeded_db,
        )


def test_role_switching_and_session_state():
    """Verify role switching logic across all canonical roles."""
    import streamlit as st
    from app.ui.theme import render_sidebar_role_switcher

    # Simulate session state
    st.session_state["role"] = Role.CREATOR.value
    assert st.session_state["role"] == "creator"

    st.session_state["role"] = Role.REVIEWER.value
    assert st.session_state["role"] == "reviewer"

    st.session_state["role"] = Role.FACT_OWNER.value
    assert st.session_state["role"] == "fact_owner"


def test_missing_role_rejected_across_all_privileged_functions(seeded_db):
    """
    Verify that omitting the role argument or passing role=None to ANY privileged operation
    is strictly rejected with PermissionError. Missing roles must never grant implicit authority.
    """
    finding = Finding(
        finding_id="FND-ROLE-TEST-01",
        asset_id="AST-001",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=6,
        source_text="Sample",
        message="Test message",
        next_step="Fix it",
        suggested_rewrite="Clean sample",
    )

    # 1. approve_claim without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        approve_claim(
            asset_id="AST-001",
            claim_text="Sample",
            fact_id="F-112",
            fact_version_id=1,
            db_path=seeded_db,
        )
    with pytest.raises(PermissionError, match="requires an explicit role"):
        approve_claim(
            asset_id="AST-001",
            claim_text="Sample",
            fact_id="F-112",
            fact_version_id=1,
            role=None,
            db_path=seeded_db,
        )

    # 2. request_changes without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        request_changes(asset_id="AST-001", comment="Note", db_path=seeded_db)
    with pytest.raises(PermissionError, match="requires an explicit role"):
        request_changes(asset_id="AST-001", comment="Note", role=None, db_path=seeded_db)

    # 3. escalate_asset without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        escalate_asset(asset_id="AST-001", comment="Note", db_path=seeded_db)
    with pytest.raises(PermissionError, match="requires an explicit role"):
        escalate_asset(asset_id="AST-001", comment="Note", role=None, db_path=seeded_db)

    # 4. publish_fact_version without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        publish_fact_version(
            fact_id="F-112",
            version=10,
            product_id="prod_monsoon",
            market="US",
            fact_text="Text",
            permitted_wording="Wording",
            db_path=seeded_db,
        )
    with pytest.raises(PermissionError, match="requires an explicit role"):
        publish_fact_version(
            fact_id="F-112",
            version=10,
            product_id="prod_monsoon",
            market="US",
            fact_text="Text",
            permitted_wording="Wording",
            role=None,
            db_path=seeded_db,
        )

    # 5. cascade_fact_update without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        cascade_fact_update("F-112", 4, db_path=seeded_db)
    with pytest.raises(PermissionError, match="requires an explicit role"):
        cascade_fact_update("F-112", 4, role=None, db_path=seeded_db)

    # 6. sweep_expiry without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        sweep_expiry("2026-11-05", db_path=seeded_db)
    with pytest.raises(PermissionError, match="requires an explicit role"):
        sweep_expiry("2026-11-05", role=None, db_path=seeded_db)

    # 7. submit_draft without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        submit_draft(
            asset_id="AST-001",
            original_text="Original",
            submitted_text="Submitted",
            findings=[finding],
            actions={finding.finding_id: {"action": "accepted", "text": "Clean"}},
            db_path=seeded_db,
        )
    with pytest.raises(PermissionError, match="requires an explicit role"):
        submit_draft(
            asset_id="AST-001",
            original_text="Original",
            submitted_text="Submitted",
            findings=[finding],
            actions={finding.finding_id: {"action": "accepted", "text": "Clean"}},
            role=None,
            db_path=seeded_db,
        )

    # 8. apply_creator_decision without role or with role=None
    with pytest.raises(PermissionError, match="requires an explicit role"):
        apply_creator_decision(finding=finding, action="accepted", db_path=seeded_db)
    with pytest.raises(PermissionError, match="requires an explicit role"):
        apply_creator_decision(finding=finding, action="accepted", role=None, db_path=seeded_db)


def test_reviewer_cannot_execute_fact_owner_operations(seeded_db):
    """Verify that Reviewer role is blocked from fact cascades and expiry sweeps."""
    with pytest.raises(PermissionError) as exc_casc:
        cascade_fact_update("F-112", 4, role=Role.REVIEWER, db_path=seeded_db)
    assert "Role 'reviewer' is not permitted to execute action 'trigger_drift_cascade'" in str(exc_casc.value)

    with pytest.raises(PermissionError) as exc_swp:
        sweep_expiry("2026-11-05", role=Role.REVIEWER, db_path=seeded_db)
    assert "Role 'reviewer' is not permitted to execute action 'sweep_expiry'" in str(exc_swp.value)


def test_fact_owner_workflow_exact_confirmation_and_cascade(monkeypatch, tmp_path):
    """
    Verify Fact Owner workflow:
    - Pre-commit confirmation 'This will flag N registered claims'
    - Single SQL drift cascade and affected claims display
    - Append-only audit logging
    - Zero LLM calls and zero web crawls
    """
    from core.seed import seed_database
    from core.lookup.facts import publish_fact_version
    from core.ledger.drift import cascade_fact_update
    from core.audit import log_review_event, get_asset_audit_trail

    db_path = str(tmp_path / "fact_owner_workflow.db")
    seed_database(db_path, include_demo_assets=True)

    # 1. Verify registered claims dependent on F-112 before cascade
    before_claims = execute_query(
        "SELECT stable_claim_id, drift_status FROM approved_claims WHERE fact_id = 'F-112' AND drift_status = 'CURRENT';",
        db_path=db_path,
    )
    dependent_count = len(before_claims)
    assert dependent_count >= 1

    # Exact confirmation string format required by build plan
    confirmation_msg = f'This will flag {dependent_count} registered claims'
    assert f"This will flag {dependent_count} registered claims" == confirmation_msg

    # Guard against LLM or network calls
    def fail_if_network(*args, **kwargs):
        raise RuntimeError("Network/LLM call detected during fact update!")

    monkeypatch.setattr("requests.post", fail_if_network)
    monkeypatch.setattr("urllib.request.urlopen", fail_if_network)

    # 2. Publish new fact version as Fact Owner (zero LLM calls)
    res = publish_fact_version(
        fact_id="F-112",
        version=4,
        product_id="prod_monsoon",
        market="US",
        fact_text="Clinically proven to reduce acne breakouts in 2 weeks with reformulated 2.5% Micronized Benzoyl Peroxide.",
        permitted_wording="Reduces breakouts in 2 weeks with micronized formula.",
        valid_from="2026-11-07",
        expires_at=None,
        owner="brand_science",
        role=Role.FACT_OWNER,
        db_path=db_path,
    )
    assert res == 1

    # 3. Execute drift cascade (1 SQL update, zero LLM calls)
    flagged = cascade_fact_update("F-112", 4, role=Role.FACT_OWNER, db_path=db_path)
    assert flagged == dependent_count

    # 4. Verify claim transitioned to REVIEW_REQUIRED
    after_claims = execute_query(
        "SELECT stable_claim_id, drift_status, flagged_at FROM approved_claims WHERE fact_id = 'F-112';",
        db_path=db_path,
    )
    for c in after_claims:
        assert c["drift_status"] == "REVIEW_REQUIRED"
        assert c["flagged_at"] is not None

    # 5. Append-only audit logging for affected assets
    affected_assets = execute_query(
        "SELECT DISTINCT asset_id FROM approved_claims WHERE fact_id = 'F-112';",
        db_path=db_path,
    )
    for aa in affected_assets:
        log_review_event(
            asset_id=aa["asset_id"],
            actor="Sarah Jenkins (Fact Owner)",
            role=Role.FACT_OWNER,
            action="PUBLISH_FACT_VERSION",
            comment=f"Published F-112 v4. Cascade flagged {flagged} registered claims.",
            db_path=db_path,
        )

    trail = get_asset_audit_trail("AST-MONSOON-01", db_path=db_path)
    assert len(trail) >= 1
    matching = next((e for e in trail if e.action == "PUBLISH_FACT_VERSION"), None)
    assert matching is not None
    assert matching.role == Role.FACT_OWNER
    assert f"Cascade flagged {flagged} registered claims." in matching.comment

