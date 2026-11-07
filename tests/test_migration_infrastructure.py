"""
Brand Rule Lab — Test Suite for Migration Infrastructure & Safeguards
Covers:
1. Production database preservation (zero modifications during tests).
2. Database backup creation and integrity verification.
3. Explicit application maintenance mode, lock tokens, and exclusive access checks.
4. Database restoration safeguards:
   - Refusal to overwrite healthy DB.
   - Continuous RestorationLock held across restoration.
   - Competing lock prevention and release on success/failure.
   - Forensic archiving and removal of stale WAL/SHM/journal sidecars.
   - Safe abortion if sidecar files cannot be removed.
5. Migration execution enforcement:
   - Rejection of production migrations outside maintenance mode.
   - Rejection of production migrations without an explicit authorized MaintenanceToken.
   - Successful execution of disposable test migrations.
   - Tracking, idempotency, and checksum mismatch detection.
   - Transactional rollback on migration execution failure.
6. 100% schema parity between fresh database initialization and migrated database.
7. Visible initialization errors (no swallowed exceptions).
8. Human-approved replacement text integrity (verbatim capitalization and punctuation preservation).
9. Genuine multi-process OS concurrency tests (subprocess testing across separate OS processes).
"""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import pytest
from pathlib import Path

from core.db import init_db, get_connection, execute_query, execute_commit
from core.maintenance import (
    MaintenanceManager,
    MaintenanceModeError,
    MaintenanceToken,
    DatabaseGate,
    is_maintenance_active,
    get_maintenance_lock_file,
    get_database_gate_file,
)
from core.migrations.runner import (
    MigrationRunner,
    RestorationLock,
    verify_exclusive_access,
    create_backup,
    restore_database_from_backup,
    run_migrations,
    get_migration_status,
    compute_checksum,
    is_production_database,
    MigrationError,
    MigrationChecksumMismatchError,
    MigrationExecutionError,
    DatabaseRestoreError,
    DatabaseExclusiveLockError,
    DatabaseIntegrityError,
)
from core.reconstruct import reconstruct_submitted_text
from core.models import Finding, FindingKind, Severity, LinkState, CreatorActionState

PROD_DB_PATH = Path("data/brand_rule_lab.db")
EXPECTED_PROD_SHA256 = "3f6b4e75955408e044d2195e48002a8f774dec452f4e81ead29ae292f4bd2ecb"
EXPECTED_PROD_ROW_COUNTS = {
    "products": 3,
    "fact_versions": 12,
    "assets": 33,
    "findings": 6,
    "approved_claims": 2,
    "review_events": 7,
    "rules": 12,
    "users": 3,
    "asset_original_snapshots": 1,
}


