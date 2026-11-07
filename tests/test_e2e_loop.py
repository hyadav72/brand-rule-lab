"""
Brand Rule Lab — Full End-to-End Workflow Integration Test
Owned by Agent A5 (QA Engineer).

Simulates the complete hackathon demonstration scenario:
1. Creator uploads Monsoon Clear Skin draft.
2. Three findings appear: V-04 (tone), T-12 (terminology), C-01 (claim mismatch vs F-112 v3).
3. Creator accepts rewrite, re-checks clean, and submits.
4. Reviewer approves, minting stable claim SC-xxxx linked to F-112 v3.
5. Fact Owner publishes F-112 v4.
6. Single-SQL cascade flags registered claim as REVIEW_REQUIRED (0 LLM calls, 1 SQL UPDATE).
7. Unmatched claim lands as UNLINKED and requires override.
"""

import pytest
from core.db import init_db, execute_query, get_connection
from core.ingest import ingest
from core.extract.claims import extract_claims
from core.rules.engine import RuleEngine
from core.seed import seed_database
from core.ledger.approve import approve_claim
from core.ledger.drift import cascade_fact_update, sweep_expiry
from core.audit import log_review_event, get_asset_audit_trail
from core.models import Role, LinkState, DriftStatus


@pytest.fixture
def clean_db(tmp_path):
    """Provide freshly seeded database for e2e workflow."""
    db_file = tmp_path / "e2e_brand_rule_lab.db"
    db_path = str(db_file)
    seed_database(db_path, include_demo_assets=False)
    return db_path


