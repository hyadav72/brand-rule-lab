"""
Brand Rule Lab — Factual Knowledge Retrieval
Owned by Agent A1 (Backend & Data Engineer).

Retrieves approved brand facts from SQLite by product, market, and temporal validity window.
Never delegates retrieval filtering to LLM claim types.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from core.db import execute_query
from core.models import FactVersion


def lookup_facts(
    product_id: str,
    market: str,
    today: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[FactVersion]:
    """
    Retrieve all valid fact versions for specified product and market.
    Enforces validity window: valid_from <= today AND (expires_at IS NULL OR expires_at >= today).
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