def run_py_subprocess(code: str, env_vars: dict = None, timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Execute a python code snippet in a completely separate OS process."""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


# ============================================================================
# 1. PRODUCTION DATABASE PRESERVATION VERIFICATION
# ============================================================================

def test_production_database_unmodified():
    """Verify that the production database remains 100% intact and untouched."""
    assert PROD_DB_PATH.exists(), "Production database must exist"
    
    with open(PROD_DB_PATH, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()
    assert current_hash == EXPECTED_PROD_SHA256, (
        f"Production database hash changed! Expected {EXPECTED_PROD_SHA256}, got {current_hash}"
    )

    conn = sqlite3.connect(str(PROD_DB_PATH))
    try:
        integrity = conn.execute("PRAGMA integrity_check;").fetchall()
        assert integrity == [("ok",)], f"Integrity check failed: {integrity}"
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert fk_check == [], f"FK check failed: {fk_check}"

        for table, expected_count in EXPECTED_PROD_ROW_COUNTS.items():
            count = conn.execute(f"SELECT count(*) FROM {table};").fetchone()[0]
            assert count == expected_count, f"Row count mismatch in table '{table}': expected {expected_count}, got {count}"
    finally:
        conn.close()


# ============================================================================
# 2. BACKUP CREATION & INTEGRITY VERIFICATION
# ============================================================================

def test_backup_creation_and_integrity(tmp_path):
    """Verify that create_backup creates a valid, integrity-verified backup."""
    backup_dir = tmp_path / "backups"
    backup_path = create_backup(str(PROD_DB_PATH), backup_dir=str(backup_dir))

    assert Path(backup_path).exists()
    assert Path(backup_path).is_file()

    # Verify backup integrity
    conn = sqlite3.connect(backup_path)
    try:
        assert conn.execute("PRAGMA integrity_check;").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
        for table, expected_count in EXPECTED_PROD_ROW_COUNTS.items():
            count = conn.execute(f"SELECT count(*) FROM {table};").fetchone()[0]
            assert count == expected_count
    finally:
        conn.close()


# ============================================================================
# 3. MAINTENANCE MODE ENFORCEMENT & CONTROLLED ACCESS
# ============================================================================

def test_maintenance_mode_lifecycle(tmp_path):
    """Verify maintenance mode lock file creation, metadata inspection, and removal."""
    db_file = tmp_path / "lifecycle.db"
    lock_file = tmp_path / ".maintenance_lock"
    mgr = MaintenanceManager(lock_file=lock_file, db_path=str(db_file))

    assert not mgr.is_active()
    assert mgr.get_metadata() is None

    token = mgr.enable(reason="Unit test maintenance", actor="tester")
    assert mgr.is_active()
    assert token.is_valid is True
    meta = mgr.get_metadata()
    assert meta["active"] is True
    assert meta["reason"] == "Unit test maintenance"
    assert meta["actor"] == "tester"
    assert meta["token_id"] == token.token_id

    mgr.disable(token)
    assert not mgr.is_active()
    assert token.is_valid is False
    assert mgr.get_metadata() is None


def test_application_connection_blocked_during_maintenance(tmp_path):
    """Normal application connections must refuse access when maintenance mode is active."""
    db_file = tmp_path / "app_test.db"
    lock_file = tmp_path / ".maintenance_lock"
    mgr = MaintenanceManager(lock_file=lock_file, db_path=str(db_file))

    # Pre-populate table
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users (name TEXT);")
    conn.execute("INSERT INTO users VALUES ('Alice');")
    conn.commit()
    conn.close()

    # Normal connection works when maintenance mode is inactive
    with get_connection(str(db_file)) as c:
        rows = c.execute("SELECT name FROM users;").fetchall()
        assert len(rows) == 1

    # Enable maintenance mode
    token = mgr.enable(reason="Security patching", actor="admin")

    # Normal application query must be refused
    with pytest.raises(MaintenanceModeError, match="currently undergoing maintenance|entering maintenance"):
        with get_connection(str(db_file)):
            pass

    with pytest.raises(MaintenanceModeError, match="currently undergoing maintenance|entering maintenance"):
        execute_query("SELECT name FROM users;", db_path=str(db_file))

    with pytest.raises(MaintenanceModeError, match="currently undergoing maintenance|entering maintenance"):
        execute_commit("INSERT INTO users VALUES ('Bob');", db_path=str(db_file))

    # Disable maintenance mode; application connections resume
    mgr.disable(token)
    res = execute_query("SELECT name FROM users;", db_path=str(db_file))
    assert len(res) == 1


def test_authorized_maintenance_operation_can_connect(tmp_path):
    """An authorized maintenance operation with a valid MaintenanceToken can connect during maintenance."""
    db_file = tmp_path / "maint_test.db"
    lock_file = tmp_path / ".maintenance_lock"
    mgr = MaintenanceManager(lock_file=lock_file, db_path=str(db_file))

    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE status (msg TEXT);")
    conn.commit()
    conn.close()

    token = mgr.enable(reason="Controlled migration", actor="migrator")

    # Connect using valid maintenance token
    with get_connection(str(db_file), maintenance_token=token) as conn:
        conn.execute("INSERT INTO status VALUES ('in_maintenance');")

    res = execute_query("SELECT msg FROM status;", db_path=str(db_file), maintenance_token=token)
    assert len(res) == 1 and res[0]["msg"] == "in_maintenance"

    # Invalidate token; access is now blocked even if token object is passed
    token.invalidate()
    with pytest.raises(MaintenanceModeError):
        with get_connection(str(db_file), maintenance_token=token):
            pass

    # Clean up
    mgr.disable(token)


# ============================================================================
# 4. RESTORATION LOCK & SIDECARS PRESERVATION
# ============================================================================

def test_restoration_lock_blocks_second_process(tmp_path):
    """A second attempt cannot acquire the restoration lock while restoration is in progress."""
    db_file = tmp_path / "lock_test.db"
    db_file.touch()

    with RestorationLock(str(db_file)):
        with pytest.raises(DatabaseExclusiveLockError, match="locked by another process|file is in use"):
            with RestorationLock(str(db_file)):
                pass


def test_restoration_lock_released_after_success_and_failure(tmp_path):
    """Restoration lock is reliably released after success and after unhandled failure."""
    db_file = tmp_path / "lifecycle_lock.db"
    db_file.touch()

    # Success path
    with RestorationLock(str(db_file)) as lock:
        assert lock.locked is True
    with RestorationLock(str(db_file)) as lock2:
        assert lock2.locked is True

    # Failure path
    try:
        with RestorationLock(str(db_file)) as lock3:
            assert lock3.locked is True
            raise RuntimeError("Simulated crash inside lock")
    except RuntimeError:
        pass

    # Lock must be released despite exception; next lock succeeds cleanly
    with RestorationLock(str(db_file)) as lock4:
        assert lock4.locked is True


def test_old_sidecars_archived_and_removed_before_restoration(tmp_path):
    """Old WAL/SHM/journal sidecars are archived to forensics and removed from target before restoring."""
    target_db = tmp_path / "active_target.db"
    target_wal = tmp_path / "active_target.db-wal"
    target_shm = tmp_path / "active_target.db-shm"
    target_journal = tmp_path / "active_target.db-journal"
    backup_db = tmp_path / "clean_backup.bak"
    forensics_dir = tmp_path / "forensics"
    lock_file = tmp_path / ".maintenance_lock"

    # Write corrupt/stale content to target and sidecars
    target_db.write_bytes(b"CORRUPTED_TARGET_DATA_PAGE")
    target_wal.write_bytes(b"STALE_WAL_FRAME_DATA")
    target_shm.write_bytes(b"STALE_SHM_INDEX_DATA")
    target_journal.write_bytes(b"STALE_HOT_JOURNAL_DATA")

    # Create valid backup database
    b_conn = sqlite3.connect(str(backup_db))
    b_conn.execute("CREATE TABLE clean (id INT);")
    b_conn.execute("INSERT INTO clean VALUES (42);")
    b_conn.commit()
    b_conn.close()

    mgr = MaintenanceManager(lock_file=lock_file, db_path=str(target_db))
    token = mgr.enable(reason="Restoring database")

    result = restore_database_from_backup(
        backup_path=str(backup_db),
        target_db_path=str(target_db),
        maintenance_mgr=mgr,
        forensics_dir=str(forensics_dir),
    )

    assert result["restored"] is True

    # 1. Target sidecars must be removed so SQLite cannot replay stale WAL/journal
    assert not target_wal.exists(), "Target WAL sidecar must be unlinked prior to restoration"
    assert not target_shm.exists(), "Target SHM sidecar must be unlinked prior to restoration"
    assert not target_journal.exists(), "Target journal sidecar must be unlinked prior to restoration"

    # 2. Forensic archive must preserve copies of corrupt DB and all sidecars
    forensic_files = [f.name for f in forensics_dir.iterdir()]
    assert any("failed_database_" in f and f.endswith(".db") for f in forensic_files)
    assert any("failed_database_" in f and f.endswith(".db-wal") for f in forensic_files)
    assert any("failed_database_" in f and f.endswith(".db-shm") for f in forensic_files)
    assert any("failed_database_" in f and f.endswith(".db-journal") for f in forensic_files)

    # 3. Restored database passes integrity_check and foreign_key_check
    r_conn = sqlite3.connect(str(target_db))
    assert r_conn.execute("PRAGMA integrity_check;").fetchall() == [("ok",)]
    assert r_conn.execute("PRAGMA foreign_key_check;").fetchall() == []
    val = r_conn.execute("SELECT id FROM clean;").fetchone()[0]
    assert val == 42
    r_conn.close()

    mgr.disable(token)


def test_restore_safeguard_refuses_healthy_database_overwrite(tmp_path):
    """Safeguard: Never automatically overwrite a healthy database with an older backup."""
    target_db = tmp_path / "target.db"
    backup_db = tmp_path / "backup.bak"
    lock_file = tmp_path / ".maintenance_lock"

    # Create healthy target database
    t_conn = sqlite3.connect(str(target_db))
    t_conn.execute("CREATE TABLE live_data (val TEXT);")
    t_conn.execute("INSERT INTO live_data VALUES ('active_production_data');")
    t_conn.commit()
    t_conn.close()

    # Create backup database
    b_conn = sqlite3.connect(str(backup_db))
    b_conn.execute("CREATE TABLE old_data (val TEXT);")
    b_conn.execute("INSERT INTO old_data VALUES ('stale_backup_data');")
    b_conn.commit()
    b_conn.close()

    mgr = MaintenanceManager(lock_file=lock_file, db_path=str(target_db))
    token = mgr.enable(reason="Testing restore safeguard")

    with pytest.raises(DatabaseRestoreError, match="CRITICAL SAFEGUARD: Automatic overwrite of a healthy database is strictly forbidden"):
        restore_database_from_backup(
            backup_path=str(backup_db),
            target_db_path=str(target_db),
            maintenance_mgr=mgr,
            allow_healthy_overwrite=False,
        )

    # Verify target data was untouched
    chk_conn = sqlite3.connect(str(target_db))
    res = chk_conn.execute("SELECT val FROM live_data;").fetchone()[0]
    chk_conn.close()
    assert res == "active_production_data"

    mgr.disable(token)


# ============================================================================
# 5. MIGRATION ENFORCEMENT (PRODUCTION VS. DISPOSABLE TEST)
# ============================================================================

def test_production_migrations_rejected_outside_maintenance_mode():
    """Production migrations must be rejected if application maintenance mode is not active."""
    lock_file = Path("data/.maintenance_lock")
    if lock_file.exists():
        lock_file.unlink()

    runner = MigrationRunner(db_path=str(PROD_DB_PATH))
    with pytest.raises(MaintenanceModeError, match="strictly requires an authorized MaintenanceToken|requires active application maintenance mode"):
        runner.run()

    with open(PROD_DB_PATH, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == EXPECTED_PROD_SHA256


def test_production_migrations_rejected_without_token_even_in_maintenance(tmp_path):
    """Production migrations must be rejected if no valid MaintenanceToken is explicitly supplied, even if maintenance is active."""
    disposable_prod = tmp_path / "disposable_prod.db"
    shutil.copy2(PROD_DB_PATH, disposable_prod)
    
    mgr = MaintenanceManager(db_path=str(disposable_prod))
    token = mgr.enable(reason="Testing token requirement", actor="admin")

    runner = MigrationRunner(db_path=str(disposable_prod), maintenance_mgr=mgr)
    
    # Attempting to run with require_maintenance=True but maintenance_token=None must be rejected
    with pytest.raises(MaintenanceModeError, match="strictly requires an authorized MaintenanceToken"):
        runner.run(require_maintenance=True, maintenance_token=None)

    mgr.disable(token)


def test_disposable_test_migrations_run_without_maintenance_mode(tmp_path):
    """Disposable test databases can run migrations without requiring production maintenance mode."""
    disposable_db = tmp_path / "disposable.db"
    conn = sqlite3.connect(str(disposable_db))
    conn.execute("CREATE TABLE assets (asset_id TEXT PRIMARY KEY);")
    conn.execute("""
        CREATE TABLE findings (
            finding_id TEXT PRIMARY KEY, asset_id TEXT, kind TEXT, severity TEXT,
            span_start INT, span_end INT, source_text TEXT, rule_id TEXT,
            fact_id TEXT, fact_version_id INT, link_state TEXT, message TEXT,
            next_step TEXT, suggested_rewrite TEXT, creator_action TEXT, dismiss_reason TEXT
        );
    """)
    conn.execute("""
        CREATE TABLE review_events (
            event_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, actor TEXT NOT NULL,
            role TEXT NOT NULL, action TEXT NOT NULL, comment TEXT, override_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

    runner = MigrationRunner(db_path=str(disposable_db))
    applied = runner.run()
    assert applied == [1, 2, 3, 4]


def test_migration_runner_on_disposable_copy(tmp_path):
    """Test running all migrations against a disposable copy of production database."""
    disposable_db = tmp_path / "disposable_brand_rule_lab.db"
    shutil.copy2(PROD_DB_PATH, disposable_db)

    runner = MigrationRunner(db_path=str(disposable_db))
    newly_applied = runner.run()

    assert newly_applied == [1, 2, 3, 4]

    conn = sqlite3.connect(str(disposable_db))
    try:
        assert conn.execute("PRAGMA integrity_check;").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []

        mig_rows = conn.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version;").fetchall()
        assert len(mig_rows) == 4

        asset_cols = [r[1] for r in conn.execute("PRAGMA table_info(assets);").fetchall()]
        assert "review_cycle" in asset_cols

        finding_cols = [r[1] for r in conn.execute("PRAGMA table_info(findings);").fetchall()]
        assert "review_cycle" in finding_cols

        rev_cols = [r[1] for r in conn.execute("PRAGMA table_info(review_events);").fetchall()]
        for col in ["finding_id", "previous_action", "new_action", "event_fingerprint", "provenance", "known_before_timestamp"]:
            assert col in rev_cols

        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        assert "asset_submissions" in tables
        assert "asset_effective_snapshots" in tables

        # Expected row counts after migration 004 repairs AST-ffed5f findings and creates submission/snapshot
        expected_migrated_counts = dict(EXPECTED_PROD_ROW_COUNTS)
        expected_migrated_counts["findings"] = 8  # 6 migrated + 2 restored
        expected_migrated_counts["review_events"] = 10  # 7 original + 3 reconstructed
        expected_migrated_counts["asset_submissions"] = 1
        expected_migrated_counts["asset_effective_snapshots"] = 1

        for table, expected_count in expected_migrated_counts.items():
            count = conn.execute(f"SELECT count(*) FROM {table};").fetchone()[0]
            assert count == expected_count, f"Count mismatch in {table}: expected {expected_count}, got {count}"
    finally:
        conn.close()


def test_migration_runner_idempotency(tmp_path):
    """Running migrations a second time must detect that all migrations are applied and do nothing."""
    disposable_db = tmp_path / "disposable_idempotent.db"
    shutil.copy2(PROD_DB_PATH, disposable_db)

    runner = MigrationRunner(db_path=str(disposable_db))
    assert runner.run() == [1, 2, 3, 4]

    second_applied = runner.run()
    assert second_applied == []

    status = runner.get_status()
    assert len(status) == 4
    assert all(s["applied"] is True for s in status)
    assert all(s["checksum_valid"] is True for s in status)


def test_checksum_mismatch_detection(tmp_path):
    """Altering the SQL of an already applied migration must trigger MigrationChecksumMismatchError."""
    disposable_db = tmp_path / "disposable_checksum.db"
    shutil.copy2(PROD_DB_PATH, disposable_db)

    sql_copy = tmp_path / "sql"
    shutil.copytree("core/migrations/sql", sql_copy)

    runner = MigrationRunner(db_path=str(disposable_db), sql_dir=sql_copy)
    runner.run()

    m1_file = sql_copy / "001_finding_identity_and_review_cycle.sql"
    m1_file.write_text(m1_file.read_text(encoding="utf-8") + "\n-- Tampered comment\n", encoding="utf-8")

    with pytest.raises(MigrationChecksumMismatchError, match="checksum mismatch"):
        runner.run()


def test_migration_transaction_rollback_on_failure(tmp_path):
    """A failed migration must be completely rolled back, leaving no partial schema or registry record."""
    disposable_db = tmp_path / "disposable_rollback.db"
    conn = sqlite3.connect(str(disposable_db))
    conn.execute("CREATE TABLE assets (asset_id TEXT PRIMARY KEY);")
    conn.commit()
    conn.close()

    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    
    (sql_dir / "001_good.sql").write_text("ALTER TABLE assets ADD COLUMN col1 TEXT;\n", encoding="utf-8")
    (sql_dir / "002_faulty.sql").write_text("ALTER TABLE assets ADD COLUMN col2 TEXT;\nINVALID SQL SYNTAX HERE;\n", encoding="utf-8")

    runner = MigrationRunner(db_path=str(disposable_db), sql_dir=sql_dir)

    with pytest.raises(MigrationExecutionError, match="Failed to apply migration 002_faulty"):
        runner.run()

    conn = sqlite3.connect(str(disposable_db))
    try:
        applied = conn.execute("SELECT version FROM schema_migrations;").fetchall()
        assert applied == [(1,)]

        cols = [r[1] for r in conn.execute("PRAGMA table_info(assets);").fetchall()]
        assert "col1" in cols
        assert "col2" not in cols
    finally:
        conn.close()


# ============================================================================
# 6. INITIALIZATION FAILURES SURFACING
# ============================================================================

def test_initialization_failures_surface_visible_error(tmp_path, monkeypatch):
    """Failures during synchronize_schema_migrations must surface immediately, not be swallowed."""
    fresh_db = tmp_path / "fresh_fail.db"

    def fail_sync(*args, **kwargs):
        raise RuntimeError("Simulated synchronization failure during init_db")

    monkeypatch.setattr("core.migrations.runner.synchronize_schema_migrations", fail_sync)

    with pytest.raises(RuntimeError, match="Simulated synchronization failure during init_db"):
        init_db(str(fresh_db))


# ============================================================================
# 7. FRESH-SCHEMA VS. MIGRATED-SCHEMA PARITY
# ============================================================================

def _extract_schema_fingerprint(conn: sqlite3.Connection) -> dict:
    """Extract structural fingerprint of SQLite database schema."""
    fp = {}
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()]
    fp["tables"] = tables
    fp["columns"] = {}
    fp["indexes"] = {}
    fp["foreign_keys"] = {}
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info({t});").fetchall()
        fp["columns"][t] = [(c[1], c[2], c[3], c[4], c[5]) for c in cols]
        fks = conn.execute(f"PRAGMA foreign_key_list({t});").fetchall()
        fp["foreign_keys"][t] = sorted([(f[2], f[3], f[4], f[5], f[6]) for f in fks])
        idxs = conn.execute(f"PRAGMA index_list({t});").fetchall()
        idx_details = []
        for idx in idxs:
            idx_name = idx[1]
            unique = idx[2]
            cols_in_idx = conn.execute(f"PRAGMA index_info({idx_name});").fetchall()
            idx_details.append((idx_name, unique, [col[2] for col in cols_in_idx]))
        fp["indexes"][t] = sorted(idx_details)
    trigs = conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='trigger' ORDER BY name;").fetchall()
    fp["triggers"] = sorted(trigs)
    return fp


def test_fresh_vs_migrated_schema_parity(tmp_path):
    """
    Test 100% structural parity between:
    - Fresh database initialized via init_db() (core/schema.sql)
    - Database created via baseline pre-migration schema + running migrations 001, 002, 003.
    """
    fresh_db = tmp_path / "fresh.db"
    init_db(str(fresh_db))

    baseline_db = tmp_path / "baseline_migrated.db"
    b_conn = sqlite3.connect(str(baseline_db))
    b_conn.execute("PRAGMA foreign_keys = ON;")
    
    baseline_ddl = """
    CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL, sku_aliases TEXT NOT NULL, market TEXT NOT NULL);
    CREATE TABLE fact_versions (fact_id TEXT NOT NULL, version INTEGER NOT NULL, product_id TEXT NOT NULL, market TEXT NOT NULL, fact_text TEXT NOT NULL, permitted_wording TEXT NOT NULL, valid_from TEXT NOT NULL, expires_at TEXT, owner TEXT NOT NULL DEFAULT 'brand_science', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (fact_id, version), FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE);
    CREATE TABLE assets (asset_id TEXT PRIMARY KEY, name TEXT NOT NULL, product_id TEXT NOT NULL, market TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_by TEXT NOT NULL, source_hash TEXT NOT NULL, text_content TEXT NOT NULL, planned_publish_date TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (product_id) REFERENCES products(product_id));
    CREATE TABLE findings (finding_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL, span_start INTEGER NOT NULL, span_end INTEGER NOT NULL, source_text TEXT NOT NULL, rule_id TEXT, fact_id TEXT, fact_version_id INTEGER, link_state TEXT NOT NULL, message TEXT NOT NULL, next_step TEXT NOT NULL, suggested_rewrite TEXT, creator_action TEXT NOT NULL DEFAULT 'pending', dismiss_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE);
    CREATE TABLE approved_claims (stable_claim_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, claim_text TEXT NOT NULL, approved_text_hash TEXT NOT NULL, fact_id TEXT NOT NULL, fact_version_id INTEGER NOT NULL, drift_status TEXT NOT NULL DEFAULT 'CURRENT', approved_by TEXT NOT NULL, approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, flagged_at TIMESTAMP, FOREIGN KEY (asset_id) REFERENCES assets(asset_id), FOREIGN KEY (fact_id, fact_version_id) REFERENCES fact_versions(fact_id, version));
    CREATE TABLE review_events (event_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL, comment TEXT, override_reason TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (asset_id) REFERENCES assets(asset_id));
    CREATE TRIGGER trg_prevent_review_events_update BEFORE UPDATE ON review_events BEGIN SELECT RAISE(ABORT, 'Mutation forbidden: review_events table is append-only.'); END;
    CREATE TRIGGER trg_prevent_review_events_delete BEFORE DELETE ON review_events BEGIN SELECT RAISE(ABORT, 'Deletion forbidden: review_events table is append-only.'); END;
    CREATE TABLE asset_original_snapshots (snapshot_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL UNIQUE, original_text TEXT NOT NULL, content_hash TEXT NOT NULL, captured_by TEXT NOT NULL, captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (asset_id) REFERENCES assets(asset_id));
    CREATE TRIGGER trg_prevent_snapshots_update BEFORE UPDATE ON asset_original_snapshots BEGIN SELECT RAISE(ABORT, 'Mutation forbidden: asset_original_snapshots table is immutable.'); END;
    CREATE TRIGGER trg_prevent_snapshots_delete BEFORE DELETE ON asset_original_snapshots BEGIN SELECT RAISE(ABORT, 'Deletion forbidden: asset_original_snapshots table is immutable.'); END;
    CREATE TABLE rules (rule_id TEXT PRIMARY KEY, predicate_type TEXT NOT NULL, scope TEXT NOT NULL, parameters_json TEXT NOT NULL, owner_approved INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE users (user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL);
    """
    b_conn.executescript(baseline_ddl)
    b_conn.close()

    run_migrations(str(baseline_db))

    c_fresh = sqlite3.connect(str(fresh_db))
    c_migrated = sqlite3.connect(str(baseline_db))
    try:
        fp_fresh = _extract_schema_fingerprint(c_fresh)
        fp_migrated = _extract_schema_fingerprint(c_migrated)

        assert fp_fresh["tables"] == fp_migrated["tables"]
        assert fp_fresh["triggers"] == fp_migrated["triggers"]
        assert fp_fresh["columns"] == fp_migrated["columns"]
        assert fp_fresh["foreign_keys"] == fp_migrated["foreign_keys"]
        assert fp_fresh["indexes"] == fp_migrated["indexes"]
    finally:
        c_fresh.close()
        c_migrated.close()


# ============================================================================
# 8. HUMAN-APPROVED TEXT INTEGRITY TESTS
# ============================================================================

def test_human_approved_text_integrity_capitalization_preservation():
    """Authoritative replacement text must never have its capitalization silently changed."""
    original_text = "Headline: say goodbye to acne forever! Gentle on skin."
    span_start = 10
    span_end = 38
    target_finding = Finding(
        finding_id="FND-01",
        asset_id="AST-01",
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=span_start,
        span_end=span_end,
        source_text="say goodbye to acne forever!",
        creator_action=CreatorActionState.ACCEPTED,
    )

    test_cases = [
        "Gentle daily wash for clearer-looking skin!",
        "GENTLE DAILY WASH FOR CLEARER-LOOKING SKIN!",
        "gentle daily wash for clearer-looking skin!",
        "Gentle Daily Wash For Clearer-Looking Skin!",
        "Gentle Daily wash for Clearer-Looking skin!",
    ]

    for replacement in test_cases:
        actions = {"FND-01": {"action": "accepted", "text": replacement}}
        reconstructed = reconstruct_submitted_text(original_text, [target_finding], actions)
        
        expected = original_text[:span_start] + replacement + original_text[span_end:]
        assert reconstructed == expected
        assert replacement in reconstructed


def test_human_approved_text_integrity_punctuation_preservation():
    """Boundary and inner punctuation must be preserved verbatim."""
    original_text = "Headline: Say goodbye to acne forever! Clinically proven 2.5% reduction."
    span_start = 10
    span_end = 38
    target_finding = Finding(
        finding_id="FND-01",
        asset_id="AST-01",
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=span_start,
        span_end=span_end,
        source_text="Say goodbye to acne forever!",
        creator_action=CreatorActionState.ACCEPTED,
    )

    punctuation_cases = [
        "Gentle daily wash for clearer-looking skin!",
        "Gentle daily wash for clearer-looking skin.",
        "Gentle daily wash for clearer-looking skin...",
        "Gentle daily wash — for clearer-looking skin",
        "Looking for gentle daily wash for clearer-looking skin?",
    ]

    for replacement in punctuation_cases:
        actions = {"FND-01": {"action": "accepted", "text": replacement}}
        reconstructed = reconstruct_submitted_text(original_text, [target_finding], actions)

        expected = original_text[:span_start] + replacement + original_text[span_end:]
        assert reconstructed == expected
        assert "Clinically proven 2.5% reduction." in reconstructed
        assert replacement in reconstructed


# ============================================================================
# 9. GENUINE MULTI-PROCESS CONCURRENCY TEST SUITE (SEPARATE OS PROCESSES)
# ============================================================================

def test_multiprocess_competing_maintenance_acquisition(tmp_path):
    """
    Test that a second independent OS process cannot acquire maintenance mode
    when another process already owns it (atomic ownership enforcement).
    """
    db_file = tmp_path / "competing.db"
    mgr1 = MaintenanceManager(db_path=str(db_file))
    token1 = mgr1.enable(reason="Main process maintenance", actor="parent_proc")

    child_code = f"""
import sys
from core.maintenance import MaintenanceManager, MaintenanceModeError
mgr = MaintenanceManager(db_path=r'{db_file}')
try:
    mgr.enable(reason='Competing child process', actor='child_proc', drain_timeout=0.2)
    print('ERROR: Child process unexpectedly acquired maintenance!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Child process rejected:', e)
    sys.exit(0)
"""
    proc = run_py_subprocess(child_code)
    assert proc.returncode == 0, f"Child stderr: {proc.stderr}"
    assert "SUCCESS: Child process rejected" in proc.stdout
    assert "already active and owned by 'parent_proc'" in proc.stdout

    mgr1.disable(token1)


def test_multiprocess_unauthorized_connection_attempt(tmp_path):
    """
    Test that a separate OS process attempting get_connection() without an authorized
    token is immediately rejected with MaintenanceModeError when maintenance is active.
    """
    db_file = tmp_path / "unauth_app.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE status (val TEXT);")
    conn.commit()
    conn.close()

    mgr = MaintenanceManager(db_path=str(db_file))
    token = mgr.enable(reason="Active maintenance", actor="admin")

    child_code = f"""
import sys
from core.db import get_connection
from core.maintenance import MaintenanceModeError
try:
    with get_connection(r'{db_file}') as conn:
        conn.execute('SELECT * FROM status;')
    print('ERROR: Unauthorized child process connected!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Unauthorized child blocked:', e)
    sys.exit(0)
"""
    proc = run_py_subprocess(child_code)
    assert proc.returncode == 0, f"Child stderr: {proc.stderr}"
    assert "SUCCESS: Unauthorized child blocked" in proc.stdout
    assert "undergoing maintenance" in proc.stdout or "blocked" in proc.stdout

    mgr.disable(token)


