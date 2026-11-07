"""
Brand Rule Lab — Append-Only Audit Logger
Owned by Agent A1 (Backend & Data Engineer).

Records all governance decisions: approvals, change requests, escalations,
creator finding actions (accept/edit/dismiss), and reviewer UNLINKED overrides.
Strictly append-only: Contains ZERO Update or Delete operations.
"""

from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional
from core.db import get_connection
from core.models import Finding, ReviewEvent, Role


def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    """Extract column names from PRAGMA table_info safely across sqlite3.Row and tuple rows."""
    cursor.execute(f"PRAGMA table_info({table_name});")
    cols = set()
    for row in cursor.fetchall():
        if hasattr(row, "keys") and "name" in row.keys():
            cols.add(row["name"])
        elif isinstance(row, dict) and "name" in row:
            cols.add(row["name"])
        elif isinstance(row, (tuple, list)) and len(row) > 1:
            cols.add(row[1])
    return cols


def log_review_event(
    asset_id: str,
    actor: str,
    role: Role | str,
    action: str,
    comment: Optional[str] = None,
    override_reason: Optional[str] = None,
    finding_id: Optional[str] = None,
    previous_action: Optional[str] = None,
    new_action: Optional[str] = None,
    event_fingerprint: Optional[str] = None,
    provenance: str = "USER_ACTION",
    known_before_timestamp: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> ReviewEvent:
    """Record an immutable review event to the audit trail."""
    role_obj = Role(role) if isinstance(role, str) else role
    event_id = f"EVT-{uuid.uuid4().hex[:8]}"
    now_ts = datetime.utcnow().isoformat()

    event = ReviewEvent(
        event_id=event_id,
        asset_id=asset_id,
        actor=actor,
        role=role_obj,
        action=action,
        comment=comment,
        override_reason=override_reason,
        timestamp=now_ts,
        finding_id=finding_id,
        previous_action=previous_action,
        new_action=new_action,
        event_fingerprint=event_fingerprint,
        provenance=provenance,
        known_before_timestamp=known_before_timestamp,
    )

    def _execute_insert(c: sqlite3.Connection) -> None:
        cursor = c.cursor()
        cols = _get_table_columns(cursor, "review_events")
        if "finding_id" in cols:
            cursor.execute(
                """
                INSERT INTO review_events (
                    event_id, asset_id, actor, role, action, comment, override_reason, timestamp,
                    finding_id, previous_action, new_action, event_fingerprint, provenance, known_before_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.asset_id,
                    event.actor,
                    event.role.value,
                    event.action,
                    event.comment,
                    event.override_reason,
                    event.timestamp,
                    event.finding_id,
                    event.previous_action,
                    event.new_action,
                    event.event_fingerprint,
                    event.provenance,
                    event.known_before_timestamp,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO review_events (
                    event_id, asset_id, actor, role, action, comment, override_reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.asset_id,
                    event.actor,
                    event.role.value,
                    event.action,
                    event.comment,
                    event.override_reason,
                    event.timestamp,
                ),
            )

    if conn is not None:
        _execute_insert(conn)
    else:
        with get_connection(db_path) as c:
            _execute_insert(c)

    return event


def log_creator_decision(
    asset_id: str,
    actor: str,
    action: str,  # e.g. "accept_rewrite", "edit_rewrite", "dismiss_finding"
    finding_id: str,
    previous_action: str = "pending",
    new_action: str = "accepted",
    comment: Optional[str] = None,
    event_fingerprint: Optional[str] = None,
    provenance: str = "USER_ACTION",
    known_before_timestamp: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[ReviewEvent]:
    """
    Log a Creator action on a finding (accept, edit, dismiss).
    Idempotent: If an event with matching (asset_id, event_fingerprint) already exists,
    skips insertion to avoid duplicating audit records on Streamlit reruns.
    """
    fp = event_fingerprint or f"FPR-{asset_id}-{finding_id}-{new_action}"

    def _check_and_insert(c: sqlite3.Connection) -> Optional[ReviewEvent]:
        # Check for duplicate event fingerprint if column exists
        cursor = c.cursor()
        cols = _get_table_columns(cursor, "review_events")
        if "event_fingerprint" in cols:
            cursor.execute(
                "SELECT 1 FROM review_events WHERE asset_id = ? AND event_fingerprint = ? LIMIT 1;",
                (asset_id, fp),
            )
            if cursor.fetchone():
                return None

        return log_review_event(
            asset_id=asset_id,
            actor=actor,
            role=Role.CREATOR,
            action=action,
            comment=comment,
            finding_id=finding_id,
            previous_action=previous_action,
            new_action=new_action,
            event_fingerprint=fp,
            provenance=provenance,
            known_before_timestamp=known_before_timestamp,
            conn=c,
        )

    if conn is not None:
        return _check_and_insert(conn)
    else:
        with get_connection(db_path) as c:
            return _check_and_insert(c)


def apply_creator_decision(
    finding: Finding,
    action: str,  # "accepted", "edited", or "dismissed"
    new_text: Optional[str] = None,
    dismiss_reason: Optional[str] = None,
    actor: str = "Alex Chen (Creator)",
    role: Optional[Role | str] = None,
    asset_id: Optional[str] = None,
    previous_action: str = "pending",
    review_cycle: Optional[int] = None,
    comment: Optional[str] = None,
    event_fingerprint: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    _fail_after_finding: bool = False,
) -> Optional[ReviewEvent]:
    """
    Atomically update the finding in SQLite and record the Creator audit event in review_events.
    Both operations execute inside the same SQLite transaction.
    If either fails, both are rolled back.
    Preserves fingerprint deduplication for Streamlit reruns.
    Enforces that only Creator role can record finding decisions.
    Requires an explicit role; missing/None role is rejected.
    """
    from core.permissions import enforce_permission

    target_asset = asset_id or finding.asset_id
    cycle = review_cycle if review_cycle is not None else getattr(finding, "review_cycle", 1)

    if action == "accepted":
        enforce_permission(role, "accept_finding")
        evt_action = "accept_rewrite"
        text_val = new_text or finding.suggested_rewrite
        dism_val = None
        default_comment = f"Accepted rewrite for {finding.rule_id or finding.fact_id}: '{text_val}'"
    elif action == "edited":
        enforce_permission(role, "edit_finding")
        evt_action = "edit_rewrite"
        text_val = new_text or finding.suggested_rewrite
        dism_val = None
        default_comment = f"Custom edit for {finding.rule_id or finding.fact_id}: '{text_val}'"
    elif action == "dismissed":
        enforce_permission(role, "dismiss_finding")
        if not dismiss_reason or not str(dismiss_reason).strip():
            raise ValueError("Dismissing a finding requires a mandatory standard reason.")
        evt_action = "dismiss_finding"
        text_val = finding.suggested_rewrite
        dism_val = str(dismiss_reason).strip()
        default_comment = f"Dismissed finding for {finding.rule_id or finding.fact_id}: {dism_val}"
    else:
        raise ValueError(f"Unknown creator action: {action}. Must be 'accepted', 'edited', or 'dismissed'.")

    def _execute(c: sqlite3.Connection) -> Optional[ReviewEvent]:
        # 1. Update / upsert findings row
        try:
            c.execute(
                """
                INSERT INTO findings (
                    finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                    rule_id, fact_id, fact_version_id, link_state, message, next_step,
                    suggested_rewrite, creator_action, dismiss_reason, review_cycle
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(finding_id) DO UPDATE SET
                    creator_action = excluded.creator_action,
                    suggested_rewrite = excluded.suggested_rewrite,
                    dismiss_reason = excluded.dismiss_reason,
                    review_cycle = excluded.review_cycle;
                """,
                (
                    finding.finding_id,
                    target_asset,
                    finding.kind.value if hasattr(finding.kind, "value") else str(finding.kind),
                    finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity),
                    finding.span_start,
                    finding.span_end,
                    finding.source_text,
                    finding.rule_id,
                    finding.fact_id,
                    finding.fact_version_id,
                    finding.link_state.value if hasattr(finding.link_state, "value") else str(finding.link_state),
                    finding.message,
                    finding.next_step,
                    text_val,
                    action,
                    dism_val,
                    cycle,
                ),
            )
        except sqlite3.OperationalError as ex:
            if "has no column named review_cycle" in str(ex):
                c.execute(
                    """
                    INSERT INTO findings (
                        finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                        rule_id, fact_id, fact_version_id, link_state, message, next_step,
                        suggested_rewrite, creator_action, dismiss_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(finding_id) DO UPDATE SET
                        creator_action = excluded.creator_action,
                        dismiss_reason = excluded.dismiss_reason,
                        suggested_rewrite = excluded.suggested_rewrite;
                    """,
                    (
                        finding.finding_id,
                        target_asset,
                        finding.kind.value if hasattr(finding.kind, "value") else str(finding.kind),
                        finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity),
                        finding.span_start,
                        finding.span_end,
                        finding.source_text,
                        finding.rule_id,
                        finding.fact_id,
                        finding.fact_version_id,
                        finding.link_state.value if hasattr(finding.link_state, "value") else str(finding.link_state),
                        finding.message,
                        finding.next_step,
                        text_val,
                        action,
                        dism_val,
                    ),
                )
            else:
                raise

        # Fault injection hook for atomicity testing
        if _fail_after_finding:
            raise RuntimeError("Simulated failure after finding update before audit log!")

        # 2. Record matching audit event
        return log_creator_decision(
            asset_id=target_asset,
            actor=actor,
            action=evt_action,
            finding_id=finding.finding_id,
            previous_action=previous_action,
            new_action=action,
            comment=comment or default_comment,
            event_fingerprint=event_fingerprint,
            conn=c,
        )

    if conn is not None:
        return _execute(conn)
    else:
        with get_connection(db_path) as c:
            return _execute(c)


def get_asset_audit_trail(asset_id: str, db_path: Optional[str] = None) -> List[ReviewEvent]:
    """Retrieve full chronological audit history for an asset, compatible with legacy and migrated schemas."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cols = _get_table_columns(cursor, "review_events")
        has_finding_id = "finding_id" in cols

        if has_finding_id:
            query = """
            SELECT event_id, asset_id, actor, role, action, comment, override_reason, timestamp,
                   finding_id, previous_action, new_action, event_fingerprint, provenance, known_before_timestamp
            FROM review_events
            WHERE asset_id = ?
            ORDER BY timestamp ASC;
            """
        else:
            query = """
            SELECT event_id, asset_id, actor, role, action, comment, override_reason, timestamp
            FROM review_events
            WHERE asset_id = ?
            ORDER BY timestamp ASC;
            """

        cursor.execute(query, (asset_id,))
        rows = cursor.fetchall()
        return [
            ReviewEvent(
                event_id=r["event_id"],
                asset_id=r["asset_id"],
                actor=r["actor"],
                role=Role(r["role"]),
                action=r["action"],
                comment=r["comment"],
                override_reason=r["override_reason"],
                timestamp=r["timestamp"],
                finding_id=r["finding_id"] if has_finding_id and "finding_id" in r.keys() else None,
                previous_action=r["previous_action"] if "previous_action" in r.keys() else None,
                new_action=r["new_action"] if "new_action" in r.keys() else None,
                event_fingerprint=r["event_fingerprint"] if "event_fingerprint" in r.keys() else None,
                provenance=r["provenance"] if "provenance" in r.keys() and r["provenance"] is not None else "USER_ACTION",
                known_before_timestamp=r["known_before_timestamp"] if "known_before_timestamp" in r.keys() else None,
            )
            for r in rows
        ]
