"""
Brand Rule Lab — Append-Only Audit Logger
Owned by Agent A1 (Backend & Data Engineer).

Records all governance decisions: approvals, change requests, escalations,
finding dismissals, and reviewer UNLINKED overrides.
Strictly append-only: Contains ZERO Update or Delete operations.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import List, Optional
from core.db import get_connection
from core.models import ReviewEvent, Role


def log_review_event(
    asset_id: str,
    actor: str,
    role: Role | str,
    action: str,
    comment: Optional[str] = None,
    override_reason: Optional[str] = None,
    db_path: Optional[str] = None,
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
    )

    with get_connection(db_path) as conn:
        conn.execute(
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

    return event


def get_asset_audit_trail(asset_id: str, db_path: Optional[str] = None) -> List[ReviewEvent]:
    """Retrieve full chronological audit history for an asset."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, asset_id, actor, role, action, comment, override_reason, timestamp
            FROM review_events
            WHERE asset_id = ?
            ORDER BY timestamp ASC;
            """,
            (asset_id,),
        )
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
            )
            for r in rows
        ]
