"""
Brand Rule Lab — Factual Knowledge Retrieval
Owned by Agent A1 (Backend & Data Engineer).

Retrieves approved brand facts from SQLite by product, market, and temporal validity window.
Never delegates retrieval filtering to LLM claim types.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from core.db import execute_commit, execute_query
from core.models import FactVersion, Role
from core.permissions import enforce_permission


def lookup_facts(
    product_id: str,
    market: str,
    today: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[FactVersion]:
    """
    Retrieve all valid fact versions for specified product and market.
    Enforces validity window: valid_from <= today AND (expires_at IS NULL OR expires_at >= today).
    Returns the latest version per fact_id (highest version number within the validity window).
    """
    check_date = today or datetime.utcnow().strftime("%Y-%m-%d")

    query = """
    SELECT fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner
    FROM fact_versions
    WHERE product_id = ?
      AND market = ?
      AND valid_from <= ?
      AND (expires_at IS NULL OR expires_at >= ?)
    ORDER BY fact_id ASC, version DESC;
    """
    rows = execute_query(query, (product_id, market, check_date, check_date), db_path=db_path)

    # Return latest version per fact_id
    seen_facts = set()
    results: List[FactVersion] = []
    for r in rows:
        fid = r["fact_id"]
        if fid not in seen_facts:
            seen_facts.add(fid)
            results.append(FactVersion(
                fact_id=r["fact_id"],
                version=r["version"],
                product_id=r["product_id"],
                market=r["market"],
                fact_text=r["fact_text"],
                permitted_wording=r["permitted_wording"],
                valid_from=r["valid_from"],
                expires_at=r["expires_at"],
                owner=r["owner"],
            ))

    return results


def lookup_all_valid_fact_versions(
    product_id: str,
    market: str,
    today: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[FactVersion]:
    """
    Retrieve ALL currently valid fact versions (every version, not just the latest per fact_id)
    for a specific product and market within the temporal validity window.

    Used for clinical claim matching in check_rewrite() so that a rewrite citing an older
    but still-valid approved version (e.g. F-112 v3 wording while v4 is also active) is
    correctly recognised as backed — without allowing evidence from other products.
    """
    check_date = today or datetime.utcnow().strftime("%Y-%m-%d")

    query = """
    SELECT fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner
    FROM fact_versions
    WHERE product_id = ?
      AND market = ?
      AND valid_from <= ?
      AND (expires_at IS NULL OR expires_at >= ?)
    ORDER BY fact_id ASC, version DESC;
    """
    rows = execute_query(query, (product_id, market, check_date, check_date), db_path=db_path)

    return [
        FactVersion(
            fact_id=r["fact_id"],
            version=r["version"],
            product_id=r["product_id"],
            market=r["market"],
            fact_text=r["fact_text"],
            permitted_wording=r["permitted_wording"],
            valid_from=r["valid_from"],
            expires_at=r["expires_at"],
            owner=r["owner"],
        )
        for r in rows
    ]


def get_fact_version(
    fact_id: str,
    version: int,
    db_path: Optional[str] = None,
) -> Optional[FactVersion]:
    """Retrieve a specific approved fact version by fact ID and version number."""
    query = """
    SELECT fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner
    FROM fact_versions
    WHERE fact_id = ? AND version = ?;
    """
    rows = execute_query(query, (fact_id, version), db_path=db_path)
    if not rows:
        return None
    r = rows[0]
    return FactVersion(
        fact_id=r["fact_id"],
        version=r["version"],
        product_id=r["product_id"],
        market=r["market"],
        fact_text=r["fact_text"],
        permitted_wording=r["permitted_wording"],
        valid_from=r["valid_from"],
        expires_at=r["expires_at"],
        owner=r["owner"],
    )


def publish_fact_version(
    fact_id: str,
    version: int,
    product_id: str,
    market: str,
    fact_text: str,
    permitted_wording: str,
    valid_from: Optional[str] = None,
    expires_at: Optional[str] = None,
    owner: str = "brand_science",
    role: Optional[Role | str] = None,
    db_path: Optional[str] = None,
) -> int:
    """
    Publish or update a brand fact version in fact_versions table.
    Enforces that only Fact Owner role can create or publish fact versions.
    Requires an explicit role; missing/None role is rejected.
    """
    enforce_permission(role, "create_fact_version")
    val_from = valid_from or datetime.utcnow().strftime("%Y-%m-%d")
    return execute_commit(
        """
        INSERT INTO fact_versions (fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fact_id, version) DO UPDATE SET
            fact_text = excluded.fact_text,
            permitted_wording = excluded.permitted_wording,
            valid_from = excluded.valid_from,
            expires_at = excluded.expires_at,
            owner = excluded.owner;
        """,
        (fact_id, version, product_id, market, fact_text, permitted_wording, val_from, expires_at, owner),
        db_path=db_path,
    )

