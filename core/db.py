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
CLOUD_DEMO_DB_PATH = "data/cloud_demo.db"
SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


def is_cloud_demo_mode() -> bool:
    """
    Return True if cloud demo mode is active.
    
    Detection Priority:
    1. Explicit DEPLOYMENT_MODE env var: 'demo', 'cloud_demo', or 'cloud' -> True; 'production' -> False.
    2. Streamlit Cloud Secrets: DEPLOYMENT_MODE = "demo".
    3. Streamlit Community Cloud Platform Signals:
       - STREAMLIT_SHARING_HOST or IS_STREAMLIT_CLOUD is present.
       - Linux container environment (/home/appuser).
       - Running inside Streamlit and no local production database exists on disk.
    """
    # 1. Check OS environment variable
    env_val = os.getenv("DEPLOYMENT_MODE", "").strip().lower()
    if env_val in ("demo", "cloud_demo", "cloud"):
        return True
    if env_val == "production":
        return False

    # 2. Check Streamlit Cloud secrets if running inside Streamlit
    try:
        from pathlib import Path
        import streamlit as st
        secrets_obj = getattr(st, "secrets", None)
        has_secrets = (
            secrets_obj is not None
            and (
                isinstance(secrets_obj, dict)
                or Path(".streamlit/secrets.toml").exists()
                or Path.home().joinpath(".streamlit/secrets.toml").exists()
                or bool(os.getenv("STREAMLIT_SECRETS"))
            )
        )
        if has_secrets:
            for sec_key in ("DEPLOYMENT_MODE", "deployment_mode", "deployment"):
                try:
                    val = secrets_obj.get(sec_key)
                    if isinstance(val, str) and val.strip().lower() in ("demo", "cloud_demo", "cloud"):
                        return True
                    elif isinstance(val, dict) and str(val.get("mode", "")).strip().lower() in ("demo", "cloud_demo", "cloud"):
                        return True
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Detect Streamlit Community Cloud Platform signals
    st_cloud_indicators = [
        os.getenv("STREAMLIT_SHARING_HOST"),
        os.getenv("IS_STREAMLIT_CLOUD"),
        os.getenv("STREAMLIT_COMMUNITY_CLOUD"),
        os.getenv("HOME") == "/home/appuser",
        os.getenv("USER") == "appuser",
        os.path.isdir("/home/appuser"),
        os.path.isdir("/mount/src"),
        "/mount/src" in str(Path(__file__).resolve().as_posix()),
        "/home/appuser" in str(Path(__file__).resolve().as_posix()),
    ]
    if any(st_cloud_indicators) and not Path("data/brand_rule_lab.db").exists():
        return True

    # 4. Running inside active Streamlit server without local production DB on disk
    try:
        import streamlit as st
        from streamlit.runtime import exists as st_runtime_exists
        if st_runtime_exists() and not Path("data/brand_rule_lab.db").exists() and not os.getenv("PROD_DATABASE_PATH"):
            return True
    except Exception:
        pass

    return False


def get_db_path(custom_path: Optional[str] = None) -> str:
    """
    Return configured database path, ensuring directory exists.
    
    Governance Rules:
    - In normal/production mode: Defaults to data/brand_rule_lab.db.
    - In explicit cloud demo mode (DEPLOYMENT_MODE="demo"): Routes to data/cloud_demo.db.
    - Strict isolation guard: Cloud demo mode is NEVER permitted to touch or resolve
      to data/brand_rule_lab.db or data/demo_brand_rule_lab.db.
    """
    if is_cloud_demo_mode():
        if custom_path:
            path_str = custom_path
        else:
            path_str = os.getenv("DATABASE_PATH") or CLOUD_DEMO_DB_PATH

        # Strict safety guard: Never allow cloud demo mode to touch production or clean baseline databases
        raw_name = Path(path_str).name.lower()
        if raw_name in ("brand_rule_lab.db", "demo_brand_rule_lab.db"):
            path_str = CLOUD_DEMO_DB_PATH
    else:
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


_ensuring_db_ready: bool = False
_verified_ready_dbs: set[str] = set()


@contextmanager
def get_connection(
    db_path: Optional[str] = None,
    *,
    maintenance_token: Optional[MaintenanceToken] = None,
    _skip_readiness_check: bool = False,
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager yielding an open SQLite connection with foreign keys enabled.
    Commits on successful block completion; rolls back on unhandled exceptions.

    Guarantees:
    - Target database is verified initialized and ready before any query is executed.
    - Normal application connections are blocked if maintenance mode is active.
    - Application connections acquire shared DatabaseGate access.
    """
    global _ensuring_db_ready
    target_path = get_db_path(db_path)
    is_mem = (target_path == ":memory:")

    # 0. Startup & Cloud Demo Pre-flight: Ensure target database is initialized before any query
    if (
        not is_mem
        and not _skip_readiness_check
        and not _ensuring_db_ready
        and target_path not in _verified_ready_dbs
        and (db_path is None or target_path == CLOUD_DEMO_DB_PATH)
    ):
        _ensuring_db_ready = True
        try:
            ensure_app_database_ready(target_path)
            _verified_ready_dbs.add(target_path)
        finally:
            _ensuring_db_ready = False

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
    with get_connection(target_path, maintenance_token=maintenance_token, _skip_readiness_check=True) as conn:
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
        with get_connection(target_path, _skip_readiness_check=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
            cursor.fetchone()

        _verified_ready_dbs.add(target_path)
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
            with get_connection(target_path, _skip_readiness_check=True) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = {r["name"] for r in cursor.fetchall()}
                if (
                    "assets" in tables
                    and "findings" in tables
                    and "approved_claims" in tables
                    and "schema_migrations" in tables
                ):
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

        _verified_ready_dbs.add(target_path)
        mode_name = "cloud_demo_initialized" if is_cloud_demo_mode() else "demo_initialized"
        return {
            "mode": mode_name,
            "db_path": target_path,
            "writes": True,
            "status": "ready",
        }

    _verified_ready_dbs.add(target_path)
    mode_name = "cloud_demo_ready" if is_cloud_demo_mode() else "demo_ready"
    return {
        "mode": mode_name,
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
