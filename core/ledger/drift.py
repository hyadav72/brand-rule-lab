"""
Brand Rule Lab — Fact Drift Cascade and Expiry Sweeps
Owned by Agent A1 (Backend & Data Engineer).

Slide 7 & Non-Negotiable Rule 7:
Fact update = 0 LLM calls, 0 web crawls, 1 SQL update.
Implemented verbatim in transactions returning affected row counts.
"""

from __future__ import annotations
from typing import Optional
from core.db import get_connection


def cascade_fact_update(fact_id: str, new_version: int, db_path: Optional[str] = None) -> int:
    """
    Propagate fact version update across all approved dependent claims.
    Flags claims linked to older fact versions as REVIEW_REQUIRED.
    Zero LLM calls, Zero web crawls, exactly 1 SQL UPDATE.
    """
    query = """
    UPDATE approved_claims
    SET drift_status = 'REVIEW_REQUIRED', flagged_at = CURRENT_TIMESTAMP
    WHERE fact_id = ? AND fact_version_id < ? AND drift_status = 'CURRENT';
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (fact_id, new_version))
        return cursor.rowcount


def sweep_expiry(today: str, db_path: Optional[str] = None) -> int:
    """
    Flag claims linked to expired facts as EXPIRED.
    Single SQL UPDATE query across all registered claims.
    """
    query = """
    UPDATE approved_claims
    SET drift_status = 'EXPIRED', flagged_at = CURRENT_TIMESTAMP
    WHERE fact_id IN (
        SELECT fact_id FROM fact_versions WHERE expires_at IS NOT NULL AND expires_at < ?
    ) AND drift_status = 'CURRENT';
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (today,))
        return cursor.rowcount
