"""
Brand Rule Lab — Review Cycle Transitions & Concurrency Control
Owned by Agent A1 & A4.

Implements atomic compare-and-swap (CAS) transitions for asset review cycles.
Only an explicit revision request on an asset with status 'changes_requested'
may transition to 'draft' and increment review_cycle.
Concurrent or redundant requests fail atomically (rowcount == 0).
"""

from __future__ import annotations
import hashlib
import sqlite3
from typing import Optional
from core.db import get_connection, execute_query


def start_revision_cycle(asset_id: str, db_path: Optional[str] = None) -> bool:
    """
    Atomic compare-and-swap transition from 'changes_requested' to 'draft'.
    Atomically increments assets.review_cycle by 1.

    Returns:
        True if this invocation won the race and transitioned the asset.
        False if the asset was not in 'changes_requested' state or a concurrent
        request already transitioned it.
    """
    with get_connection(db_path) as conn:
        try:
            cursor = conn.execute(
                """
                UPDATE assets
                SET status = 'draft', review_cycle = review_cycle + 1
                WHERE asset_id = ? AND status = 'changes_requested';
                """,
                (asset_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.OperationalError:
            # Fallback for unmigrated schema lacking review_cycle column
            cursor = conn.execute(
                """
                UPDATE assets
                SET status = 'draft'
                WHERE asset_id = ? AND status = 'changes_requested';
                """,
                (asset_id,),
            )
            conn.commit()
            return cursor.rowcount > 0


def get_asset_review_cycle(
    asset_id: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Retrieve current review_cycle for an asset, defaulting to 1."""
    try:
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute("SELECT review_cycle FROM assets WHERE asset_id = ?;", (asset_id,))
            rows = cursor.fetchall()
        else:
            rows = execute_query(
                "SELECT review_cycle FROM assets WHERE asset_id = ?;",
                (asset_id,),
                db_path=db_path,
            )
        if rows and "review_cycle" in rows[0].keys() and rows[0]["review_cycle"] is not None:
            return int(rows[0]["review_cycle"])
    except Exception:
        pass
    return 1


def load_revision_asset(
    asset_id: str,
    db_path: Optional[str] = None,
) -> dict:
    """
    Load an existing asset and its state for Creator workspace revision.

    Retrieves:
    1. Asset metadata (product, market, channel, publish date, cycle, status).
    2. Effective draft text (from assets.text_content or effective snapshot).
    3. Active findings for the current review cycle (or most recent cycle).
    4. Creator action state and decisions (accepted, edited, dismissed, pending).
    5. Associated ExtractedDoc and active_context dictionaries.

    Preserves stable finding IDs and their review-cycle relationships.
    Does not mutate or partially update database state.
    """
    from core.models import (
        CreatorActionState,
        ExtractedDoc,
        Finding,
        FindingKind,
        LinkState,
        Severity,
    )
    from core.snapshots import get_effective_snapshot, get_original_snapshot

    rows = execute_query(
        """
        SELECT asset_id, name, product_id, market, channel, status, created_by,
               source_hash, text_content, planned_publish_date, review_cycle
        FROM assets
        WHERE asset_id = ?;
        """,
        (asset_id,),
        db_path=db_path,
    )
    if not rows:
        raise ValueError(f"Asset '{asset_id}' not found.")

    asset = dict(rows[0])
    current_cycle = int(asset["review_cycle"]) if "review_cycle" in asset and asset["review_cycle"] is not None else 1

    # 1. Effective draft text
    draft_text = asset.get("text_content") or ""
    if not draft_text:
        eff = get_effective_snapshot(asset_id, review_cycle=current_cycle, db_path=db_path)
        if not eff and current_cycle > 1:
            eff = get_effective_snapshot(asset_id, review_cycle=current_cycle - 1, db_path=db_path)
        if eff:
            draft_text = eff.get("effective_text") or ""

    if not draft_text:
        orig = get_original_snapshot(asset_id, db_path=db_path)
        if orig:
            draft_text = orig.get("original_text") or ""

    doc = ExtractedDoc(
        text=draft_text,
        pages=[draft_text] if draft_text else [],
        source_filename=asset.get("name") or f"{asset_id}.txt",
        source_hash=asset.get("source_hash") or hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
    )

    # 2. Asset context
    context = {
        "asset_id": asset["asset_id"],
        "product": asset["product_id"],
        "market": asset["market"],
        "channel": asset["channel"],
        "planned_publish_date": asset["planned_publish_date"] or "2026-11-10",
        "review_cycle": current_cycle,
    }

    # 3. Active findings for current review cycle
    finding_rows = execute_query(
        """
        SELECT finding_id, asset_id, kind, severity, span_start, span_end, source_text,
               rule_id, fact_id, fact_version_id, link_state, message, next_step,
               suggested_rewrite, creator_action, dismiss_reason, review_cycle
        FROM findings
        WHERE asset_id = ? AND review_cycle = ?
        ORDER BY span_start ASC;
        """,
        (asset_id, current_cycle),
        db_path=db_path,
    )
    if not finding_rows:
        finding_rows = execute_query(
            """
            SELECT finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                   rule_id, fact_id, fact_version_id, link_state, message, next_step,
                   suggested_rewrite, creator_action, dismiss_reason, review_cycle
            FROM findings
            WHERE asset_id = ?
            ORDER BY review_cycle DESC, span_start ASC;
            """,
            (asset_id,),
            db_path=db_path,
        )

    findings: list[Finding] = []
    actions: dict[str, dict] = {}

    for row_item in finding_rows:
        r = dict(row_item)
        k = FindingKind(r["kind"]) if isinstance(r["kind"], str) else r["kind"]
        s = Severity(r["severity"]) if isinstance(r["severity"], str) else r["severity"]
        ls = LinkState(r["link_state"]) if isinstance(r["link_state"], str) else r["link_state"]

        ca_raw = r.get("creator_action", "pending") or "pending"
        if isinstance(ca_raw, str):
            try:
                ca_enum = CreatorActionState(ca_raw)
            except Exception:
                ca_enum = CreatorActionState.PENDING
        else:
            ca_enum = ca_raw or CreatorActionState.PENDING

        f_cycle = int(r["review_cycle"]) if "review_cycle" in r and r["review_cycle"] is not None else 1

        f = Finding(
            finding_id=r["finding_id"],
            asset_id=r["asset_id"],
            kind=k,
            severity=s,
            span_start=r["span_start"],
            span_end=r["span_end"],
            source_text=r["source_text"],
            rule_id=r["rule_id"],
            fact_id=r["fact_id"],
            fact_version_id=r["fact_version_id"],
            link_state=ls,
            message=r["message"],
            next_step=r["next_step"],
            suggested_rewrite=r["suggested_rewrite"],
            creator_action=ca_enum,
            dismiss_reason=r["dismiss_reason"],
            review_cycle=f_cycle,
        )
        findings.append(f)

        act_str = ca_enum.value if hasattr(ca_enum, "value") else str(ca_enum)
        actions[f.finding_id] = {
            "action": act_str,
            "text": f.suggested_rewrite or "",
            "dismiss_reason": f.dismiss_reason or "",
        }

    return {
        "asset": dict(asset),
        "doc": doc,
        "context": context,
        "findings": findings,
        "actions": actions,
        "review_cycle": current_cycle,
    }

