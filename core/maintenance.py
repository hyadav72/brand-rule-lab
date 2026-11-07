"""
Brand Rule Lab — Application Maintenance & Lock Governance
Owned by Agent A1 (Backend & Data Engineer).

Provides:
- Explicit application maintenance mode lifecycle management with atomic ownership.
- Cryptographically signed and target-bound MaintenanceTokens for controlled operations.
- Process-safe reader-writer DatabaseGate for database quiescence and eliminating TOCTOU races.
- Non-bypassable maintenance checks and token validation for database connection layers.
- Cross-platform lock and gate file resolution for production and isolated test databases.
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import platform
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_MAINTENANCE_LOCK = Path("data/.maintenance_lock")
DEFAULT_GATE_FILE = Path("data/.maintenance_gate")


class MaintenanceModeError(Exception):
    """Raised when an operation is blocked due to active maintenance mode."""
    pass


class MaintenanceToken:
    """
    Controlled authorization token issued exclusively by MaintenanceManager.enable().
    Bound to a specific target database path, signed with a cryptographic HMAC,
    and required by core.db to permit database access during maintenance mode.
    """
    def __init__(
        self,
        token_id: str,
        db_path: str,
        actor: str,
        reason: str,
        created_at: Optional[str] = None,
        signature: Optional[str] = None,
    ):
        self.token_id = token_id
        self.db_path = str(Path(db_path).resolve()) if db_path and db_path != ":memory:" else str(db_path)
        self.actor = actor
        self.reason = reason
        self.created_at = created_at or datetime.utcnow().isoformat()
        self.signature = signature or ""
        self._valid = True

    def invalidate(self) -> None:
        """Invalidate this token, revoking maintenance database access."""
        self._valid = False

    @property
    def is_valid(self) -> bool:
        """Check if this token is currently valid."""
        return self._valid

    def __repr__(self) -> str:
        return f"<MaintenanceToken id={self.token_id[:8]}... db='{self.db_path}' actor='{self.actor}' valid={self._valid}>"


class DatabaseGate:
    """
    Process-safe reader-writer coordination gate for database connections and maintenance.
    - Application connections acquire shared access (multiple concurrent operations allowed).
    - Maintenance mode acquires exclusive access (quiescence / draining of active operations).
    - Operates across OS processes using native OS byte-range and advisory locks.
    """
    def __init__(self, gate_path: Optional[Path] = None):
        self.gate_path = Path(gate_path) if gate_path else None
        self._is_memory = (self.gate_path is None or str(self.gate_path) == ":memory:")
        self._handle = None
        self._fd = None
        self._mode = None

    def acquire_shared(self, timeout: float = 2.0) -> None:
        """Acquire shared access for an application connection."""
        if self._is_memory:
            return
        self.gate_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()

        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h = kernel32.CreateFileW(
                str(self.gate_path),
                0xC0000000, # GENERIC_READ | GENERIC_WRITE
                7,          # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                None,
                4,          # OPEN_ALWAYS
                0x80,       # FILE_ATTRIBUTE_NORMAL
                None,
            )
            if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
                raise OSError(f"Cannot open gate file '{self.gate_path}': error {kernel32.GetLastError()}")

            ov = ctypes.c_buffer(32)
            while True:
                # dwFlags = 1 (LOCKFILE_FAIL_IMMEDIATELY), shared lock
                res = kernel32.LockFileEx(h, 1, 0, 1, 0, ov)
                if res:
                    self._handle = h
                    self._mode = "shared"
                    return
                if time.time() - start >= timeout:
                    kernel32.CloseHandle(h)
                    raise TimeoutError(f"Timed out acquiring shared gate lock on '{self.gate_path}'")
                time.sleep(0.01)
        else:
            import fcntl
            fd = os.open(str(self.gate_path), os.O_RDWR | os.O_CREAT, 0o666)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    self._fd = fd
                    self._mode = "shared"
                    return
                except (IOError, OSError):
                    if time.time() - start >= timeout:
                        os.close(fd)
                        raise TimeoutError(f"Timed out acquiring shared gate lock on '{self.gate_path}'")
                    time.sleep(0.01)

    def release_shared(self) -> None:
        """Release shared gate access."""
        if self._is_memory or self._mode != "shared":
            return
        if platform.system() == "Windows":
            import ctypes
            if self._handle:
                ov = ctypes.c_buffer(32)
                ctypes.windll.kernel32.UnlockFileEx(self._handle, 0, 1, 0, ov)
                ctypes.windll.kernel32.CloseHandle(self._handle)
                self._handle = None
        else:
            import fcntl
            if self._fd is not None:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._fd)
                    self._fd = None
        self._mode = None

    def acquire_exclusive(self, timeout: float = 5.0) -> None:
        """Acquire exclusive gate access for maintenance quiescence (draining in-flight connections)."""
        if self._is_memory:
            return
        self.gate_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()

        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h = kernel32.CreateFileW(
                str(self.gate_path),
                0xC0000000,
                7,
                None,
                4,
                0x80,
                None,
            )
            if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
                raise OSError(f"Cannot open gate file '{self.gate_path}': error {kernel32.GetLastError()}")

            ov = ctypes.c_buffer(32)
            while True:
                # dwFlags = 1 (FAIL_IMMEDIATELY) | 2 (EXCLUSIVE_LOCK) = 3
                res = kernel32.LockFileEx(h, 3, 0, 1, 0, ov)
                if res:
                    self._handle = h
                    self._mode = "exclusive"
                    return
                if time.time() - start >= timeout:
                    kernel32.CloseHandle(h)
                    raise TimeoutError(f"Timed out draining database connections on '{self.gate_path}'")
                time.sleep(0.01)
        else:
            import fcntl
            fd = os.open(str(self.gate_path), os.O_RDWR | os.O_CREAT, 0o666)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    self._mode = "exclusive"
                    return
                except (IOError, OSError):
                    if time.time() - start >= timeout:
                        os.close(fd)
                        raise TimeoutError(f"Timed out draining database connections on '{self.gate_path}'")
                    time.sleep(0.01)

    def release_exclusive(self) -> None:
        """Release exclusive gate access."""
        if self._is_memory or self._mode != "exclusive":
            return
        if platform.system() == "Windows":
            import ctypes
            if self._handle:
                ov = ctypes.c_buffer(32)
                ctypes.windll.kernel32.UnlockFileEx(self._handle, 0, 1, 0, ov)
                ctypes.windll.kernel32.CloseHandle(self._handle)
                self._handle = None
        else:
            import fcntl
            if self._fd is not None:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._fd)
                    self._fd = None
        self._mode = None


class MaintenanceManager:
    """
    Manages explicit application maintenance mode with atomic ownership and quiescence.
    - Atomically creates an exclusive lock file to prevent competing maintenance coordinators.
    - Drains active connections via DatabaseGate before authorizing maintenance operations.
    - Mints cryptographically signed, database-bound MaintenanceTokens.
    - Requires matching token ownership to release maintenance mode.
    """
    def __init__(self, lock_file: Optional[Path] = None, db_path: Optional[str] = None):
        self.db_path = db_path
        self.lock_file = lock_file or get_maintenance_lock_file(db_path)
        self.gate = DatabaseGate(get_database_gate_file(db_path))
        self._active_token: Optional[MaintenanceToken] = None
        self._gate_held = False

    def enable(
        self,
        reason: str = "Database maintenance in progress",
        actor: str = "system",
        drain_timeout: float = 5.0,
    ) -> MaintenanceToken:
        """
        Activate maintenance mode with atomic ownership and connection quiescence.
        1. Atomically creates lock file via O_CREAT | O_EXCL. Rejects competing maintenance requests.
        2. Drains in-flight application connections via exclusive DatabaseGate acquisition.
        3. Returns an HMAC-signed, database-bound MaintenanceToken.
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Atomic lock file creation (reject competing coordinator)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self.lock_file), flags, 0o644)
        except FileExistsError:
            meta = self.get_metadata()
            owner = meta.get("actor", "unknown") if meta else "unknown"
            raise MaintenanceModeError(
                f"Maintenance mode is already active and owned by '{owner}'. "
                "Concurrent maintenance ownership is strictly prohibited."
            )

        # 2. Database Quiescence: Drain existing connections
        try:
            self.gate.acquire_exclusive(timeout=drain_timeout)
            self._gate_held = True
        except TimeoutError as e:
            # Drain failed: close fd and unlink lock file to avoid leaving stuck state
            os.close(fd)
            try:
                self.lock_file.unlink()
            except OSError:
                pass
            raise MaintenanceModeError(
                f"Failed to establish maintenance mode: active database connections could not be drained within {drain_timeout}s."
            ) from e

        # 3. Mint signed token and write structured metadata
        token_id = uuid.uuid4().hex
        created_at = datetime.utcnow().isoformat()
        salt = uuid.uuid4().hex
        normalized_db = str(Path(self.db_path).resolve()) if self.db_path and self.db_path != ":memory:" else str(self.db_path or "")
        
        signature = hmac.new(
            salt.encode("utf-8"),
            f"{token_id}:{normalized_db}:{created_at}:{actor}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        payload = {
            "active": True,
            "token_id": token_id,
            "db_path": normalized_db,
            "actor": actor,
            "reason": reason,
            "created_at": created_at,
            "salt": salt,
            "signature": signature,
        }

        try:
            payload_bytes = json.dumps(payload, indent=2).encode("utf-8")
            os.write(fd, payload_bytes)
        finally:
            os.close(fd)

        self._active_token = MaintenanceToken(
            token_id=token_id,
            db_path=normalized_db,
            actor=actor,
            reason=reason,
            created_at=created_at,
            signature=signature,
        )
        return self._active_token

    def disable(self, token: Optional[MaintenanceToken] = None) -> None:
        """
        Deactivate maintenance mode and release quiescence gate.
        STRICT REQUIREMENT: The caller must provide the exact owning MaintenanceToken.
        One process cannot release another process's maintenance lock.
        """
        if not self.lock_file.exists():
            if self._gate_held:
                self.gate.release_exclusive()
                self._gate_held = False
            return

        if token is None or not isinstance(token, MaintenanceToken):
            raise MaintenanceModeError(
                "Cannot release maintenance mode: a valid, matching MaintenanceToken must be explicitly provided."
            )

        meta = self.get_metadata()
        if not meta:
            if self._gate_held:
                self.gate.release_exclusive()
                self._gate_held = False
            try:
                self.lock_file.unlink()
            except OSError:
                pass
            return

        # Check token_id match
        if token.token_id != meta.get("token_id"):
            raise MaintenanceModeError(
                f"Cannot release maintenance mode: token '{token.token_id[:8]}' does not match active owner."
            )

        # Check signature match against lock metadata
        salt = meta.get("salt", "")
        normalized_meta_db = meta.get("db_path", "")
        expected_sig = hmac.new(
            salt.encode("utf-8"),
            f"{token.token_id}:{normalized_meta_db}:{token.created_at}:{token.actor}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(token.signature, expected_sig):
            raise MaintenanceModeError("Cannot release maintenance mode: token signature is invalid or forged.")

        token.invalidate()
        if self._active_token:
            self._active_token.invalidate()
            self._active_token = None

        if self._gate_held:
            self.gate.release_exclusive()
            self._gate_held = False

        try:
            self.lock_file.unlink()
        except OSError:
            pass

    def is_active(self) -> bool:
        """Check if maintenance mode is currently active."""
        if not self.lock_file.exists():
            return False
        try:
            data = json.loads(self.lock_file.read_text(encoding="utf-8"))
            return bool(data.get("active", False))
        except Exception:
            # If lock file exists and cannot be parsed, treat as active for safety
            return True

    def get_metadata(self) -> Optional[dict]:
        """Return maintenance lock metadata if active."""
        if not self.lock_file.exists():
            return None
        try:
            return json.loads(self.lock_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_active_token(self) -> Optional[MaintenanceToken]:
        """Return currently active token if maintenance mode is enabled."""
        if self.is_active() and self._active_token and self._active_token.is_valid:
            return self._active_token
        return None

    def validate_token(self, token: Optional[MaintenanceToken]) -> bool:
        """
        Validate whether the provided token matches active maintenance state:
        1. Checks token presence and in-memory validity.
        2. Verifies maintenance mode is currently active on disk.
        3. Verifies token is bound to this exact database path.
        4. Verifies token_id matches active metadata token_id.
        5. Validates cryptographic HMAC signature against secret salt in metadata.
        """
        if token is None or not isinstance(token, MaintenanceToken) or not token.is_valid:
            return False
        if not self.is_active():
            return False
        meta = self.get_metadata()
        if not meta:
            return False

        # Database path binding check
        normalized_token_db = str(Path(token.db_path).resolve()) if token.db_path and token.db_path != ":memory:" else str(token.db_path)
        normalized_meta_db = str(Path(meta.get("db_path", "")).resolve()) if meta.get("db_path") and meta.get("db_path") != ":memory:" else str(meta.get("db_path", ""))
        if normalized_token_db != normalized_meta_db:
            return False

        if self.db_path and self.db_path != ":memory:":
            normalized_self_db = str(Path(self.db_path).resolve())
            if normalized_token_db != normalized_self_db:
                return False

        # Token ID match
        if token.token_id != meta.get("token_id"):
            return False

        # Cryptographic signature verification
        salt = meta.get("salt", "")
        expected_sig = hmac.new(
            salt.encode("utf-8"),
            f"{token.token_id}:{normalized_meta_db}:{token.created_at}:{token.actor}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(token.signature, expected_sig)


def get_maintenance_lock_file(db_path: Optional[str] = None) -> Path:
    """Resolve the appropriate maintenance lock file for the given database path."""
    if not db_path or db_path == ":memory:":
        return DEFAULT_MAINTENANCE_LOCK
    p = Path(db_path)
    return p.parent / ".maintenance_lock"


def get_database_gate_file(db_path: Optional[str] = None) -> Path:
    """Resolve the appropriate DatabaseGate file for the given database path."""
    if not db_path or db_path == ":memory:":
        return DEFAULT_GATE_FILE
    p = Path(db_path)
    return p.parent / f".{p.name}.gate"


def is_maintenance_active(db_path: Optional[str] = None) -> bool:
    """Return True if maintenance mode is currently active for the specified database."""
    if db_path == ":memory:":
        return False
    lock_file = get_maintenance_lock_file(db_path)
    return MaintenanceManager(lock_file=lock_file, db_path=db_path).is_active()
