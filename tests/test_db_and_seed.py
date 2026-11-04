"""
Brand Rule Lab — Database and Seed Tests
Owned by Agent A5 (QA Engineer).
"""

import sqlite3
import pytest
from core.db import get_connection, init_db, execute_query
from core.seed import seed_database


@pytest.fixture
def test_db(tmp_path):
    """Provide a fresh isolated SQLite database."""
    db_file = tmp_path / "test_brand_rule_lab.db"
    db_path = str(db_file)
    init_db(db_path)
    return db_path


def test_db_initialization_and_tables(test_db):
    """Verify that all schema tables exist with foreign keys."""
    rows = execute_query(
        "SELECT name FROM sqlite_master WHERE type='table';",
        db_path=test_db,
    )
    table_names = {r["name"] for r in rows}
    required_tables = {
        "products",
        "fact_versions",
        "assets",
        "findings",
        "approved_claims",
        "review_events",
        "rules",
        "users",
    }
    assert required_tables.issubset(table_names)


def test_seeding_products_and_facts(test_db):
    """Verify seed_database populates products and facts properly."""
    counts = seed_database(test_db)
    assert counts["products"] == 3
    assert counts["facts"] >= 12
    assert counts["rules"] >= 7
    assert counts["users"] == 3

    # Verify F-112 versions 1-4 exist
    f112_rows = execute_query(
        "SELECT version, fact_text, permitted_wording, valid_from, expires_at FROM fact_versions WHERE fact_id = ? ORDER BY version ASC;",
        ("F-112",),
        db_path=test_db,
    )
    assert len(f112_rows) == 4
    assert f112_rows[2]["version"] == 3  # F-112 v3 is current baseline
    assert "4 weeks" in f112_rows[2]["fact_text"]
    assert f112_rows[3]["version"] == 4  # F-112 v4 is drift target
    assert "2 weeks" in f112_rows[3]["fact_text"]


def test_idempotent_seeding(test_db):
    """Verify that running seed_database multiple times does not duplicate records."""
    seed_database(test_db)
    seed_database(test_db)

    products = execute_query("SELECT COUNT(*) as count FROM products;", db_path=test_db)
    assert products[0]["count"] == 3

    facts = execute_query("SELECT COUNT(*) as count FROM fact_versions;", db_path=test_db)
    assert facts[0]["count"] == 12
