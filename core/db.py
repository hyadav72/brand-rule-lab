"""
Brand Rule Lab — Database Access Layer
Owned by Agent A1 (Backend & Data Engineer).

Manages SQLite connections, schema initialization, and transactional queries.
Enforces foreign keys, maintenance mode access control, and read/write integrity.
"""

from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, List, Optional, Tuple
from dotenv import load_dotenv

from core.maintenance import (
    is_maintenance_active,
    MaintenanceModeError,
    MaintenanceToken,
    MaintenanceManager,
    DatabaseGate,
    get_maintenance_lock_file,
    get_database_gate_file,
)

load_dotenv()

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "data/brand_rule_lab.db")
SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Return configured database path, ensuring directory exists."""
    path_str = custom_path or os.getenv("DATABASE_PATH", "data/brand_rule_lab.db")
    if path_str != ":memory:":
        raw_path = path_str
        if raw_path.startswith("file:"):
            raw_path = raw_path[5:]
            if "?" in raw_path:
                raw_path = raw_path.split("?", 1)[0]
            if len(raw_path) > 2 and raw_path.startswith("/") and raw_path[2] == ":":
                raw_path = raw_path.lstrip("/")
        db_file = Path(raw_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
    return path_str


@contextmanager
def get_connection(
    db_path: Optional[str] = None,
    *,
    maintenance_token: Optional[MaintenanceToken] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager yielding an open SQLite connection with foreign keys enabled.
    Commits on successful block completion; rolls back on unhandled exceptions.

    Maintenance Mode & Quiescence Governance:
    - Normal application connections are blocked if maintenance mode is active.
    - Application connections acquire shared DatabaseGate access, preventing maintenance
      from interrupting active operations without a proper quiescence drain.
    - Double-checks maintenance mode under gate lock to eliminate TOCTOU races.
    - Explicit maintenance operations providing a cryptographically verified,
      database-bound MaintenanceToken bypass the gate and connect directly.
    """
    target_path = get_db_path(db_path)
    is_mem = (target_path == ":memory:")

    # 1. Maintenance Mode Check
    if not is_mem and is_maintenance_active(target_path):
        mgr = MaintenanceManager(get_maintenance_lock_file(target_path), db_path=target_path)
        if not mgr.validate_token(maintenance_token):
            raise MaintenanceModeError(
                f"Database '{target_path}' is currently undergoing maintenance. "
                "Application requests are locked."
            )
        # Authorized maintenance caller: connect directly without gate acquisition
        conn = sqlite3.connect(target_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    # 2. Normal application connection: acquire shared gate access
    gate = DatabaseGate(get_database_gate_file(target_path) if not is_mem else None)
    try:
        gate.acquire_shared(timeout=1.0)
    except (TimeoutError, OSError):
        raise MaintenanceModeError(
            f"Database '{target_path}' is entering maintenance. Connection request blocked."
        )

    try:
        # Re-check maintenance under shared gate lock to eliminate TOCTOU race
        if not is_mem and is_maintenance_active(target_path):
            raise MaintenanceModeError(
                f"Database '{target_path}' is currently undergoing maintenance. "
                "Application requests are locked."
            )

        conn = sqlite3.connect(target_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    finally:
        gate.release_shared()


def init_db(
    db_path: Optional[str] = None,
    schema_path: Optional[Path] = None,
    *,
    maintenance_token: Optional[MaintenanceToken] = None,
) -> None:
    """
    Initialize database schema from schema.sql idempotently.
    Registers baseline migrations in schema_migrations. Failures during synchronization
    are raised directly rather than swallowed.
    """
    target_path = get_db_path(db_path)
    from core.migrations.runner import is_production_database
    if is_production_database(target_path):
        raise PermissionError(
            f"Executing automated schema initialization against protected production database '{target_path}' is strictly prohibited. "
            "Production schema must remain untouched."
        )

    sql_file = schema_path or SCHEMA_SQL_PATH
    if not sql_file.exists():
        raise FileNotFoundError(f"Schema file not found at: {sql_file}")

    schema_sql = sql_file.read_text(encoding="utf-8")
    with get_connection(target_path, maintenance_token=maintenance_token) as conn:
        conn.executescript(schema_sql)
        # Register baseline migrations in schema_migrations for newly initialized fresh databases
        from core.migrations.runner import synchronize_schema_migrations
        synchronize_schema_migrations(conn)


def ensure_app_database_ready(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Ensure the database configured for the application is ready and accessible.

    Permanent Protection Safeguards:
    1. If db_path resolves to the protected production database:
       - Strictly enforces READ-ONLY access during application startup.
       - NEVER runs seed_database(), init_db(), or migrations.
       - Performs zero writes.
       - Validates read connectivity.
    2. If db_path resolves to a separately configured demo/development database:
       - If database is uninitialized (missing or empty), explicitly initializes it using
         supported seed_database(include_demo_assets=True) and applies migrations.
       - If database is already initialized, operates idempotently without re-seeding.
    3. Failures are raised directly so startup halts visibly rather than continuing partially.
    """
    target_path = get_db_path(db_path)
    from core.migrations.runner import is_production_database

    if is_production_database(target_path):
        target_file = Path(target_path)
        if not target_file.exists():
            raise FileNotFoundError(
                f"Protected production database file not found at: {target_path}. "
                "Automatic creation of production database is strictly prohibited."
            )
        # Verify read-only connectivity without performing writes
        with get_connection(target_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
            cursor.fetchone()

        return {
            "mode": "production_read_only",
            "db_path": target_path,
            "writes": 0,
            "status": "ready",
        }

    # Separately configured demo or development database
    target_file = Path(target_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    needs_init = True
    if target_file.exists():
        try:
            with get_connection(target_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = {r["name"] for r in cursor.fetchall()}
                if "assets" in tables and "findings" in tables:
                    needs_init = False
        except Exception:
            needs_init = True

    if needs_init:
        # Explicitly initialize demo database with supported demo fixtures and migrations
        from core.seed import seed_database
        from core.snapshots import migrate_add_snapshots_table
        from core.migrations.runner import MigrationRunner

        seed_database(target_path, include_demo_assets=True)
        migrate_add_snapshots_table(target_path)
        runner = MigrationRunner(db_path=target_path)
        runner.run(require_maintenance=False)

        return {
            "mode": "demo_initialized",
            "db_path": target_path,
            "writes": True,
            "status": "ready",
        }

    return {
        "mode": "demo_ready",
        "db_path": target_path,
        "writes": 0,
        "status": "ready",
    }


def execute_query(
    query: str,
    params: Tuple[Any, ...] = (),
    db_path: Optional[str] = None,
    *,
    maintenance_token: Optional[MaintenanceToken] = None,
) -> List[sqlite3.Row]:
    """Execute read-only query and return list of rows."""
    with get_connection(db_path, maintenance_token=maintenance_token) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_commit(
    query: str,
    params: Tuple[Any, ...] = (),
    db_path: Optional[str] = None,
    *,
    maintenance_token: Optional[MaintenanceToken] = None,
) -> int:
    """Execute mutating statement and return affected row count."""
    with get_connection(db_path, maintenance_token=maintenance_token) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.rowcount
