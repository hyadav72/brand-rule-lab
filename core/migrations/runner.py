"""
Brand Rule Lab — Database Migration & Safe Maintenance Engine
Owned by Agent A1 (Backend & Data Engineer).

Provides:
- Schema migration execution with transaction safety and pre/postflight integrity checks.
- Script checksum computation and mismatch detection.
- Explicit application maintenance / shutdown locks.
- Exclusive database access verification and continuous restoration locking.
- Safe backup creation and integrity verification.
- Protected forensic restore procedures (never overwrites a healthy DB, archives & unlinks WAL/SHM sidecars).
"""

from __future__ import annotations
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.maintenance import (
    DEFAULT_MAINTENANCE_LOCK,
    MaintenanceModeError,
    MaintenanceToken,
    MaintenanceManager,
    get_maintenance_lock_file,
    is_maintenance_active,
)

DEFAULT_SQL_DIR = Path(__file__).resolve().parent / "sql"
DEFAULT_BACKUP_DIR = Path("data/backups")
DEFAULT_FORENSICS_DIR = Path("data/forensics")


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class MigrationError(Exception):
    """Base class for all migration and database management errors."""
    pass


class MigrationChecksumMismatchError(MigrationError):
    """Raised when an already applied migration has a modified SQL script."""
    pass


class MigrationExecutionError(MigrationError):
    """Raised when an error occurs during migration execution."""
    pass


class DatabaseRestoreError(MigrationError):
    """Raised when a database restore violation or safeguard is triggered."""
    pass


class DatabaseExclusiveLockError(MigrationError):
    """Raised when exclusive database file access cannot be verified or held."""
    pass


class DatabaseIntegrityError(MigrationError):
    """Raised when SQLite integrity check or foreign key check fails."""
    pass


# ============================================================================
# MIGRATION DATACLASS & CHECKSUM
# ============================================================================

@dataclass
class Migration:
    """Represents a discovered migration script."""
    version: int
    name: str
    filepath: Path
    checksum: str
    content: str


