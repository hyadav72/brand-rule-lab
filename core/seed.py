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


def seed_database(db_path: Optional[str] = None) -> Dict[str, int]:
    """Orchestrate complete idempotent seed ingestion."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        p_count = seed_products(conn)
        f_count = seed_facts(conn)
        r_count = seed_rules(conn)
        u_count = seed_users(conn)

    return {
        "products": p_count,
        "facts": f_count,
        "rules": r_count,
        "users": u_count,
    }


if __name__ == "__main__":
    results = seed_database()
    print("Database seeding completed:", results)
