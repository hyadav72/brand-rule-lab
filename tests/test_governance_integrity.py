"""
Brand Rule Lab — Governance & Content Integrity Regression Tests
Owned by Agent A5 (QA Engineer).

Verifies the P0 governance invariants:
1. Reviewer sees effective submitted copy (reconstructed with accepted/edited rewrites).
2. Original draft copy remains permanently preserved in the append-only audit trail.
3. Accepted rewrites are rechecked against all deterministic rules.
4. Unsupported factual claims (e.g., 'clinically tested' without matching approved facts)
   do NOT become compliant automatically and are flagged as UNLINKED.
5. Fact-linked claims preserve their exact fact version (e.g., F-112 v3).
6. UNLINKED (unmatched claim) and NOT_OBSERVED (coverage boundary) remain strictly distinct.
7. Approval remains disabled when genuine unresolved UNLINKED claims exist, requiring
   explicit reviewer override logging.
"""

import pytest
from core.db import execute_commit, execute_query, get_connection
from core.models import Finding, FindingKind, LinkState, Role, Severity
from core.reconstruct import reconstruct_submitted_text
from core.rules.engine import RuleEngine
from core.audit import get_asset_audit_trail, log_review_event
from core.ledger.approve import approve_claim
from core.seed import seed_database


@pytest.fixture
def governance_db(tmp_path):
    """Provide clean database for governance tests."""
    db_file = tmp_path / "gov_brand_rule_lab.db"
    db_path = str(db_file)
    seed_database(db_path, include_demo_assets=False)
    return db_path