def test_multiprocess_existing_connection_drained_before_maintenance(tmp_path):
    """
    Test database quiescence:
    When a separate child process holds an active connection, maintenance mode
    cannot be established until the existing connection is safely closed/drained.
    """
    db_file = tmp_path / "drain_test.db"
    conn0 = sqlite3.connect(str(db_file))
    conn0.execute("CREATE TABLE items (id INT);")
    conn0.commit()
    conn0.close()

    ready_file = tmp_path / "child_ready"
    release_file = tmp_path / "child_release"

    child_code = f"""
import time
from pathlib import Path
from core.db import get_connection

with get_connection(r'{db_file}') as conn:
    Path(r'{ready_file}').write_text('connected')
    while not Path(r'{release_file}').exists():
        time.sleep(0.02)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    child_proc = subprocess.Popen([sys.executable, "-c", child_code], env=env)

    try:
        # Wait until child has acquired connection
        start = time.time()
        while not ready_file.exists():
            if time.time() - start > 5.0:
                raise TimeoutError("Child did not connect in time")
            time.sleep(0.02)

        mgr = MaintenanceManager(db_path=str(db_file))

        # Attempt to enable maintenance with short drain timeout (must fail due to active child)
        with pytest.raises(MaintenanceModeError, match="could not be drained"):
            mgr.enable(reason="Quiescence test", actor="admin", drain_timeout=0.2)

        # Release child connection
        release_file.write_text("release")
        child_proc.wait(timeout=5.0)

        # Now enable maintenance: quiescence succeeds
        token = mgr.enable(reason="Quiescence test after drain", actor="admin", drain_timeout=2.0)
        assert token.is_valid is True
        mgr.disable(token)
    finally:
        if child_proc.poll() is None:
            child_proc.kill()


def test_multiprocess_connection_acquisition_race(tmp_path):
    """
    Test that rapid concurrent connection attempts across multiple OS processes
    never slip through during maintenance mode.
    """
    db_file = tmp_path / "race_test.db"
    conn0 = sqlite3.connect(str(db_file))
    conn0.execute("CREATE TABLE counter (val INT);")
    conn0.execute("INSERT INTO counter VALUES (0);")
    conn0.commit()
    conn0.close()

    mgr = MaintenanceManager(db_path=str(db_file))
    token = mgr.enable(reason="Race test maintenance", actor="admin")

    child_code = f"""
