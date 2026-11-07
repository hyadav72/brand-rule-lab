"""
Brand Rule Lab — Demo Queue Seed Assets (BLK-04) Regression Tests
Owned by Agent A5 & A1.

Tests required by BLK-04:
1. Both new demo assets (AST-DIWALI-01, AST-SUNSCREEN-01) are created.
2. Both appear in the Reviewer queue with ready_for_review status.
3. Each has the expected valid findings.
4. All findings reference valid existing rules or fact versions.
5. Existing Monsoon data (AST-MONSOON-01) remains unchanged.
6. Repeated seeding creates no duplicates (strict idempotency).
7. Seed tests use disposable databases only.
8. No fabricated approval history or reviewer events for new demo assets.
"""

import pytest
import sqlite3
from pathlib import Path

from core.db import execute_query, get_connection
from core.seed import seed_database


@pytest.fixture
def disposable_seed_db(tmp_path):
    """Provide a fresh disposable database seeded with demo assets."""
    db_file = tmp_path / "disposable_demo_seed.db"
    db_path = str(db_file)
    counts = seed_database(db_path, include_demo_assets=True)
    assert counts["assets"] == 3
    return db_path


def test_demo_assets_created_and_appear_in_reviewer_queue(disposable_seed_db):
    """AST-DIWALI-01 and AST-SUNSCREEN-01 are created with ready_for_review status."""
    db = disposable_seed_db

    rows = execute_query(
        "SELECT asset_id, name, product_id, market, channel, status, created_by FROM assets ORDER BY asset_id ASC;",
        db_path=db,
    )
    asset_ids = [r["asset_id"] for r in rows]

    assert "AST-MONSOON-01" in asset_ids
    assert "AST-DIWALI-01" in asset_ids
    assert "AST-SUNSCREEN-01" in asset_ids

    assets_by_id = {r["asset_id"]: r for r in rows}

    # Verify AST-DIWALI-01
    diwali = assets_by_id["AST-DIWALI-01"]
    assert diwali["status"] == "ready_for_review"
    assert diwali["channel"] == "email"
    assert diwali["market"] == "US"
    assert diwali["product_id"] == "prod_monsoon"
    assert "Demo" in diwali["name"]

    # Verify AST-SUNSCREEN-01
    sunscreen = assets_by_id["AST-SUNSCREEN-01"]
    assert sunscreen["status"] == "ready_for_review"
    assert sunscreen["channel"] == "pdp"
    assert sunscreen["market"] == "UK"
    assert sunscreen["product_id"] == "prod_barrier"
    assert "Demo" in sunscreen["name"]


def test_demo_assets_have_expected_valid_findings(disposable_seed_db):
    """AST-DIWALI-01 and AST-SUNSCREEN-01 have realistic, deterministic findings."""
    db = disposable_seed_db

    # 1. Diwali findings
    diwali_findings = execute_query(
        "SELECT finding_id, rule_id, fact_id, fact_version_id, link_state, kind, severity FROM findings WHERE asset_id = 'AST-DIWALI-01' ORDER BY span_start ASC;",
        db_path=db,
    )
    assert len(diwali_findings) == 3

    # Finding 1: C-01 linked to F-OFFER-01 v1
    assert diwali_findings[0]["rule_id"] == "C-01"
    assert diwali_findings[0]["fact_id"] == "F-OFFER-01"
    assert diwali_findings[0]["fact_version_id"] == 1
    assert diwali_findings[0]["link_state"] == "LINKED"

    # Finding 2: T-08 terminology on 'miracle'
    assert diwali_findings[1]["rule_id"] == "T-08"
    assert diwali_findings[1]["link_state"] == "UNLINKED"

    # Finding 3: T-15 tone on 'zero breakouts forever'
    assert diwali_findings[2]["rule_id"] == "T-15"
    assert diwali_findings[2]["link_state"] == "UNLINKED"

    # 2. Sunscreen findings
    sunscreen_findings = execute_query(
        "SELECT finding_id, rule_id, fact_id, fact_version_id, link_state, kind, severity FROM findings WHERE asset_id = 'AST-SUNSCREEN-01' ORDER BY span_start ASC;",
        db_path=db,
    )
    assert len(sunscreen_findings) == 3

    # Finding 1: C-01 linked to F-302 v1
    assert sunscreen_findings[0]["rule_id"] == "C-01"
    assert sunscreen_findings[0]["fact_id"] == "F-302"
    assert sunscreen_findings[0]["fact_version_id"] == 1
    assert sunscreen_findings[0]["link_state"] == "LINKED"

    # Finding 2: T-05 misleading natural claim on '100% natural'
    assert sunscreen_findings[1]["rule_id"] == "T-05"
    assert sunscreen_findings[1]["link_state"] == "UNLINKED"

    # Finding 3: V-04 tone on 'guaranteed'
    assert sunscreen_findings[2]["rule_id"] == "V-04"
    assert sunscreen_findings[2]["link_state"] == "UNLINKED"


def test_findings_reference_valid_rules_and_facts(disposable_seed_db):
    """All findings on demo assets reference registered rules and existing approved fact versions."""
    db = disposable_seed_db

    findings = execute_query(
        "SELECT finding_id, asset_id, rule_id, fact_id, fact_version_id FROM findings WHERE asset_id IN ('AST-MONSOON-01', 'AST-DIWALI-01', 'AST-SUNSCREEN-01');",
        db_path=db,
    )

    registered_rules = {r["rule_id"] for r in execute_query("SELECT rule_id FROM rules;", db_path=db)}

    for f in findings:
        # Verify rule exists
        if f["rule_id"]:
            assert f["rule_id"] in registered_rules, f"Finding {f['finding_id']} cites unknown rule {f['rule_id']}"

        # Verify fact exists if linked
        if f["fact_id"]:
            fact_row = execute_query(
                "SELECT fact_id, version FROM fact_versions WHERE fact_id = ? AND version = ?;",
                (f["fact_id"], f["fact_version_id"]),
                db_path=db,
            )
            assert len(fact_row) == 1, f"Finding {f['finding_id']} cites unknown fact version {f['fact_id']} v{f['fact_version_id']}"