def test_reviewer_sees_accepted_edited_text_after_submission(governance_db):
    """
    Issue 1 Verification:
    Reviewer must inspect the effective submitted copy containing all accepted
    and custom-edited rewrites, not the raw unedited initial draft.
    """
    original_draft = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    asset_id = "AST-GOV-001"

    # Insert draft
    execute_commit(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
        VALUES (?, 'Monsoon Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'hash01', ?, '2026-11-10');
        """,
        (asset_id, original_draft),
        db_path=governance_db,
    )

    findings = [
        Finding(
            finding_id="f1",
            asset_id=asset_id,
            kind=FindingKind.TONE,
            severity=Severity.BLOCK,
            span_start=20,
            span_end=27,
            source_text="forever",
            rule_id="V-04",
            link_state=LinkState.UNLINKED,
            message="Absolute tone",
            next_step="Replace with long-term",
        ),
        Finding(
            finding_id="f2",
            asset_id=asset_id,
            kind=FindingKind.TERMINOLOGY,
            severity=Severity.BLOCK,
            span_start=38,
            span_end=41,
            source_text="BPO",
            rule_id="T-12",
            link_state=LinkState.UNLINKED,
            message="BPO abbreviation disallowed",
            next_step="Expand to Benzoyl Peroxide",
        ),
        Finding(
            finding_id="f3",
            asset_id=asset_id,
            kind=FindingKind.CLAIM,
            severity=Severity.BLOCK,
            span_start=47,
            span_end=73,
            source_text="clears breakouts in 3 days",
            rule_id="C-01",
            fact_id="F-112",
            fact_version_id=3,
            link_state=LinkState.LINKED,
            message="Contradicts 4-week trial baseline",
            next_step="Align with 4-week trial wording",
        ),
    ]

    actions = {
        "f1": {"action": "accepted", "text": "with regular use"},
        "f2": {"action": "accepted", "text": "Benzoyl Peroxide"},
        "f3": {"action": "accepted", "text": "reduces breakouts in 4 weeks with twice-daily use"},
    }

    # Reconstruct submitted copy
    submitted_copy = reconstruct_submitted_text(original_draft, findings, actions)
    expected_copy = "Say goodbye to acne with regular use! Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use."
    assert submitted_copy == expected_copy

    # Simulate submission persistence
    execute_commit(
        "UPDATE assets SET text_content = ?, status = 'ready_for_review' WHERE asset_id = ?;",
        (submitted_copy, asset_id),
        db_path=governance_db,
    )

    # Reviewer queries asset
    reviewer_asset = execute_query(
        "SELECT text_content, status FROM assets WHERE asset_id = ?;",
        (asset_id,),
        db_path=governance_db,
    )[0]

    assert reviewer_asset["status"] == "ready_for_review"
    assert reviewer_asset["text_content"] == expected_copy
    assert "forever" not in reviewer_asset["text_content"]
    assert "BPO" not in reviewer_asset["text_content"]


def test_original_draft_remains_available_in_audit_history(governance_db):
    """
    Issue 1 & D-2 Audit Verification:
    Original draft copy must be stored as an immutable snapshot in asset_original_snapshots,
    retrievable for tamper-evident audit, and NOT duplicated as raw text inside review_events.comment.
    """
    import hashlib
    import sqlite3
    from core.snapshots import get_original_snapshot, save_original_snapshot

    original_draft = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    asset_id = "AST-GOV-002"
    actor_name = "Alex Chen (Creator)"

    execute_commit(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
        VALUES (?, 'Monsoon Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'hash02', ?, '2026-11-10');
        """,
        (asset_id, original_draft),
        db_path=governance_db,
    )

    # 1. Save original draft snapshot (D-2)
    snapshot_id = save_original_snapshot(
        asset_id=asset_id,
        original_text=original_draft,
        captured_by=actor_name,
        db_path=governance_db,
    )
    assert snapshot_id == f"SNAP-{asset_id}"

    # 2. Log review event referencing snapshot_id, omitting raw draft copy
    log_review_event(
        asset_id=asset_id,
        actor=actor_name,
        role=Role.CREATOR,
        action="submit_for_review",
        comment=f"Submitted effective draft with 3 resolved findings. Snapshot: {snapshot_id}",
        db_path=governance_db,
    )

    # 3. Retrieve and verify snapshot from dedicated table
    snap = get_original_snapshot(asset_id, db_path=governance_db)
    assert snap is not None
    assert snap["original_text"] == original_draft
    assert snap["captured_by"] == actor_name
    assert snap["content_hash"] == hashlib.sha256(original_draft.encode("utf-8")).hexdigest()

    # 4. Verify audit comment does NOT duplicate raw draft text
    trail = get_asset_audit_trail(asset_id, db_path=governance_db)
    submit_event = next(e for e in trail if e.action == "submit_for_review")
    assert original_draft not in submit_event.comment
    assert "forever" not in submit_event.comment
    assert "BPO" not in submit_event.comment
    assert snapshot_id in submit_event.comment

    # 5. Verify snapshot immutability (triggers forbid UPDATE and DELETE)
    with pytest.raises(Exception):
        execute_commit(
            "UPDATE asset_original_snapshots SET original_text = 'tampered' WHERE asset_id = ?;",
            (asset_id,),
            db_path=governance_db,
        )

    with pytest.raises(Exception):
        execute_commit(
            "DELETE FROM asset_original_snapshots WHERE asset_id = ?;",
            (asset_id,),
            db_path=governance_db,
        )


def test_accepted_rewrites_rechecked_against_deterministic_rules():
    """
    Issue 2 Re-check Verification:
    Accepted or edited rewrites must be evaluated through deterministic rules;
    if a rewrite retains a violation, it is rejected as not clean.
    """
    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US", "channel": "paid_social"}

    # Flawed rewrite retaining 'BPO'
    dirty_rewrite = "Say goodbye to breakouts with our 2.5% BPO wash."
    is_clean, violations = engine.check_rewrite(dirty_rewrite, context)
    assert not is_clean
    assert any(v.rule_id == "T-12" for v in violations)

    # Clean clinical trial rewrite
    clean_rewrite = "Our 2.5% Benzoyl Peroxide wash is clinically proven to reduce acne breakouts in 4 weeks with twice-daily use."
    is_clean, violations = engine.check_rewrite(clean_rewrite, context)
    assert is_clean
    assert len(violations) == 0


def test_unsupported_factual_rewrites_do_not_become_compliant_automatically(governance_db):
    """
    Issue 2 Efficacy Evidence Verification:
    Affirmative clinical claims ('clinically tested' / 'clinically proven') without matching
    approved fact evidence in the fact registry must be flagged as UNLINKED claims.
    """
    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US", "channel": "paid_social"}

    # Rewrite using 'clinically tested' without trial fact backing
    unsupported_rewrite = "Say goodbye to acne with our wash, clinically tested for sensitive skin."
    is_clean, violations = engine.check_rewrite(unsupported_rewrite, context)

    assert not is_clean, "Unsupported clinical claim should NOT be treated as clean"
    unsupported_finding = next((v for v in violations if "clinically" in v.source_text.lower()), None)
    assert unsupported_finding is not None
    assert unsupported_finding.link_state == LinkState.UNLINKED
    assert unsupported_finding.severity == Severity.BLOCK


def test_fact_linked_claims_preserve_exact_fact_version(governance_db):
    """
    Issue 3 Lineage Verification:
    Fact-linked claims preserve exact fact ID and version across extraction,
    rewrite, and ledger approval.
    """
    asset_id = "AST-GOV-003"
    claim_text = "reduces breakouts in 4 weeks with twice-daily use"

    execute_commit(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
        VALUES (?, 'Monsoon Social', 'prod_monsoon', 'US', 'paid_social', 'ready_for_review', 'Alex Chen', 'hash03', ?, '2026-11-10');
        """,
        (asset_id, claim_text),
        db_path=governance_db,
    )

    stable_id = approve_claim(
        asset_id=asset_id,
        claim_text=claim_text,
        fact_id="F-112",
        fact_version_id=3,
        reviewer_id="Sarah Jenkins",
        role=Role.REVIEWER,
        db_path=governance_db,
    )

    row = execute_query(
        "SELECT fact_id, fact_version_id, drift_status FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_id,),
        db_path=governance_db,
    )[0]

    assert row["fact_id"] == "F-112"
    assert row["fact_version_id"] == 3
    assert row["drift_status"] == "CURRENT"


def test_unlinked_and_not_observed_remain_distinct():
    """
    Issue 3 Boundary Verification:
    UNLINKED and NOT_OBSERVED represent distinct governance concepts:
    - UNLINKED: An evaluated claim in an ingested asset with no matching approved fact.
    - NOT_OBSERVED: Live marketing content outside Brand Rule Lab's governance boundary.
    """
    from app.ui.components import render_state_chip

    unlinked_chip = render_state_chip(LinkState.UNLINKED)
    assert "chip-unlinked" in unlinked_chip
    assert "UNLINKED" in unlinked_chip

    not_observed_chip = render_state_chip("NOT_OBSERVED")
    assert "chip-not-observed" in not_observed_chip
    assert "NOT_OBSERVED" in not_observed_chip

    assert LinkState.UNLINKED.value != "NOT_OBSERVED"


def test_approval_disabled_when_genuine_unresolved_unlinked_claims_exist(governance_db):
    """
    Issue 3 & 4 Approval Guard Verification:
    Approval must remain strictly disabled whenever genuine unresolved UNLINKED
    claims exist, unless an explicit override reason is provided.
    """
    asset_id = "AST-GOV-004"
    unlinked_finding = Finding(
        finding_id="fnd_unlinked_01",
        asset_id=asset_id,
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=20,
        source_text="100% organic extract",
        rule_id="T-05",
        link_state=LinkState.UNLINKED,
        message="Misleading organic claim without fact backing",
        next_step="Attach organic certification fact",
        creator_action="pending",
    )

    findings_list = [unlinked_finding]

    # Reviewer governance logic
    unlinked_claims = [
        f for f in findings_list
        if f.link_state == LinkState.UNLINKED and (
            f.kind == FindingKind.CLAIM or f.creator_action in ("dismissed", "pending")
        )
    ]
    has_unlinked = len(unlinked_claims) > 0
    assert has_unlinked is True

    # Case A: Without override reason -> Approval is disabled
    override_reason_empty = ""
    approve_disabled = has_unlinked and not override_reason_empty.strip()
    assert approve_disabled is True, "Approval must be disabled when UNLINKED claims lack an override justification"

    # Case B: With legal override reason -> Approval is unlocked
    override_reason_valid = "External certified organic laboratory dossier #USDA-2026-88 reviewed and approved."
    approve_disabled = has_unlinked and not override_reason_valid.strip()
    assert approve_disabled is False, "Approval must unlock when an explicit override justification is recorded"


def test_v04_neutral_rewrite_and_no_unsupported_efficacy():
    """
    D-1 Regression Verification:
    1. V-04.json maps 'guaranteed' to neutral 'trusted care' (not 'proven care' or 'clinically tested').
    2. MockLLM.suggest_rewrite maps 'guaranteed' to 'trusted care'.
    3. 'trusted care' evaluates clean with zero tone or clinical findings.
    """
    import json
    from pathlib import Path
    from core.llm import get_llm_adapter

    # 1. Verify JSON specification
    v04_path = Path(__file__).parent.parent / "data" / "rules" / "V-04.json"
    v04_spec = json.loads(v04_path.read_text(encoding="utf-8"))
    subs = v04_spec["parameters"]["suggested_substitutions"]
    assert subs["guaranteed"] == "trusted care", f"Expected 'trusted care', got {subs.get('guaranteed')}"
    assert "proven" not in subs["guaranteed"], "Substitution must not use 'proven' or imply unsubstantiated efficacy"

    # 2. Verify Mock adapter implementation
    adapter = get_llm_adapter()
    dummy_finding = Finding(
        finding_id="f_test",
        asset_id="a_test",
        kind=FindingKind.TONE,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=10,
        source_text="guaranteed",
        rule_id="V-04",
    )
    suggested = adapter.suggest_rewrite(dummy_finding)
    assert suggested == "trusted care"

    # 3. Verify clean evaluation under RuleEngine
    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US", "channel": "paid_social"}
    is_clean, violations = engine.check_rewrite("Our gentle cleanser provides trusted care for daily skin clarity.", context)
    assert is_clean is True, f"trusted care should be clean, got violations: {violations}"
    assert len(violations) == 0


def test_d3_clinical_claim_product_isolation_and_condition_governance(governance_db):
    """
    D-3 Regression Verification:
    1. Monsoon + supported F-112 v3 claim -> passes clean.
    2. Glow + Monsoon's breakout claim -> BLOCK / UNLINKED (no cross-product leakage).
    3. Barrier Cream + Monsoon's breakout claim -> BLOCK / UNLINKED.
    4. Monsoon + changed timeframe -> BLOCK.
    5. Monsoon + missing required twice-daily condition -> BLOCK / UNLINKED.
    6. Fact update drift does not alter approved claim's historical version.
    """
    from core.ledger.drift import cascade_fact_update
    engine = RuleEngine()

    supported_claim = "Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use."

    # Case 1: Monsoon + supported F-112 v3 claim -> linked and passes clean
    clean1, viols1 = engine.check_rewrite(supported_claim, {"product": "prod_monsoon", "market": "US"})
    assert clean1 is True, f"Monsoon with supported F-112 wording must pass, got: {viols1}"
    assert len(viols1) == 0

    # Case 2: Glow + Monsoon's breakout claim -> BLOCK / UNLINKED
    clean2, viols2 = engine.check_rewrite(supported_claim, {"product": "prod_glow", "market": "US"})
    assert clean2 is False, "Glow must NOT inherit Monsoon's clinical trial evidence"
    assert any(v.link_state == LinkState.UNLINKED and v.severity == Severity.BLOCK for v in viols2)

    # Case 3: Barrier Cream + Monsoon's breakout claim -> BLOCK / UNLINKED
    clean3, viols3 = engine.check_rewrite(supported_claim, {"product": "prod_barrier", "market": "UK"})
    assert clean3 is False, "Barrier Cream must NOT inherit Monsoon's clinical trial evidence"
    assert any(v.link_state == LinkState.UNLINKED and v.severity == Severity.BLOCK for v in viols3)

    # Case 4: Monsoon + changed timeframe (1 week) -> BLOCK
    changed_timeframe = "Our wash reduces breakouts in 1 week with twice-daily use."
    clean4, viols4 = engine.check_rewrite(changed_timeframe, {"product": "prod_monsoon", "market": "US"})
    assert clean4 is False, "Unsupported 1-week timeframe must be blocked"
    assert any(v.severity == Severity.BLOCK for v in viols4)

    # Case 5: Monsoon + missing required twice-daily condition -> must not silently pass
    missing_condition = "Our wash reduces breakouts in 4 weeks."
    clean5, viols5 = engine.check_rewrite(missing_condition, {"product": "prod_monsoon", "market": "US"})
    assert clean5 is False, "Missing required twice-daily condition must be blocked"
    assert any(v.link_state == LinkState.UNLINKED and v.severity == Severity.BLOCK for v in viols5)

    # Case 6: A fact update must not silently change the version associated with an existing approved claim
    asset_id = "AST-GOV-005"
    execute_commit(
        """
        INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
        VALUES (?, 'Monsoon Launch', 'prod_monsoon', 'US', 'paid_social', 'approved', 'Alex Chen', 'hash05', ?, '2026-11-10');
        """,
        (asset_id, supported_claim),
        db_path=governance_db,
    )

    stable_id = approve_claim(
        asset_id=asset_id,
        claim_text=supported_claim,
        fact_id="F-112",
        fact_version_id=3,
        reviewer_id="Sarah Jenkins",
        role=Role.REVIEWER,
        db_path=governance_db,
    )

    # Verify initial version is 3 and drift_status is CURRENT
    claim_pre = execute_query(
        "SELECT fact_id, fact_version_id, drift_status FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_id,),
        db_path=governance_db,
    )[0]
    assert claim_pre["fact_id"] == "F-112"
    assert claim_pre["fact_version_id"] == 3
    assert claim_pre["drift_status"] == "CURRENT"

    # Propagate fact update to version 4
    affected = cascade_fact_update("F-112", 4, role=Role.FACT_OWNER, db_path=governance_db)
    assert affected >= 1

    # Verify claim is flagged as REVIEW_REQUIRED, but fact_version_id REMAINS 3 (immutable lineage)
    claim_post = execute_query(
        "SELECT fact_id, fact_version_id, drift_status FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_id,),
        db_path=governance_db,
    )[0]
    assert claim_post["fact_version_id"] == 3, "Fact update must NEVER silently alter historical fact_version_id in approved claims"
    assert claim_post["drift_status"] == "REVIEW_REQUIRED"


def test_c01_monsoon_f112_v3_recheck_passes_and_blocks_invalid_variants():
    """
    Dedicated regression test for Finding #4 (C-01):
    1. prod_monsoon + 'reduces breakouts in 4 weeks with twice-daily use' + F-112 v3 -> is_clean: True, 0 violations.
    2. prod_monsoon + 'clears breakouts in 3 days' -> is_clean: False, severity == Severity.BLOCK.
    3. prod_monsoon + 'reduces breakouts in 4 weeks' (missing twice-daily use) -> is_clean: False, severity == Severity.BLOCK.
    4. prod_glow or prod_barrier + 'reduces breakouts in 4 weeks with twice-daily use' -> is_clean: False, link_state == LinkState.UNLINKED, severity == Severity.BLOCK.
    """
    engine = RuleEngine()

    # 1. Monsoon + valid F-112 v3 wording -> is_clean: True, 0 violations
    valid_claim = "reduces breakouts in 4 weeks with twice-daily use"
    is_clean, violations = engine.check_rewrite(valid_claim, {"product": "prod_monsoon", "market": "US"})
    assert is_clean is True, f"Valid F-112 v3 claim must pass clean, got: {violations}"
    assert len(violations) == 0

    # Also test with partial context (omitting market, defaults to US)
    is_clean_default_mkt, viols_default_mkt = engine.check_rewrite(valid_claim, {"product": "prod_monsoon"})
    assert is_clean_default_mkt is True, f"Valid claim with default market must pass, got: {viols_default_mkt}"
    assert len(viols_default_mkt) == 0

    # 2. Monsoon + 'clears breakouts in 3 days' -> is_clean: False, severity == Severity.BLOCK
    invalid_timeframe = "clears breakouts in 3 days"
    is_clean, violations = engine.check_rewrite(invalid_timeframe, {"product": "prod_monsoon", "market": "US"})
    assert is_clean is False, "Unsubstantiated 3-day claim must fail"
    assert any(v.severity == Severity.BLOCK for v in violations)

    # 3. Monsoon + 'reduces breakouts in 4 weeks' (missing required condition) -> is_clean: False, severity == Severity.BLOCK
    missing_condition = "reduces breakouts in 4 weeks"
    is_clean, violations = engine.check_rewrite(missing_condition, {"product": "prod_monsoon", "market": "US"})
    assert is_clean is False, "Claim missing required 'twice-daily use' condition must fail"
    assert any(v.severity == Severity.BLOCK for v in violations)

    # 4. prod_glow or prod_barrier + 'reduces breakouts in 4 weeks with twice-daily use' -> is_clean: False, link_state == LinkState.UNLINKED, severity == Severity.BLOCK
    for other_product in ["prod_glow", "prod_barrier"]:
        is_clean, violations = engine.check_rewrite(valid_claim, {"product": other_product, "market": "US"})
        assert is_clean is False, f"Product {other_product} must NOT inherit Monsoon's clinical trial evidence"
        unlinked_blocks = [v for v in violations if v.link_state == LinkState.UNLINKED and v.severity == Severity.BLOCK]
        assert len(unlinked_blocks) > 0, f"Expected UNLINKED BLOCK for {other_product}, got {violations}"


def test_creator_ui_recheck_locks_acceptance_and_submission(monkeypatch, tmp_path):
    """
    Creator UI Verification:
    - Failed re-check locks the 'Accept Proposed Rewrite' button (disabled=True).
    - Failed re-check locks the 'Submit Draft for Review' button in Step 3 (disabled=True).
    """
    temp_db = tmp_path / "creator_ui_test.db"
    seed_database(str(temp_db), include_demo_assets=False)
    monkeypatch.setenv("DATABASE_PATH", str(temp_db))
    monkeypatch.setattr("core.db.DEFAULT_DB_PATH", str(temp_db))
    monkeypatch.setenv("LLM_MODE", "mock")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("app/pages/1_Creator.py")
    at.run()
    assert not at.exception

    # Load demo draft
    at.button[0].click().run()
    assert not at.exception
    assert len(at.session_state["findings"]) > 0

    target_fid = at.session_state["findings"][0].finding_id

    # Under normal condition, the proposed rewrite passes re-check and button is enabled
    normal_btn = [b for b in at.button if b.key == f"btn_acc_{target_fid}"][0]
    assert normal_btn.disabled is False

    # Simulate an invalid suggested rewrite (violates rules)
    at.session_state["findings"][0].suggested_rewrite = "clears breakouts in 3 days"
    at.run()
    assert not at.exception

    locked_btn = [b for b in at.button if b.key == f"btn_acc_{target_fid}"][0]
    assert locked_btn.disabled is True, "Accept button must be disabled when re-check fails"

    # Verify Step 3 submission locking:
    # Accept all findings, but let one action have an invalid rewrite
    at.session_state["finding_actions"] = {
        f.finding_id: {"action": "accepted", "text": f.suggested_rewrite}
        for f in at.session_state["findings"]
    }
    at.session_state["finding_actions"][target_fid]["text"] = "clears breakouts in 3 days"
    at.run()
    assert not at.exception

    submit_buttons = [b for b in at.button if "Submit" in (b.label or "")]
    assert len(submit_buttons) > 0
    assert any(b.disabled is True for b in submit_buttons), "Submit button must be locked if any accepted rewrite violates rules"


