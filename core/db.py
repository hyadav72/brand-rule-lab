"""
Brand Rule Lab — Database Access Layer
Owned by Agent A1 (Backend & Data Engineer).

Manages SQLite connections, schema initialization, and transactional queries.
Enforces foreign keys and read/write integrity.
"""

from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "data/brand_rule_lab.db")
SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Return configured database path, ensuring directory exists."""
    path_str = custom_path or DEFAULT_DB_PATH
    if path_str != ":memory:":
        db_file = Path(path_str)
        db_file.parent.mkdir(parents=True, exist_ok=True)
    return path_str


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager yielding an open SQLite connection with foreign keys enabled.
    Commits on successful block completion; rolls back on unhandled exceptions.
    """
    target_path = get_db_path(db_path)
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


def init_db(db_path: Optional[str] = None, schema_path: Optional[Path] = None) -> None:
    """Initialize database schema from schema.sql idempotently."""
    sql_file = schema_path or SCHEMA_SQL_PATH
    if not sql_file.exists():
        raise FileNotFoundError(f"Schema file not found at: {sql_file}")

    schema_sql = sql_file.read_text(encoding="utf-8")
    with get_connection(db_path) as conn:
        conn.executescript(schema_sql)


def execute_query(query: str, params: Tuple[Any, ...] = (), db_path: Optional[str] = None) -> List[sqlite3.Row]:
    """Execute read-only query and return list of rows."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_commit(query: str, params: Tuple[Any, ...] = (), db_path: Optional[str] = None) -> int:
    """Execute mutating statement and return affected row count."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.rowcount
