"""
Brand Rule Lab — Seed Data Importer
Owned by Agent A1 (Backend & Data Engineer).

Imports initial synthetic data:
- Products (data/products.csv)
- Approved Fact Versions (data/facts.csv)
- Registered Rules (data/rules/*.json)
- Default Demo Users
"""

from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from core.db import get_connection, init_db

DATA_DIR = Path(__file__).parent.parent / "data"
PRODUCTS_CSV = DATA_DIR / "products.csv"
FACTS_CSV = DATA_DIR / "facts.csv"
RULES_DIR = DATA_DIR / "rules"

DEFAULT_USERS = [
    ("user_creator", "Alex Chen (Creator)", "creator"),
    ("user_reviewer", "Sarah Jenkins (Reviewer)", "reviewer"),
    ("user_fact_owner", "Dr. Elena Rostova (Fact Owner)", "fact_owner"),
]


def validate_iso_date(date_str: Optional[str]) -> bool:
    """Verify YYYY-MM-DD date format."""
    if not date_str:
        return True
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def seed_products(conn, csv_path: Path = PRODUCTS_CSV) -> int:
    """Seed products from CSV with validation."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Products seed CSV missing: {csv_path}")

    inserted = 0
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["product_id"].strip()
            name = row["name"].strip()
            sku_aliases = row["sku_aliases"].strip()
            market = row["market"].strip()

            # Validate json format of sku_aliases
            try:
                json.loads(sku_aliases)
            except Exception:
                # If raw string, convert to JSON array
                sku_aliases = json.dumps([a.strip() for a in sku_aliases.split(",")])

            conn.execute(
                """
                INSERT INTO products (product_id, name, sku_aliases, market)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    name = excluded.name,
                    sku_aliases = excluded.sku_aliases,
                    market = excluded.market;
                """,
                (pid, name, sku_aliases, market),
            )
            inserted += 1
    return inserted


def seed_facts(conn, csv_path: Path = FACTS_CSV) -> int:
    """Seed approved fact versions from CSV with strict validation."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Facts seed CSV missing: {csv_path}")

    inserted = 0
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fact_id = row["fact_id"].strip()
            version = int(row["version"].strip())
            product_id = row["product_id"].strip()
            market = row["market"].strip()
            fact_text = row["fact_text"].strip()
            permitted_wording = row["permitted_wording"].strip()
            valid_from = row["valid_from"].strip()
            expires_at = row["expires_at"].strip() if row.get("expires_at") else None
            owner = row.get("owner", "brand_science").strip()

            # Strict validations
            if not owner:
                raise ValueError(f"Fact {fact_id} v{version} missing mandatory owner field")
            if not validate_iso_date(valid_from):
                raise ValueError(f"Invalid valid_from date format for {fact_id} v{version}: {valid_from}")
            if expires_at and not validate_iso_date(expires_at):
                raise ValueError(f"Invalid expires_at date format for {fact_id} v{version}: {expires_at}")

            conn.execute(
                """
                INSERT INTO fact_versions (
                    fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_id, version) DO UPDATE SET
                    product_id = excluded.product_id,
                    market = excluded.market,
                    fact_text = excluded.fact_text,
                    permitted_wording = excluded.permitted_wording,
                    valid_from = excluded.valid_from,
                    expires_at = excluded.expires_at,
                    owner = excluded.owner;
                """,
                (fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner),
            )
            inserted += 1
    return inserted


def seed_rules(conn, rules_dir: Path = RULES_DIR) -> int:
    """Seed rule specifications from JSON files."""
    if not rules_dir.exists():
        return 0

    inserted = 0
    for rule_file in rules_dir.glob("*.json"):
        rule_spec = json.loads(rule_file.read_text(encoding="utf-8"))
        rule_id = rule_spec["rule_id"]
        pred_type = rule_spec["predicate_type"]
        scope = json.dumps(rule_spec.get("scope", {}))
        params = json.dumps(rule_spec.get("parameters", {}))
        approved = 1 if rule_spec.get("owner_approved", False) else 0
        version = rule_spec.get("version", 1)

        conn.execute(
            """
            INSERT INTO rules (rule_id, predicate_type, scope, parameters_json, owner_approved, version)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                predicate_type = excluded.predicate_type,
                scope = excluded.scope,
                parameters_json = excluded.parameters_json,
                owner_approved = excluded.owner_approved,
                version = excluded.version;
            """,
            (rule_id, pred_type, scope, params, approved, version),
        )
        inserted += 1
    return inserted


def seed_users(conn) -> int:
    """Seed demo personas for role picker."""
    inserted = 0
    for user_id, display_name, role in DEFAULT_USERS:
        conn.execute(
            """
            INSERT INTO users (user_id, display_name, role)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                role = excluded.role;
            """,
            (user_id, display_name, role),
        )
        inserted += 1
    return inserted