def compute_checksum(content: str) -> str:
    """
    Compute deterministic SHA-256 checksum of SQL content.
    Normalizes line endings (\\r\\n -> \\n) and strips trailing line whitespace
    to ensure identical checksums across different OS checkouts.
    """
    normalized_lines = [line.rstrip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized_text = "\n".join(normalized_lines).strip()
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


# ============================================================================
# RESTORATION LOCK & EXCLUSIVE ACCESS
# ============================================================================

class RestorationLock:
    """
    Holds a mandatory OS-level exclusive file lock across the entire physical database
    restoration procedure. Prevents competing processes from accessing, locking, reading,
    or modifying the target database file during replacement.
    Guarantees reliable lock release on exit (including on exceptions).
    """
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self.file_handle: Optional[Any] = None
        self.locked = False

    def __enter__(self) -> RestorationLock:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        if not db_file.exists():
            db_file.touch()

        try:
            self.file_handle = open(db_file, "r+b")
        except (IOError, OSError, PermissionError) as e:
            raise DatabaseExclusiveLockError(
                f"Cannot acquire exclusive restoration lock on '{self.db_path}': file is in use: {e}"
            )

        try:
            if platform.system() == "Windows":
                import msvcrt
                # Lock byte 0 non-blocking
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.locked = True
        except (IOError, OSError, PermissionError) as e:
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
            raise DatabaseExclusiveLockError(
                f"Cannot acquire exclusive restoration lock on '{self.db_path}': locked by another process: {e}"
            )
        return self

    def archive_current_to(self, forensic_dest_path: str) -> None:
        """
        Stream current file content directly through the locked file descriptor to forensics.
        Does not open a secondary file handle, avoiding OS sharing conflicts.
        """
        if self.file_handle is None or not self.locked:
            raise DatabaseExclusiveLockError("Restoration lock not held.")
        self.file_handle.seek(0)
        with open(forensic_dest_path, "wb") as f_out:
            shutil.copyfileobj(self.file_handle, f_out)

    def write_backup_bytes(self, backup_path: str) -> None:
        """
        Stream backup file bytes directly through the locked file descriptor,
        truncating and flushing without releasing the lock.
        """
        if self.file_handle is None or not self.locked:
            raise DatabaseExclusiveLockError("Restoration lock not held.")

        b_file = Path(backup_path)
        if not b_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        self.file_handle.seek(0)
        with open(b_file, "rb") as src:
            shutil.copyfileobj(src, self.file_handle)
        self.file_handle.truncate()
        self.file_handle.flush()
        try:
            os.fsync(self.file_handle.fileno())
        except OSError:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.file_handle is not None:
            try:
                if self.locked:
                    if platform.system() == "Windows":
                        import msvcrt
                        self.file_handle.seek(0)
                        msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                self.file_handle.close()
                self.file_handle = None
                self.locked = False


def verify_exclusive_access(
    db_path: str,
    maintenance_mgr: Optional[MaintenanceManager] = None,
) -> bool:
    """
    Verify exclusive database access before high-risk operations.
    Enforces active maintenance mode and tests acquisition of the RestorationLock.
    """
    mgr = maintenance_mgr or MaintenanceManager(get_maintenance_lock_file(db_path), db_path=db_path)
    if not mgr.is_active():
        raise MaintenanceModeError(
            "Cannot acquire exclusive access: Application maintenance mode is NOT active. "
            "You must activate maintenance mode to reject new connections before exclusive operations."
        )

    db_file = Path(db_path)
    if not db_file.exists():
        return True

    try:
        with RestorationLock(db_path):
            pass
    except Exception as e:
        raise DatabaseExclusiveLockError(f"Database file '{db_path}' is in use or locked: {e}") from e

    return True


def is_production_database(db_path: Optional[str] = None) -> bool:
    """Return True if db_path resolves to the main protected production database."""
    if not db_path:
        from core.db import get_db_path
        db_path = get_db_path()

    raw_path = str(db_path).strip()
    if raw_path.startswith("file:"):
        raw_path = raw_path[5:]
        if "?" in raw_path:
            raw_path = raw_path.split("?", 1)[0]
        # Handle file:///C:/path or file:/C:/path on Windows
        if len(raw_path) > 2 and raw_path.startswith("/") and raw_path[2] == ":":
            raw_path = raw_path.lstrip("/")

    try:
        norm_target = os.path.normcase(os.path.realpath(os.path.abspath(raw_path)))
        prod_path = "data/brand_rule_lab.db"
        norm_prod = os.path.normcase(os.path.realpath(os.path.abspath(prod_path)))

        # 1. Exact match with primary repository production database
        if norm_target == norm_prod:
            return True

        # 2. Never treat explicit demo, disposable, temporary, or test databases as production
        name_lower = Path(norm_target).name.lower()
        if any(marker in name_lower for marker in ("demo", "disposable", "test", "tmp", "temp", "cloud")):
            return False

        # 3. Explicit production path environment variable
        explicit_prod = os.getenv("PROD_DATABASE_PATH")
        if explicit_prod:
            norm_explicit = os.path.normcase(os.path.realpath(os.path.abspath(explicit_prod)))
            if norm_target == norm_explicit:
                return True

        # 4. If target file is named brand_rule_lab.db (and not located in test/tmp directory)
        parts_lower = [p.lower() for p in Path(norm_target).parts]
        if name_lower == "brand_rule_lab.db":
            if not any(marker in parts_lower for marker in ("tmp", "temp", "pytest", "tests", ".pytest_cache")):
                return True

        return False
    except Exception:
        name = Path(raw_path).name.lower()
        return name == "brand_rule_lab.db" and "demo" not in name and "test" not in name


# ============================================================================
# BACKUP & RESTORE UTILITIES
# ============================================================================

def create_backup(db_path: str, backup_dir: Optional[str] = None) -> str:
    """
    Create a verified, timestamped backup of the specified database using SQLite backup API.
    Verifies integrity before and after backup.
    
    Returns:
        Path string of the created backup file.
    """
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # Pre-backup integrity check
    conn_src = sqlite3.connect(str(source))
    try:
        integrity = conn_src.execute("PRAGMA integrity_check;").fetchall()
        if integrity != [("ok",)]:
            raise DatabaseIntegrityError(f"Source database '{db_path}' failed integrity check: {integrity}")
        fk_check = conn_src.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_check:
            raise DatabaseIntegrityError(f"Source database '{db_path}' has foreign key violations: {fk_check}")
    finally:
        conn_src.close()

    dest_dir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = dest_dir / f"{source.stem}.backup_{timestamp}.bak"

    # Perform atomic SQLite online backup
    src_conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(backup_file))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    # Post-backup integrity check on destination
    chk_conn = sqlite3.connect(str(backup_file))
    try:
        b_integrity = chk_conn.execute("PRAGMA integrity_check;").fetchall()
        if b_integrity != [("ok",)]:
            raise DatabaseIntegrityError(f"Backup file '{backup_file}' failed integrity check: {b_integrity}")
    finally:
        chk_conn.close()

    return str(backup_file)


