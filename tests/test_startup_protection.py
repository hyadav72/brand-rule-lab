"""
Brand Rule Lab — Startup Database Protection & Safeguards Tests
Verifies:
1. Starting the app with the production database configured performs zero writes.
2. Startup does not create schema_migrations in production.
3. Startup does not execute seed functions against production.
4. Demo database initialization still works.
5. Repeated demo initialization is idempotent.
6. Production migration protection remains enforced.
7. Startup failure stops visibly without partial state.
"""

import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import pytest

from core.db import ensure_app_database_ready, init_db, get_connection
from core.seed import seed_database
from core.migrations.runner import MigrationRunner, is_production_database
from core.maintenance import MaintenanceModeError


def test_production_database_path_recognition(monkeypatch):
    """Verify is_production_database correctly identifies production vs demo/test paths across normalization variations."""
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    assert is_production_database("data/brand_rule_lab.db") is True
    assert is_production_database() is True  # Default path when DATABASE_PATH unset

    # Canonical variations: directory traversal, relative paths, forward/backward slashes
    assert is_production_database("./data/../data/brand_rule_lab.db") is True
    assert is_production_database("data/./brand_rule_lab.db") is True
    assert is_production_database("data\\brand_rule_lab.db") is True
    assert is_production_database(os.path.abspath("data/brand_rule_lab.db")) is True

    # Case normalization (Windows filesystem case-insensitivity)
    assert is_production_database("DATA/BRAND_RULE_LAB.DB") is True
    assert is_production_database("Data/Brand_Rule_Lab.db") is True

    # URI paths (e.g. file: URI with query options)
    assert is_production_database("file:data/brand_rule_lab.db") is True
    assert is_production_database("file:data/brand_rule_lab.db?mode=ro") is True

    # Demo, disposable, and test databases must NOT be classified as production
    assert is_production_database("data/demo_brand_rule_lab.db") is False
    assert is_production_database("data/demo_queue.db") is False
    assert is_production_database("tmp/test_db.db") is False
    assert is_production_database("disposable_prod.db") is False
    assert is_production_database("scratch/temp_db.db") is False


def test_production_path_bypass_variants_cannot_seed_or_init():
    """Bypass variations (traversal, case, URI) are still blocked by seed_database and init_db."""
    bypass_paths = [
        "./data/../data/brand_rule_lab.db",
        "data/./brand_rule_lab.db",
        "DATA/BRAND_RULE_LAB.DB",
        "Data/Brand_Rule_Lab.db",
        "file:data/brand_rule_lab.db",
    ]
    for bp in bypass_paths:
        with pytest.raises(PermissionError, match="strictly prohibited"):
            seed_database(bp)
        with pytest.raises(PermissionError, match="strictly prohibited"):
            init_db(bp)