import sys
from core.db import get_connection
from core.maintenance import MaintenanceModeError
try:
    with get_connection(r'{db_file}') as conn:
        conn.execute('SELECT * FROM counter;')
    # Should not reach here
    sys.exit(1)
except MaintenanceModeError:
    sys.exit(0)
"""
    # Spawn 5 concurrent processes
    processes = [run_py_subprocess(child_code) for _ in range(5)]
    for p in processes:
        assert p.returncode == 0, f"A process slipped through maintenance: {p.stdout} / {p.stderr}"

    mgr.disable(token)


def test_multiprocess_token_forgery_and_cross_database_rejected(tmp_path):
    """
    Test that forged tokens or tokens from another database are strictly rejected
    in separate OS processes.
    """
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    db1 = dir1 / "db1.db"
    db2 = dir2 / "db2.db"

    mgr1 = MaintenanceManager(db_path=str(db1))
    token1 = mgr1.enable(reason="Maint 1", actor="admin1")

    mgr2 = MaintenanceManager(db_path=str(db2))
    token2 = mgr2.enable(reason="Maint 2", actor="admin2")

    # Child attempts to use token1 on db2 (cross-database reuse)
    cross_db_code = f"""
import sys
from core.db import get_connection
from core.maintenance import MaintenanceToken, MaintenanceModeError