def seed_demo_assets(conn) -> int:
    """Seed demo marketing assets in ready_for_review queue with findings and ledger claim."""
    # 1. AST-MONSOON-01 (Monsoon Clear Skin Launch Campaign)
    conn.execute(
        """
        INSERT INTO assets (
            asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
        ) VALUES (
            'AST-MONSOON-01', 'Monsoon Clear Skin Launch Campaign', 'prod_monsoon', 'US', 'paid_social',
            'ready_for_review', 'Alex Chen (Creator)', 'a1b2c3d4e5',
            'Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days. Dermatologist tested and guaranteed to work.',
            '2026-11-20'
        )
        ON CONFLICT(asset_id) DO UPDATE SET
            status = excluded.status,
            text_content = excluded.text_content,
            planned_publish_date = excluded.planned_publish_date;
        """
    )
    monsoon_findings = [
        ("FND-D02-0", "AST-MONSOON-01", "offer_date", "block", 0, 30, "Say goodbye to acne forever! O", "D-02", "F-OFFER-02", 1, "LINKED", "Planned publication date '2026-11-20' is after offer expires (2026-11-12).", "Adjust promotional offer date to end on or before approved deadline 2026-11-12.", "Flash sale ends 2026-11-12"),
        ("FND-V04-20", "AST-MONSOON-01", "tone", "block", 20, 27, "forever", "V-04", None, None, "UNLINKED", "Absolute claim 'forever' violates brand tone guidelines. Use qualified non-absolute wording.", "Replace with qualified wording (e.g., 'long-term').", "long-term"),
        ("FND-T12-38", "AST-MONSOON-01", "terminology", "block", 38, 41, "BPO", "T-12", None, None, "UNLINKED", "Abbreviation 'BPO' is prohibited in consumer copy under FDA/ASCI labeling guidelines.", "Expand to full approved chemical name 'Benzoyl Peroxide'.", "Benzoyl Peroxide"),
        ("FND-C01-47", "AST-MONSOON-01", "claim", "block", 47, 73, "clears breakouts in 3 days", "C-01", "F-112", 3, "LINKED", "Claim mismatch: turnaround of 3 days contradicts approved trial baseline (minimum 28 days). Approved fact F-112 v3 supports a 4-week clinical trial statement.", "Align claim with approved wording: 'reduces breakouts in 4 weeks with twice-daily use'.", "reduces breakouts in 4 weeks with twice-daily use"),
        ("FND-V04-100", "AST-MONSOON-01", "tone", "block", 100, 110, "guaranteed", "V-04", None, None, "UNLINKED", "Absolute claim 'guaranteed' violates brand tone guidelines. Use qualified non-absolute wording.", "Replace with qualified wording (e.g., 'trusted care').", "trusted care"),
    ]
    for fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew in monsoon_findings:
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, fact_id, fact_version_id, link_state, message, next_step, suggested_rewrite, creator_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted')
            ON CONFLICT(finding_id) DO UPDATE SET
                message = excluded.message,
                suggested_rewrite = excluded.suggested_rewrite;
            """,
            (fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew),
        )

    conn.execute(
        """
        INSERT INTO approved_claims (
            stable_claim_id, asset_id, claim_text, approved_text_hash, fact_id, fact_version_id, drift_status, approved_by, approved_at
        ) VALUES (
            'SC-4fd5', 'AST-MONSOON-01', 'Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use.',
            'hash_approved_01', 'F-112', 3, 'CURRENT', 'Sarah Jenkins (Reviewer)', '2026-11-04 18:00:00'
        )
        ON CONFLICT(stable_claim_id) DO UPDATE SET
            drift_status = excluded.drift_status;
        """
    )

    # 2. AST-DIWALI-01 (Diwali Festival Offer Email)
    diwali_text = "Celebrate Diwali with radiant skin! Save 20% on all Monsoon bundles through Oct 31 with our miracle formula for zero breakouts forever."
    conn.execute(
        """
        INSERT INTO assets (
            asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
        ) VALUES (
            'AST-DIWALI-01', 'Diwali Festival Offer Email (Demo)', 'prod_monsoon', 'US', 'email',
            'ready_for_review', 'Alex Chen (Creator)', 'd1w4l1h4sh01',
            ?, '2026-10-25'
        )
        ON CONFLICT(asset_id) DO UPDATE SET
            status = excluded.status,
            text_content = excluded.text_content,
            planned_publish_date = excluded.planned_publish_date;
        """,
        (diwali_text,),
    )
    diwali_findings = [
        (
            "FND-C01-36-DIWALI01-C1",
            "AST-DIWALI-01",
            "claim",
            "block",
            36,
            82,
            "Save 20% on all Monsoon bundles through Oct 31",
            "C-01",
            "F-OFFER-01",
            1,
            "LINKED",
            "Promotional claim matches approved fact F-OFFER-01 v1 (Diwali early-bird 20% bundle discount).",
            "Align wording with approved statement: 'Save 20% on bundles through Oct 31.'.",
            "Save 20% on bundles through Oct 31.",
            "accepted",
        ),
        (
            "FND-T08-92-DIWALI01-C1",
            "AST-DIWALI-01",
            "terminology",
            "block",
            92,
            99,
            "miracle",
            "T-08",
            None,
            None,
            "UNLINKED",
            "Superlative term 'miracle' violates ASCI and FTC substantiation standards for cosmetic products.",
            "Replace with approved terminology: 'proven'.",
            "proven",
            "accepted",
        ),
        (
            "FND-T15-112-DIWALI01-C1",
            "AST-DIWALI-01",
            "tone",
            "block",
            112,
            134,
            "zero breakouts forever",
            "T-15",
            None,
            None,
            "UNLINKED",
            "Universal outcome claim 'zero breakouts forever' violates truth-in-advertising guidelines.",
            "Replace with qualified wording: 'helps reduce the frequency of blemishes'.",
            "helps reduce the frequency of blemishes",
            "accepted",
        ),
    ]
    for fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew, caction in diwali_findings:
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, fact_id, fact_version_id, link_state, message, next_step, suggested_rewrite, creator_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(finding_id) DO UPDATE SET
                message = excluded.message,
                suggested_rewrite = excluded.suggested_rewrite,
                creator_action = excluded.creator_action;
            """,
            (fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew, caction),
        )

    # 3. AST-SUNSCREEN-01 (Sunscreen PDP)
    sunscreen_text = "Daily mineral sunscreen with broad spectrum SPF 50. Formulated with 3 essential ceramides and hyaluronic acid for 100% natural protection guaranteed."
    conn.execute(
        """
        INSERT INTO assets (
            asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
        ) VALUES (
            'AST-SUNSCREEN-01', 'Ceramide Sunscreen Daily PDP (Demo)', 'prod_barrier', 'UK', 'pdp',
            'ready_for_review', 'Alex Chen (Creator)', 'sunscr33nh4sh01',
            ?, '2026-11-15'
        )
        ON CONFLICT(asset_id) DO UPDATE SET
            status = excluded.status,
            text_content = excluded.text_content,
            planned_publish_date = excluded.planned_publish_date;
        """,
        (sunscreen_text,),
    )
    sunscreen_findings = [
        (
            "FND-C01-68-SUNSCREEN01-C1",
            "AST-SUNSCREEN-01",
            "claim",
            "block",
            68,
            109,
            "3 essential ceramides and hyaluronic acid",
            "C-01",
            "F-302",
            1,
            "LINKED",
            "Active ingredient claim verified against approved fact F-302 v1.",
            "Maintain approved formulation wording: '3 essential ceramides and hyaluronic acid.'.",
            "3 essential ceramides and hyaluronic acid",
            "accepted",
        ),
        (
            "FND-T05-114-SUNSCREEN01-C1",
            "AST-SUNSCREEN-01",
            "claim",
            "block",
            114,
            126,
            "100% natural",
            "T-05",
            None,
            None,
            "UNLINKED",
            "Misleading claim '100% natural' violates truth-in-advertising guidelines.",
            "Remove absolute chemical-free/natural claims or link to certified organic fact.",
            "formulated with gentle ingredients",
            "accepted",
        ),
        (
            "FND-V04-138-SUNSCREEN01-C1",
            "AST-SUNSCREEN-01",
            "tone",
            "block",
            138,
            148,
            "guaranteed",
            "V-04",
            None,
            None,
            "UNLINKED",
            "Absolute claim 'guaranteed' violates brand tone guidelines. Use qualified non-absolute wording.",
            "Replace with qualified wording (e.g., 'trusted care').",
            "trusted daily protection",
            "accepted",
        ),
    ]
    for fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew, caction in sunscreen_findings:
        conn.execute(
            """
            INSERT INTO findings (
                finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                rule_id, fact_id, fact_version_id, link_state, message, next_step, suggested_rewrite, creator_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(finding_id) DO UPDATE SET
                message = excluded.message,
                suggested_rewrite = excluded.suggested_rewrite,
                creator_action = excluded.creator_action;
            """,
            (fid, aid, kind, sev, s_start, s_end, stext, rid, fact_id, fver, lstate, msg, nstep, srew, caction),
        )

    return 3


def seed_database(db_path: Optional[str] = None, include_demo_assets: bool = False) -> Dict[str, int]:
    """Orchestrate complete idempotent seed ingestion."""
    from core.db import get_db_path
    from core.migrations.runner import is_production_database

    target_path = get_db_path(db_path)
    if is_production_database(target_path):
        raise PermissionError(
            f"Seeding the protected production database '{target_path}' is strictly prohibited. "
            "Production database must remain untouched."
        )

    init_db(target_path)
    with get_connection(target_path) as conn:
        p_count = seed_products(conn)
        f_count = seed_facts(conn)
        r_count = seed_rules(conn)
        u_count = seed_users(conn)
        a_count = seed_demo_assets(conn) if include_demo_assets else 0

    return {
        "products": p_count,
        "facts": f_count,
        "rules": r_count,
        "users": u_count,
        "assets": a_count,
    }


if __name__ == "__main__":
    results = seed_database(include_demo_assets=True)
    print("Database seeding completed:", results)
