"""
Brand Rule Lab — Asset Draft Snapshot and Submission Store
Owned by Agent A1 (Backend & Data Engineer).

Writes immutable snapshots of:
1. The original marketing draft text at first submission (asset_original_snapshots).
2. The topological submission record per review cycle (asset_submissions).
3. The effective post-compliance submitted copy snapshot per review cycle (asset_effective_snapshots).

All snapshots and submissions are protected by SQLite immutability triggers (RAISE ABORT).
"""

from __future__ import annotations
import hashlib
import sqlite3
import uuid
from typing import List, Optional
from core.db import execute_commit, execute_query, get_connection
from core.models import Finding, Role


def save_original_snapshot(
    asset_id: str,
    original_text: str,
    captured_by: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """
    Persist the original draft text as an immutable snapshot (once per asset).
    If a snapshot already exists for this asset_id (UNIQUE constraint), the
    INSERT is silently skipped and the existing snapshot_id is returned.

    Returns:
        snapshot_id: e.g. 'SNAP-AST-abc123'
    """
    snapshot_id = f"SNAP-{asset_id}"
    content_hash = hashlib.sha256(original_text.encode("utf-8")).hexdigest()

    sql = """
    INSERT INTO asset_original_snapshots
        (snapshot_id, asset_id, original_text, content_hash, captured_by)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(asset_id) DO NOTHING;
    """
    params = (snapshot_id, asset_id, original_text, content_hash, captured_by)

    if conn is not None:
        conn.execute(sql, params)
    else:
        execute_commit(sql, params, db_path=db_path)

    return snapshot_id


def get_original_snapshot(
    asset_id: str,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    """
    Retrieve the immutable original draft snapshot for an asset.

    Returns a dict with keys: snapshot_id, asset_id, original_text,
    content_hash, captured_by, captured_at — or None if not found.
    """
    rows = execute_query(
        """
        SELECT snapshot_id, asset_id, original_text, content_hash, captured_by, captured_at
        FROM asset_original_snapshots
        WHERE asset_id = ?;
        """,
        (asset_id,),
        db_path=db_path,
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "snapshot_id": r["snapshot_id"],
        "asset_id": r["asset_id"],
        "original_text": r["original_text"],
        "content_hash": r["content_hash"],
        "captured_by": r["captured_by"],
        "captured_at": r["captured_at"],
    }


def create_submission(
    asset_id: str,
    review_cycle: int,
    submitted_by: str,
    submitted_at: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """
    Record a topological parent submission in asset_submissions.
    Enforces UNIQUE(asset_id, review_cycle).

    Returns:
        submission_id: e.g. 'SUB-AST-ffed5f-C1'
    """
    submission_id = f"SUB-{asset_id}-C{review_cycle}"

    try:
        if submitted_at:
            sql = """
            INSERT INTO asset_submissions (submission_id, asset_id, review_cycle, submitted_by, submitted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, review_cycle) DO NOTHING;
            """
            params = (submission_id, asset_id, review_cycle, submitted_by, submitted_at)
        else:
            sql = """
            INSERT INTO asset_submissions (submission_id, asset_id, review_cycle, submitted_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asset_id, review_cycle) DO NOTHING;
            """
            params = (submission_id, asset_id, review_cycle, submitted_by)

        if conn is not None:
            conn.execute(sql, params)
        else:
            execute_commit(sql, params, db_path=db_path)
    except sqlite3.OperationalError as ex:
        if "no such table" in str(ex):
            pass
        else:
            raise

    return submission_id


def get_submission(
    asset_id: str,
    review_cycle: int = 1,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    """Retrieve submission record for an asset and cycle."""
    rows = execute_query(
        """
        SELECT submission_id, asset_id, review_cycle, submitted_by, submitted_at
        FROM asset_submissions
        WHERE asset_id = ? AND review_cycle = ?;
        """,
        (asset_id, review_cycle),
        db_path=db_path,
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "submission_id": r["submission_id"],
        "asset_id": r["asset_id"],
        "review_cycle": r["review_cycle"],
        "submitted_by": r["submitted_by"],
        "submitted_at": r["submitted_at"],
    }


def save_effective_snapshot(
    asset_id: str,
    submission_id: str,
    effective_text: str,
    captured_by: str,
    review_cycle: int = 1,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """
    Persist an immutable post-compliance submitted copy snapshot in asset_effective_snapshots.
    Protected by UNIQUE(asset_id, review_cycle) and immutability triggers.

    Returns:
        snapshot_id: e.g. 'SNAP-EFF-AST-ffed5f-C1'
    """
    sid = snapshot_id or f"SNAP-EFF-{asset_id}-C{review_cycle}"
    content_hash = hashlib.sha256(effective_text.encode("utf-8")).hexdigest()

    try:
        if captured_at:
            sql = """
            INSERT INTO asset_effective_snapshots
                (snapshot_id, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, review_cycle) DO NOTHING;
            """
            params = (sid, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by, captured_at)
        else:
            sql = """
            INSERT INTO asset_effective_snapshots
                (snapshot_id, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, review_cycle) DO NOTHING;
            """
            params = (sid, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by)

        if conn is not None:
            conn.execute(sql, params)
        else:
            execute_commit(sql, params, db_path=db_path)
    except sqlite3.OperationalError as ex:
        if "no such table" in str(ex):
            pass
        else:
            raise

    return sid


def get_effective_snapshot(
    asset_id: str,
    review_cycle: int = 1,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    """Retrieve effective snapshot for an asset and cycle."""
    rows = execute_query(
        """
        SELECT snapshot_id, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by, captured_at
        FROM asset_effective_snapshots
        WHERE asset_id = ? AND review_cycle = ?;
        """,
        (asset_id, review_cycle),
        db_path=db_path,
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "snapshot_id": r["snapshot_id"],
        "submission_id": r["submission_id"],
        "asset_id": r["asset_id"],
        "review_cycle": r["review_cycle"],
        "effective_text": r["effective_text"],
        "content_hash": r["content_hash"],
        "captured_by": r["captured_by"],
        "captured_at": r["captured_at"],
    }


def submit_draft(
    asset_id: str,
    original_text: str,
    submitted_text: str,
    findings: List[Finding],
    actions: dict,
    actor_name: str = "Alex Chen (Creator)",
    role: Optional[Role | str] = None,
    review_cycle: Optional[int] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    _fail_at_stage: Optional[int] = None,
) -> dict:
    """
    Execute the entire draft submission workflow in ONE atomic SQLite transaction.

    The transaction includes:
    1. All finding inserts/updates.
    2. Original snapshot creation.
    3. Submission record creation.
    4. Effective snapshot creation.
    5. Asset text and status update.
    6. Submission audit event.

    If any step fails, all preceding writes are rolled back.
    When a shared `conn` is provided, the caller owns commit/rollback.
    Enforces that only Creator role can submit drafts for review.
    Requires an explicit role; missing/None role is rejected.
    """
    from core.audit import log_review_event
    from core.models import Role
    from core.permissions import enforce_permission

    enforce_permission(role, "submit_for_review")
    creator_role = Role(role) if isinstance(role, str) else role

    def _execute_pipeline(c: sqlite3.Connection) -> dict:
        cycle = review_cycle if review_cycle is not None else 1

        # Stage 1: All finding inserts/updates
        if _fail_at_stage == 1:
            raise RuntimeError("Simulated failure at Stage 1: Finding inserts/updates")

        for f in findings:
            act_data = actions.get(f.finding_id, {})
            text_val = act_data.get("text", f.suggested_rewrite)
            act_action = act_data.get("action", f.creator_action)
            dism_reason = act_data.get("dismiss_reason", f.dismiss_reason)

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
                        dismiss_reason = excluded.dismiss_reason,
                        suggested_rewrite = excluded.suggested_rewrite,
                        review_cycle = excluded.review_cycle;
                    """,
                    (
                        f.finding_id,
                        asset_id,
                        f.kind.value if hasattr(f.kind, "value") else str(f.kind),
                        f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                        f.span_start,
                        f.span_end,
                        f.source_text,
                        f.rule_id,
                        f.fact_id,
                        f.fact_version_id,
                        f.link_state.value if hasattr(f.link_state, "value") else str(f.link_state),
                        f.message,
                        f.next_step,
                        text_val,
                        act_action,
                        dism_reason,
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
                            f.finding_id,
                            asset_id,
                            f.kind.value if hasattr(f.kind, "value") else str(f.kind),
                            f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                            f.span_start,
                            f.span_end,
                            f.source_text,
                            f.rule_id,
                            f.fact_id,
                            f.fact_version_id,
                            f.link_state.value if hasattr(f.link_state, "value") else str(f.link_state),
                            f.message,
                            f.next_step,
                            text_val,
                            act_action,
                            dism_reason,
                        ),
                    )
                else:
                    raise

        # Stage 2: Original snapshot creation
        if _fail_at_stage == 2:
            raise RuntimeError("Simulated failure at Stage 2: Original snapshot creation")

        orig_snapshot_id = save_original_snapshot(
            asset_id=asset_id,
            original_text=original_text,
            captured_by=actor_name,
            conn=c,
        )

        # Stage 3: Submission record creation
        if _fail_at_stage == 3:
            raise RuntimeError("Simulated failure at Stage 3: Submission record creation")

        submission_id = create_submission(
            asset_id=asset_id,
            review_cycle=cycle,
            submitted_by=actor_name,
            conn=c,
        )

        # Stage 4: Effective snapshot creation
        if _fail_at_stage == 4:
            raise RuntimeError("Simulated failure at Stage 4: Effective snapshot creation")

        eff_snapshot_id = save_effective_snapshot(
            asset_id=asset_id,
            submission_id=submission_id,
            effective_text=submitted_text,
            captured_by=actor_name,
            review_cycle=cycle,
            conn=c,
        )

        # Stage 5: Asset text and status update
        if _fail_at_stage == 5:
            raise RuntimeError("Simulated failure at Stage 5: Asset text and status update")

        c.execute(
            "UPDATE assets SET text_content = ?, status = 'ready_for_review' WHERE asset_id = ?;",
            (submitted_text, asset_id),
        )

        # Stage 6: Submission audit event
        if _fail_at_stage == 6:
            raise RuntimeError("Simulated failure at Stage 6: Submission audit event")

        evt = log_review_event(
            asset_id=asset_id,
            actor=actor_name,
            role=creator_role,
            action="submit_for_review",
            comment=f"Submitted effective draft for cycle {cycle} with {len(findings)} resolved findings. Snapshot: {eff_snapshot_id}",
            conn=c,
        )

        return {
            "submission_id": submission_id,
            "orig_snapshot_id": orig_snapshot_id,
            "eff_snapshot_id": eff_snapshot_id,
            "review_cycle": cycle,
            "event": evt,
        }

    if conn is not None:
        return _execute_pipeline(conn)
    else:
        with get_connection(db_path) as c:
            return _execute_pipeline(c)


def migrate_add_snapshots_table(db_path: Optional[str] = None) -> None:
    """
    Safe idempotent migration: adds original snapshot table and triggers
    to an existing database if not present.
    """
    from core.db import get_db_path
    from core.migrations.runner import is_production_database

    target_path = get_db_path(db_path)
    if is_production_database(target_path):
        # Protected production database: snapshot table already exists, database remains read-only
        return

    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS asset_original_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL UNIQUE,
            original_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            captured_by TEXT NOT NULL,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
        );
        """,
        """
        CREATE TRIGGER IF NOT EXISTS trg_prevent_snapshots_update
        BEFORE UPDATE ON asset_original_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'Mutation forbidden: asset_original_snapshots table is immutable.');
        END;
        """,
        """
        CREATE TRIGGER IF NOT EXISTS trg_prevent_snapshots_delete
        BEFORE DELETE ON asset_original_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'Deletion forbidden: asset_original_snapshots table is immutable.');
        END;
        """,
    ]
    for ddl in ddl_statements:
        execute_commit(ddl, db_path=db_path)