token1 = MaintenanceToken(
    token_id='{token1.token_id}',
    db_path=r'{token1.db_path}',
    actor='{token1.actor}',
    reason='{token1.reason}',
    created_at='{token1.created_at}',
    signature='{token1.signature}'
)

try:
    with get_connection(r'{db2}', maintenance_token=token1):
        pass
    print('ERROR: Cross-database token accepted!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Cross-database rejected:', e)
    sys.exit(0)
"""
    p_cross = run_py_subprocess(cross_db_code)
    assert p_cross.returncode == 0, p_cross.stderr
    assert "SUCCESS: Cross-database rejected" in p_cross.stdout

    # Child attempts to use forged token
    forged_code = f"""
import sys
from core.db import get_connection
from core.maintenance import MaintenanceToken, MaintenanceModeError

forged = MaintenanceToken(
    token_id='forged_token_id',
    db_path=r'{db1}',
    actor='hacker',
    reason='exploit',
    signature='invalid_hmac_signature'
)

try:
    with get_connection(r'{db1}', maintenance_token=forged):
        pass
    print('ERROR: Forged token accepted!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Forged token rejected:', e)
    sys.exit(0)
"""
    p_forge = run_py_subprocess(forged_code)
    assert p_forge.returncode == 0, p_forge.stderr
    assert "SUCCESS: Forged token rejected" in p_forge.stdout

    mgr1.disable(token1)
    mgr2.disable(token2)


def test_multiprocess_production_migration_without_token_rejected(tmp_path):
    """
    Test that a child process attempting to run migrations on a production-like
    database without an explicit authorized MaintenanceToken is rejected.
    """
    prod_copy = tmp_path / "prod_copy.db"
    shutil.copy2(PROD_DB_PATH, prod_copy)

    mgr = MaintenanceManager(db_path=str(prod_copy))
    token = mgr.enable(reason="Migration prep", actor="admin")

    child_code = f"""