def test_existing_monsoon_data_remains_unchanged(disposable_seed_db):
    """Preserves existing AST-MONSOON-01 asset, its 5 findings, and its approved claim."""
    db = disposable_seed_db

    monsoon_asset = execute_query(
        "SELECT * FROM assets WHERE asset_id = 'AST-MONSOON-01';",
        db_path=db,
    )
    assert len(monsoon_asset) == 1
    assert monsoon_asset[0]["status"] == "ready_for_review"

    monsoon_findings = execute_query(
        "SELECT finding_id, rule_id, fact_id, fact_version_id, link_state, kind, severity, span_start, span_end, source_text FROM findings WHERE asset_id = 'AST-MONSOON-01' ORDER BY span_start ASC;",
        db_path=db,
    )
    assert len(monsoon_findings) == 5
    fids = [f["finding_id"] for f in monsoon_findings]
    assert fids == ["FND-D02-0", "FND-V04-20", "FND-T12-38", "FND-C01-47", "FND-V04-100"]

    # Verify restored FND-D02-0 provenance and attributes
    d02 = next(f for f in monsoon_findings if f["finding_id"] == "FND-D02-0")
    assert d02["rule_id"] == "D-02"
    assert d02["fact_id"] == "F-OFFER-02"
    assert d02["fact_version_id"] == 1
    assert d02["link_state"] == "LINKED"
    assert d02["kind"] == "offer_date"
    assert d02["severity"] == "block"
    assert d02["span_start"] == 0
    assert d02["span_end"] == 30
    assert d02["source_text"] == "Say goodbye to acne forever! O"

    claims = execute_query(
        "SELECT stable_claim_id, fact_id, fact_version_id, drift_status FROM approved_claims WHERE asset_id = 'AST-MONSOON-01';",
        db_path=db,
    )
    assert len(claims) == 1
    assert claims[0]["stable_claim_id"] == "SC-4fd5"
    assert claims[0]["drift_status"] == "CURRENT"


def test_repeated_seeding_creates_no_duplicates(disposable_seed_db):
    """Running seed_database repeatedly is strictly idempotent with zero duplicates."""
    db = disposable_seed_db

    # Run seed process 3 additional times
    seed_database(db, include_demo_assets=True)
    seed_database(db, include_demo_assets=True)
    seed_database(db, include_demo_assets=True)

    assets = execute_query("SELECT COUNT(*) as cnt FROM assets WHERE asset_id IN ('AST-MONSOON-01', 'AST-DIWALI-01', 'AST-SUNSCREEN-01');", db_path=db)
    assert assets[0]["cnt"] == 3

    findings = execute_query("SELECT asset_id, COUNT(*) as cnt FROM findings GROUP BY asset_id ORDER BY asset_id ASC;", db_path=db)
    counts_by_asset = {r["asset_id"]: r["cnt"] for r in findings}
    assert counts_by_asset["AST-MONSOON-01"] == 5
    assert counts_by_asset["AST-DIWALI-01"] == 3
    assert counts_by_asset["AST-SUNSCREEN-01"] == 3

    # Ensure repeated seeding does not duplicate the restored finding
    d02_rows = execute_query("SELECT COUNT(*) as cnt FROM findings WHERE finding_id = 'FND-D02-0';", db_path=db)
    assert d02_rows[0]["cnt"] == 1

    claims = execute_query("SELECT COUNT(*) as cnt FROM approved_claims;", db_path=db)
    assert claims[0]["cnt"] == 1  # Only Monsoon pre-approved claim


def test_reviewer_queue_query_matches_app_page(disposable_seed_db):
    """The exact Reviewer queue SQL query retrieves all 3 demo assets with correct counts."""
    db = disposable_seed_db

    # Exact query from app/pages/2_Reviewer.py lines 35-43
    queue_assets = execute_query(
        """
        SELECT a.asset_id, a.name, a.product_id, a.market, a.channel, a.status, a.created_by,
               a.planned_publish_date, a.text_content, a.review_cycle, COUNT(f.finding_id) as finding_count
        FROM assets a
        LEFT JOIN findings f ON a.asset_id = f.asset_id AND f.review_cycle = a.review_cycle
        GROUP BY a.asset_id
        ORDER BY a.created_at DESC;
        """,
        db_path=db,
    )

    assert len(queue_assets) == 3
    queue_map = {a["asset_id"]: a for a in queue_assets}

    assert queue_map["AST-MONSOON-01"]["finding_count"] == 5
    assert queue_map["AST-DIWALI-01"]["finding_count"] == 3
    assert queue_map["AST-SUNSCREEN-01"]["finding_count"] == 3

    for aid in ("AST-MONSOON-01", "AST-DIWALI-01", "AST-SUNSCREEN-01"):
        assert queue_map[aid]["status"] == "ready_for_review"

    # Confirm no fabricated approval history for the new demo assets
    for aid in ("AST-DIWALI-01", "AST-SUNSCREEN-01"):
        appr = execute_query("SELECT * FROM approved_claims WHERE asset_id = ?;", (aid,), db_path=db)
        assert len(appr) == 0, f"Demo asset {aid} should NOT have fabricated approval records"