def test_startup_production_database_performs_zero_writes(monkeypatch):
    """Starting the app with the production database configured performs zero writes."""
    prod_path = Path("data/brand_rule_lab.db")
    assert prod_path.exists()

    with open(prod_path, "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()
    mtime_before = prod_path.stat().st_mtime_ns

    # Run application readiness check with production database configured
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    status = ensure_app_database_ready("data/brand_rule_lab.db")

    assert status["mode"] == "production_read_only"
    assert status["writes"] == 0
    assert status["status"] == "ready"

    with open(prod_path, "rb") as f:
        hash_after = hashlib.sha256(f.read()).hexdigest()
    mtime_after = prod_path.stat().st_mtime_ns

    assert hash_before == hash_after, "Production database was modified during startup!"
    assert mtime_before == mtime_after, "Production database file timestamp changed during startup!"


def test_startup_does_not_create_schema_migrations_in_production(tmp_path, monkeypatch):
    """Startup on an unmigrated production copy does not create schema_migrations table."""
    prod_backup = Path("data/backups/brand_rule_lab.db.backup_exact_byte_copy.bak")
    assert prod_backup.exists()

    # Create a fresh copy of the pristine backup
    test_prod_copy = tmp_path / "brand_rule_lab.db"
    shutil.copyfile(str(prod_backup), str(test_prod_copy))

    with open(test_prod_copy, "rb") as f:
        backup_hash = hashlib.sha256(f.read()).hexdigest()

    # Verify schema_migrations does NOT exist in backup
    conn = sqlite3.connect(f"file:{test_prod_copy}?mode=ro", uri=True)
    tables_before = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "schema_migrations" not in tables_before

    # Explicitly configure this as the production database
    monkeypatch.setenv("PROD_DATABASE_PATH", str(test_prod_copy))
    assert is_production_database(str(test_prod_copy)) is True

    status = ensure_app_database_ready(str(test_prod_copy))
    assert status["mode"] == "production_read_only"
    assert status["writes"] == 0

    # Verify schema_migrations was NOT created
    conn = sqlite3.connect(f"file:{test_prod_copy}?mode=ro", uri=True)
    tables_after = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "schema_migrations" not in tables_after

    with open(test_prod_copy, "rb") as f:
        post_hash = hashlib.sha256(f.read()).hexdigest()
    assert backup_hash == post_hash, "Pristine database copy was modified by startup check!"


def test_startup_refuses_to_seed_or_init_production_database(monkeypatch):
    """Direct seed_database or init_db against production raises PermissionError."""
    with pytest.raises(PermissionError, match="strictly prohibited"):
        seed_database("data/brand_rule_lab.db")

    with pytest.raises(PermissionError, match="strictly prohibited"):
        init_db("data/brand_rule_lab.db")

    # When DATABASE_PATH is unset, default path is production and must raise PermissionError
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    with pytest.raises(PermissionError, match="strictly prohibited"):
        seed_database()

    with pytest.raises(PermissionError, match="strictly prohibited"):
        init_db()


def test_demo_database_initialization_works_and_is_idempotent(tmp_path):
    """A separately configured demo database is initialized and repeated startup is idempotent."""
    demo_db = tmp_path / "demo_brand_rule_lab.db"
    assert not demo_db.exists()

    # 1. First run: initializes missing demo database
    status1 = ensure_app_database_ready(str(demo_db))
    assert status1["mode"] == "demo_initialized"
    assert status1["writes"] is True
    assert demo_db.exists()

    # Verify demo assets and migrations exist in demo database
    conn = sqlite3.connect(str(demo_db))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    assets = [r["asset_id"] for r in c.execute("SELECT asset_id FROM assets").fetchall()]
    assert "AST-MONSOON-01" in assets
    assert "AST-DIWALI-01" in assets
    assert "AST-SUNSCREEN-01" in assets

    applied_mig = [r["version"] for r in c.execute("SELECT version FROM schema_migrations").fetchall()]
    assert set(applied_mig) == {1, 2, 3, 4}
    conn.close()

    with open(demo_db, "rb") as f:
        demo_hash_1 = hashlib.sha256(f.read()).hexdigest()

    # 2. Second run: already initialized, operates idempotently without re-seeding
    status2 = ensure_app_database_ready(str(demo_db))
    assert status2["mode"] == "demo_ready"
    assert status2["writes"] == 0

    with open(demo_db, "rb") as f:
        demo_hash_2 = hashlib.sha256(f.read()).hexdigest()
    assert demo_hash_1 == demo_hash_2, "Idempotent startup should not alter demo database!"


def test_production_migration_protection_remains_enforced():
    """Production migrations cannot run without active maintenance mode and token."""
    runner = MigrationRunner(db_path="data/brand_rule_lab.db")
    with pytest.raises(MaintenanceModeError, match="strictly requires an authorized MaintenanceToken|requires active application maintenance mode"):
        runner.run()


def test_startup_missing_production_database_fails_visibly(tmp_path, monkeypatch):
    """Missing production database raises FileNotFoundError visibly rather than creating a blank database."""
    missing_prod = tmp_path / "brand_rule_lab.db"
    monkeypatch.setenv("PROD_DATABASE_PATH", str(missing_prod))

    with pytest.raises(FileNotFoundError, match="Automatic creation of production database is strictly prohibited"):
        ensure_app_database_ready(str(missing_prod))