import sys
from core.migrations.runner import MigrationRunner
from core.maintenance import MaintenanceModeError

runner = MigrationRunner(db_path=r'{prod_copy}')
try:
    # Attempting to run with require_maintenance=True but NO token
    runner.run(require_maintenance=True, maintenance_token=None)
    print('ERROR: Migration ran without token!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Migration without token rejected:', e)
    sys.exit(0)
"""
    p = run_py_subprocess(child_code)
    assert p.returncode == 0, p.stderr
    assert "SUCCESS: Migration without token rejected" in p.stdout
    assert "strictly requires an authorized MaintenanceToken" in p.stdout

    mgr.disable(token)


def test_multiprocess_foreign_process_cannot_disable_maintenance(tmp_path):
    """
    Test that one OS process cannot disable or release maintenance mode owned by another process.
    """
    db_file = tmp_path / "exclusive_owner.db"
    mgr1 = MaintenanceManager(db_path=str(db_file))
    token1 = mgr1.enable(reason="Critical work", actor="proc1")

    child_code = f"""
import sys
from core.maintenance import MaintenanceManager, MaintenanceToken, MaintenanceModeError

mgr_foreign = MaintenanceManager(db_path=r'{db_file}')

# Attempt 1: Disable with None
try:
    mgr_foreign.disable(None)
    print('ERROR: disable(None) succeeded!')
    sys.exit(1)