def restore_database_from_backup(
    backup_path: str,
    target_db_path: str,
    maintenance_mgr: Optional[MaintenanceManager] = None,
    forensics_dir: Optional[str] = None,
    allow_healthy_overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Safely restore a database from backup subject to strict forensic safeguards:
    
    1. Verifies explicit maintenance mode before proceeding.
    2. NEVER automatically overwrites a healthy target database. If target exists and
       passes integrity checks, raises DatabaseRestoreError.
    3. Acquires RestorationLock held throughout forensic archiving, sidecar cleanup,
       and physical byte replacement.
    4. Preserves failed/corrupted target database AND sidecars in forensics archive.
    5. Safely unlinks stale sidecars (-wal, -shm, -journal) from target directory.
       STRICT REQUIREMENT: If any sidecar fails to unlink (e.g. held open by another process),
       aborts restoration immediately with DatabaseRestoreError to prevent stale WAL replay.
    6. Verifies backup integrity before and after copy.
    """
    backup_file = Path(backup_path)
    target_file = Path(target_db_path)

    # Safeguard 1: Verify Maintenance Mode
    mgr = maintenance_mgr or MaintenanceManager(get_maintenance_lock_file(str(target_file)), db_path=str(target_file))
    if not mgr.is_active():
        raise MaintenanceModeError(
            "Cannot restore database: Application maintenance mode is NOT active. "
            "You must activate maintenance mode to reject application connections before restoration."
        )

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Verify backup integrity before touching target
    b_conn = sqlite3.connect(str(backup_file))
    try:
        b_res = b_conn.execute("PRAGMA integrity_check;").fetchall()
        if b_res != [("ok",)]:
            raise DatabaseIntegrityError(f"Backup file '{backup_path}' failed integrity check: {b_res}")
    finally:
        b_conn.close()

    f_dir = Path(forensics_dir or DEFAULT_FORENSICS_DIR)
    f_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    forensic_path = None

    # Safeguard 2: Check target database health (reject overwrite if healthy)
    if target_file.exists() and target_file.stat().st_size > 0:
        is_healthy = False
        try:
            # Check SQLite header magic bytes before connecting
            with open(target_file, "rb") as hf:
                magic = hf.read(16)
            if magic.startswith(b"SQLite format 3\x00"):
                conn = sqlite3.connect(str(target_file))
                try:
                    res = conn.execute("PRAGMA integrity_check;").fetchall()
                    fk = conn.execute("PRAGMA foreign_key_check;").fetchall()
                    if res == [("ok",)] and not fk:
                        is_healthy = True
                finally:
                    conn.close()
        except Exception:
            is_healthy = False

        if is_healthy and not allow_healthy_overwrite:
            raise DatabaseRestoreError(
                "CRITICAL SAFEGUARD: Automatic overwrite of a healthy database is strictly forbidden. "
                "The target database passed integrity checks. Manual intervention is required to replace "
                "a healthy database with an older backup."
            )

    # Pre-archive sidecars before connection/locking can delete or mutate them
    for ext in ["-wal", "-shm", "-journal"]:
        sidecar = Path(f"{target_file}{ext}")
        if sidecar.exists():
            try:
                sidecar_dest = f_dir / f"failed_database_{timestamp}_corrupted.db{ext}"
                shutil.copy2(sidecar, sidecar_dest)
            except OSError as e:
                raise DatabaseRestoreError(
                    f"CRITICAL SAFEGUARD: Cannot safely restore database: sidecar file '{sidecar.name}' "
                    f"could not be archived (it may be locked by another active process: {e}). "
                    "Restoration aborted to prevent database corruption."
                )

    # Safeguards 3 & 4: Continuous RestorationLock across archive, cleanup, and rewrite
    with RestorationLock(str(target_file)) as lock:
        # Step A: Archive corrupted file directly through locked file handle
        if target_file.exists() and target_file.stat().st_size > 0:
            forensic_target = f_dir / f"failed_database_{timestamp}_corrupted.db"
            lock.archive_current_to(str(forensic_target))
            forensic_path = str(forensic_target)

        # Step B: Safely unlink stale sidecars (-wal, -shm, -journal) from target directory
        for ext in ["-wal", "-shm", "-journal"]:
            sidecar = Path(f"{target_file}{ext}")
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except OSError as e:
                    raise DatabaseRestoreError(
                        f"CRITICAL SAFEGUARD: Cannot safely restore database: sidecar file '{sidecar.name}' "
                        f"could not be removed (it may be locked by another active process: {e}). "
                        "Restoration aborted to prevent database corruption."
                    )

        # Step C: Write backup bytes through locked file handle
        lock.write_backup_bytes(str(backup_file))

    # Verify restored target integrity
    r_conn = sqlite3.connect(str(target_file))
    try:
        r_res = r_conn.execute("PRAGMA integrity_check;").fetchall()
        if r_res != [("ok",)]:
            raise DatabaseIntegrityError(f"Restored database failed integrity check: {r_res}")
        r_fk = r_conn.execute("PRAGMA foreign_key_check;").fetchall()
        if r_fk:
            raise DatabaseIntegrityError(f"Restored database has foreign key violations: {r_fk}")
    finally:
        r_conn.close()

    return {
        "restored": True,
        "target_path": str(target_file),
        "backup_path": str(backup_file),
        "forensic_archive": forensic_path,
    }


# ============================================================================
# MIGRATION RUNNER
# ============================================================================

class MigrationRunner:
    """
    Executes versioned SQL migrations against a SQLite database.
    Enforces:
    - Mandatory, cryptographically verified MaintenanceToken for production database migrations
    - Continuous validation of maintenance authorization throughout migration lifecycle
    - schema_migrations tracking table
    - Checksum validation on all previously applied migrations
    - Transactional execution and full rollback on failure
    - Preflight and postflight SQLite integrity and foreign key checks
    """
    def __init__(
        self,
        db_path: Optional[str] = None,
        sql_dir: Optional[Path] = None,
        maintenance_mgr: Optional[MaintenanceManager] = None,
    ):
        self.db_path = db_path or os.getenv("DATABASE_PATH", "data/brand_rule_lab.db")
        self.sql_dir = sql_dir or DEFAULT_SQL_DIR
        self.maintenance_mgr = maintenance_mgr or MaintenanceManager(
            get_maintenance_lock_file(self.db_path), db_path=self.db_path
        )

    def _get_connection(self, maintenance_token: Optional[MaintenanceToken] = None) -> sqlite3.Connection:
        """Create a connection with foreign keys enabled and isolation_level=None."""
        if is_production_database(self.db_path) or self.maintenance_mgr.is_active():
            if not self.maintenance_mgr.validate_token(maintenance_token):
                raise MaintenanceModeError("Invalid or unauthorized MaintenanceToken for migration connection.")
        target = Path(self.db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target))
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.isolation_level = None  # Autocommit mode for explicit transaction control
        return conn

    def ensure_migrations_table(self, conn: sqlite3.Connection) -> None:
        """Create schema_migrations table if it does not already exist."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def discover_migrations(self) -> List[Migration]:
        """
        Scan sql_dir for migration files matching ^(\\d+)_(.+)\\.sql$.
        Returns list of Migration objects sorted by version ascending.
        """
        if not self.sql_dir.exists():
            return []

        migrations: List[Migration] = []
        pattern = re.compile(r"^(\d+)_([a-zA-Z0-9_\-]+)\.sql$")
        seen_versions = set()

        for f in self.sql_dir.iterdir():
            if not f.is_file() or not f.name.endswith(".sql"):
                continue
            match = pattern.match(f.name)
            if not match:
                continue
            version = int(match.group(1))
            name = match.group(2)
            if version in seen_versions:
                raise MigrationError(f"Duplicate migration version detected: {version} in {f.name}")
            seen_versions.add(version)

            content = f.read_text(encoding="utf-8")
            checksum = compute_checksum(content)
            migrations.append(Migration(version=version, name=name, filepath=f, checksum=checksum, content=content))

        migrations.sort(key=lambda m: m.version)
        return migrations

    def get_applied_migrations(self, conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
        """Return dict of applied migrations keyed by version."""
        self.ensure_migrations_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version;")
        rows = cursor.fetchall()
        return {
            row[0]: {
                "name": row[1],
                "checksum": row[2],
                "applied_at": row[3],
            }
            for row in rows
        }

    def preflight_check(self, conn: sqlite3.Connection) -> None:
        """Run SQLite integrity check before executing migrations."""
        res = conn.execute("PRAGMA integrity_check;").fetchall()
        if res != [("ok",)]:
            raise DatabaseIntegrityError(f"Preflight integrity check failed on '{self.db_path}': {res}")

    def postflight_check(self, conn: sqlite3.Connection) -> None:
        """Run SQLite integrity and foreign key checks after executing migrations."""
        res = conn.execute("PRAGMA integrity_check;").fetchall()
        if res != [("ok",)]:
            raise DatabaseIntegrityError(f"Postflight integrity check failed on '{self.db_path}': {res}")
        fk = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk:
            raise DatabaseIntegrityError(f"Postflight foreign key check failed on '{self.db_path}': {fk}")

    def apply_migration(self, conn: sqlite3.Connection, migration: Migration) -> None:
        """
        Execute a single migration inside an explicit transaction.
        Rolls back completely if an error occurs.
        """
        escaped_name = migration.name.replace("'", "''")
        wrapped_sql = (
            "BEGIN TRANSACTION;\n"
            f"{migration.content}\n"
            "INSERT INTO schema_migrations (version, name, checksum) "
            f"VALUES ({migration.version}, '{escaped_name}', '{migration.checksum}');\n"
            "COMMIT;\n"
        )
        try:
            conn.executescript(wrapped_sql)
        except Exception as e:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise MigrationExecutionError(
                f"Failed to apply migration {migration.version:03d}_{migration.name}: {e}"
            ) from e

    def run(
        self,
        require_maintenance: Optional[bool] = None,
        maintenance_token: Optional[MaintenanceToken] = None,
    ) -> List[int]:
        """
        Execute all pending migrations in version order.
        Strictly requires a valid, verified MaintenanceToken for production database migrations.
        Maintains authorization verification across the entire execution lifecycle.
        
        Returns:
            List of newly applied migration versions.
        """
        should_require = (
            require_maintenance
            if require_maintenance is not None
            else is_production_database(self.db_path)
        )
        if should_require:
            if maintenance_token is None:
                raise MaintenanceModeError(
                    f"Production database migration on '{self.db_path}' strictly requires an authorized MaintenanceToken. "
                    "Maintenance mode alone is not sufficient; an authorized token must be explicitly provided."
                )
            if not self.maintenance_mgr.validate_token(maintenance_token):
                raise MaintenanceModeError("Invalid, expired, forged, or cross-database MaintenanceToken provided for production migration.")

        conn = self._get_connection(maintenance_token=maintenance_token)
        try:
            self.preflight_check(conn)
            self.ensure_migrations_table(conn)
            applied = self.get_applied_migrations(conn)
            discovered = self.discover_migrations()

            # Verify maintenance authorization is preserved after discovery
            if should_require and not self.maintenance_mgr.validate_token(maintenance_token):
                raise MaintenanceModeError("Maintenance authorization was revoked or modified during migration discovery.")

            # 1. Verify checksums of already applied migrations
            for m in discovered:
                if m.version in applied:
                    recorded_chk = applied[m.version]["checksum"]
                    if m.checksum != recorded_chk:
                        raise MigrationChecksumMismatchError(
                            f"Migration {m.version:03d}_{m.name} checksum mismatch! "
                            f"Recorded in schema_migrations: '{recorded_chk}', but current file checksum is '{m.checksum}'. "
                            "Altering previously applied migration scripts is strictly prohibited."
                        )

            # 2. Apply pending migrations in order
            newly_applied: List[int] = []
            for m in discovered:
                if m.version not in applied:
                    # Re-verify maintenance authorization before each migration transaction
                    if should_require and not self.maintenance_mgr.validate_token(maintenance_token):
                        raise MaintenanceModeError(f"Maintenance authorization was lost before applying migration {m.version:03d}.")
                    self.apply_migration(conn, m)
                    newly_applied.append(m.version)

            if should_require and not self.maintenance_mgr.validate_token(maintenance_token):
                raise MaintenanceModeError("Maintenance authorization was lost during postflight verification.")

            self.postflight_check(conn)
            return newly_applied
        finally:
            conn.close()

    def get_status(self) -> List[Dict[str, Any]]:
        """Return status summary of all discovered migrations."""
        target = Path(self.db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target))
        try:
            self.ensure_migrations_table(conn)
            applied = self.get_applied_migrations(conn)
            discovered = self.discover_migrations()

            status_list = []
            for m in discovered:
                is_applied = m.version in applied
                rec = applied.get(m.version)
                checksum_valid = (rec["checksum"] == m.checksum) if is_applied else True
                status_list.append({
                    "version": m.version,
                    "name": m.name,
                    "applied": is_applied,
                    "applied_at": rec["applied_at"] if rec else None,
                    "checksum": m.checksum,
                    "checksum_valid": checksum_valid,
                })
            return status_list
        finally:
            conn.close()


def run_migrations(
    db_path: Optional[str] = None,
    sql_dir: Optional[Path] = None,
    require_maintenance: Optional[bool] = None,
    maintenance_token: Optional[MaintenanceToken] = None,
) -> List[int]:
    """Convenience helper to run pending migrations."""
    runner = MigrationRunner(db_path=db_path, sql_dir=sql_dir)
    return runner.run(require_maintenance=require_maintenance, maintenance_token=maintenance_token)


def get_migration_status(db_path: Optional[str] = None, sql_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Convenience helper to query migration status."""
    runner = MigrationRunner(db_path=db_path, sql_dir=sql_dir)
    return runner.get_status()


def synchronize_schema_migrations(conn: sqlite3.Connection, sql_dir: Optional[Path] = None) -> None:
    """
    Synchronize schema_migrations table for a freshly initialized database from schema.sql.
    Inserts all existing migration scripts as applied with their current checksums.
    """
    s_dir = sql_dir or DEFAULT_SQL_DIR
    runner = MigrationRunner(sql_dir=s_dir)
    runner.ensure_migrations_table(conn)
    discovered = runner.discover_migrations()
    for m in discovered:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum)
            VALUES (?, ?, ?);
            """,
            (m.version, m.name, m.checksum),
        )