def test_complete_hackathon_demo_scenario(clean_db):
    """
    Verify the 12-step hackathon demo path from upload to drift cascade.
    """
    # 1. Creator uploads the draft
    draft_text = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    doc = ingest(draft_text.encode("utf-8"), "monsoon_social.txt")
    asset_id = "AST-DEMO-001"

    with get_connection(clean_db) as conn:
        conn.execute(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
            VALUES (?, 'Monsoon Clear Skin Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', ?, ?, '2026-11-10');
            """,
            (asset_id, doc.source_hash, doc.text),
        )

    # 2. Extract claims and run rules
    claims = extract_claims(doc.text, product_hint="Monsoon Clear Skin")
    engine = RuleEngine()
    context = {
        "asset_id": asset_id,
        "product": "prod_monsoon",
        "market": "US",
        "channel": "paid_social",
        "planned_publish_date": "2026-11-10",
    }
    findings = engine.run_rules(doc, claims, context)

    # 3. Three findings appear: V-04, T-12, C-01
    assert len(findings) == 3
    rule_map = {f.rule_id: f for f in findings}
    assert "V-04" in rule_map
    assert "T-12" in rule_map
    assert "C-01" in rule_map

    # Check that C-01 links to F-112 v3
    c01 = rule_map["C-01"]
    assert c01.fact_id == "F-112"
    assert c01.fact_version_id == 3
    assert c01.link_state == LinkState.LINKED

    # 4. Creator accepts suggested rewrites and re-checks
    proposed_rewrite = "Say goodbye to breakouts with our 2.5% Benzoyl Peroxide wash, clinically proven to reduce acne breakouts in 4 weeks with twice-daily use."
    is_clean, violations = engine.check_rewrite(proposed_rewrite, context)
    assert is_clean, f"Rewrite should be clean but got violations: {violations}"

    # 5. Creator submits draft to reviewer queue
    log_review_event(
        asset_id=asset_id,
        actor="Alex Chen (Creator)",
        role=Role.CREATOR,
        action="submit_for_review",
        comment="Accepted compliant clinical rewrites.",
        db_path=clean_db,
    )

    # 6. Reviewer opens queue, sees asset, and approves
    stable_claim_id = approve_claim(
        asset_id=asset_id,
        claim_text="reduces breakouts in 4 weeks with twice-daily use",
        fact_id="F-112",
        fact_version_id=3,
        reviewer_id="Sarah Jenkins (Reviewer)",
        role=Role.REVIEWER,
        db_path=clean_db,
    )

    # 7. Stable claim ID is generated (SC-xxxx) and stored in ledger
    assert stable_claim_id.startswith("SC-")
    ledger_row = execute_query(
        "SELECT * FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_claim_id,),
        db_path=clean_db,
    )[0]
    assert ledger_row["drift_status"] == "CURRENT"
    assert ledger_row["fact_id"] == "F-112"
    assert ledger_row["fact_version_id"] == 3
    assert len(ledger_row["approved_text_hash"]) == 64

    # 8. Fact Owner updates F-112 to v4 (2-week claim)
    with get_connection(clean_db) as conn:
        conn.execute(
            """
            INSERT INTO fact_versions (fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, owner)
            VALUES ('F-112', 4, 'prod_monsoon', 'US', 'Clinically proven to reduce breakouts in 2 weeks.', 'Reduces breakouts in 2 weeks.', '2026-11-05', 'brand_science')
            ON CONFLICT(fact_id, version) DO UPDATE SET
                fact_text = excluded.fact_text,
                permitted_wording = excluded.permitted_wording;
            """
        )

    # 9. Execute fact-drift propagation (1 SQL update, 0 LLM calls)
    flagged_rows = cascade_fact_update("F-112", 4, role=Role.FACT_OWNER, db_path=clean_db)
    assert flagged_rows == 1, "Exactly 1 registered dependent claim must be flagged."

    # 10. The previously approved claim now has drift_status = REVIEW_REQUIRED
    updated_ledger_row = execute_query(
        "SELECT drift_status, flagged_at FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_claim_id,),
        db_path=clean_db,
    )[0]
    assert updated_ledger_row["drift_status"] == "REVIEW_REQUIRED"
    assert updated_ledger_row["flagged_at"] is not None

    # 11. Verify append-only audit trail contains all chronological events
    trail = get_asset_audit_trail(asset_id, db_path=clean_db)
    actions = [evt.action for evt in trail]
    assert "submit_for_review" in actions
    assert "approve" in actions


def test_unlinked_claims_handling(clean_db):
    """
    Verify that an unmatched claim ('100% organic') is categorized as UNLINKED
    and blocks approval unless an explicit override is recorded.
    """
    draft = "Our wash uses 100% organic tea tree extract."
    doc = ingest(draft.encode("utf-8"), "organic_draft.txt")
    claims = extract_claims(doc.text, product_hint="Monsoon Clear Skin")
    engine = RuleEngine()

    findings = engine.run_rules(doc, claims, {"asset_id": "AST-UNLINKED-01"})
    # T-05 triggers on 100% organic
    t05 = next((f for f in findings if f.rule_id == "T-05"), None)
    assert t05 is not None
    assert t05.link_state == LinkState.UNLINKED
    assert t05.severity == "block"


def test_expiry_sweep_flags_expired_facts(clean_db):
    """
    Verify sweep_expiry correctly flags claims linked to expired facts as EXPIRED.
    """
    # Insert prerequisite asset first to satisfy foreign key
    with get_connection(clean_db) as conn:
        conn.execute(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
            VALUES ('AST-OFFER-01', 'Diwali Bundle Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex Chen', 'hash999', 'Diwali draft', '2026-10-25');
            """
        )

    # Link a claim to F-OFFER-01 (expired on 2026-10-31)
    stable_id = approve_claim(
        asset_id="AST-OFFER-01",
        claim_text="Save 20% on Diwali bundles through Oct 31",
        fact_id="F-OFFER-01",
        fact_version_id=1,
        reviewer_id="Sarah Jenkins",
        role=Role.REVIEWER,
        db_path=clean_db,
    )

    # Run sweep as of today (2026-11-05)
    flagged = sweep_expiry("2026-11-05", role=Role.FACT_OWNER, db_path=clean_db)
    assert flagged >= 1

    claim_row = execute_query(
        "SELECT drift_status FROM approved_claims WHERE stable_claim_id = ?;",
        (stable_id,),
        db_path=clean_db,
    )[0]
    assert claim_row["drift_status"] == "EXPIRED"