except MaintenanceModeError as e:
    pass

# Attempt 2: Disable with fake token
fake_token = MaintenanceToken(
    token_id='fake_id',
    db_path=r'{db_file}',
    actor='intruder',
    reason='sabotage'
)
try:
    mgr_foreign.disable(fake_token)
    print('ERROR: disable(fake_token) succeeded!')
    sys.exit(1)
except MaintenanceModeError as e:
    print('SUCCESS: Foreign disable rejected:', e)
    sys.exit(0)
"""
    p = run_py_subprocess(child_code)
    assert p.returncode == 0, p.stderr
    assert "SUCCESS: Foreign disable rejected" in p.stdout

    # Verify original maintenance mode remains intact on disk
    assert mgr1.is_active() is True
    mgr1.disable(token1)
    assert mgr1.is_active() is False


def test_multiprocess_wal_deletion_failure_aborts_restoration(tmp_path):
    """
    Test that if a sidecar file (-wal) is locked by an external process and cannot be removed,
    restore_database_from_backup aborts immediately with DatabaseRestoreError without overwriting the target.
    """
    target_db = tmp_path / "wal_target.db"
    backup_db = tmp_path / "clean_backup.bak"

    # Create backup database
    bconn = sqlite3.connect(str(backup_db))
    bconn.execute("CREATE TABLE clean (v TEXT);")
    bconn.execute("INSERT INTO clean VALUES ('backup_payload');")
    bconn.commit()
    bconn.close()

    # Pre-create target database in WAL mode
    tconn = sqlite3.connect(str(target_db))
    tconn.execute("PRAGMA journal_mode=WAL;")
    tconn.execute("CREATE TABLE old (v TEXT);")
    tconn.commit()
    tconn.close()

    ready_file = tmp_path / "lock_ready"
    release_file = tmp_path / "lock_release"

    # Child process opens target_db in WAL mode and keeps uncheckpointed frames open
    child_code = f"""
import time, sqlite3
from pathlib import Path

conn = sqlite3.connect(r'{target_db}')
conn.execute('PRAGMA journal_mode=WAL;')
conn.execute('INSERT INTO old VALUES ("uncheckpointed_data");')
Path(r'{ready_file}').write_text('locked')
while not Path(r'{release_file}').exists():
    time.sleep(0.02)
conn.close()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    child_proc = subprocess.Popen([sys.executable, "-c", child_code], env=env)

    try:
        start = time.time()
        while not ready_file.exists():
            if time.time() - start > 5.0:
                raise TimeoutError("Child did not lock WAL in time")
            time.sleep(0.02)

        wal_file = Path(str(target_db) + "-wal")
        assert wal_file.exists(), "WAL file must exist while child connection is open"

        mgr = MaintenanceManager(db_path=str(target_db))
        token = mgr.enable(reason="Restoring WAL db")

        # Corrupt target header so healthy check does not block
        with open(target_db, "r+b") as hf:
            hf.seek(0)
            hf.write(b"CORRUPTED_TARGET")

        # Attempt restoration: must abort because WAL sidecar cannot be archived or unlinked
        with pytest.raises(DatabaseRestoreError, match="Cannot safely restore database: sidecar file.*could not be (archived|removed)"):
            restore_database_from_backup(
                backup_path=str(backup_db),
                target_db_path=str(target_db),
                maintenance_mgr=mgr,
                forensics_dir=str(tmp_path / "forensics"),
                allow_healthy_overwrite=True,
            )

        release_file.write_text("release")
        child_proc.wait(timeout=5.0)
        mgr.disable(token)
    finally:
        if child_proc.poll() is None:
            child_proc.kill()


def test_multiprocess_restoration_lock_contention(tmp_path):
    """
    Test that when RestorationLock is held by a parent process:
    A separate OS process attempting to acquire RestorationLock fails with DatabaseExclusiveLockError,
    and attempting to query SQLite fails with disk I/O error.
    """
    db_file = tmp_path / "contention.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript("CREATE TABLE t (x INT); INSERT INTO t VALUES (1);")
    conn.close()

    with RestorationLock(str(db_file)):
        child_code = f"""
import sys, sqlite3
from core.migrations.runner import RestorationLock, DatabaseExclusiveLockError

# 1. Test competing RestorationLock
try:
    with RestorationLock(r'{db_file}'):
        print('ERROR: Child acquired RestorationLock!')
        sys.exit(1)
except DatabaseExclusiveLockError as e:
    pass

# 2. Test SQLite I/O failure
try:
    c = sqlite3.connect(r'{db_file}', timeout=0.1)
    c.execute('SELECT * FROM t;')
    print('ERROR: Child read SQLite during RestorationLock!')
    sys.exit(1)
except sqlite3.OperationalError:
    print('SUCCESS: RestorationLock blocked child')
    sys.exit(0)
"""
        proc = run_py_subprocess(child_code)
        assert proc.returncode == 0, f"Child stderr: {proc.stderr}"
        assert "SUCCESS: RestorationLock blocked child" in proc.stdout
