"""
Brand Rule Lab — Permissions and Audit Log Tests
Owned by Agent A5 (QA Engineer).
"""

import sqlite3
import pytest
from core.audit import log_review_event, get_asset_audit_trail
from core.db import init_db, get_connection
from core.models import Role
from core.permissions import can_perform, enforce_permission


@pytest.fixture
def seeded_db(tmp_path):
    """Provide initialized database with sample asset."""
    db_file = tmp_path / "test_permissions.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert prerequisite product and asset
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO products VALUES ('prod_monsoon', 'Monsoon Clear Skin', '[]', 'US');"
        )
        conn.execute(
            """
            INSERT INTO assets (
                asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date
            ) VALUES ('AST-001', 'Acne Wash Social', 'prod_monsoon', 'US', 'paid_social', 'draft', 'Alex', 'hash123', 'Sample draft', '2026-11-10');
            """
        )
    return db_path


def test_role_permissions():
    """Verify role boundaries as required by Section 12."""
    # Creator permissions
    assert can_perform(Role.CREATOR, "upload_draft")
    assert can_perform(Role.CREATOR, "submit_for_review")
    assert not can_perform(Role.CREATOR, "approve_asset")  # Creator CANNOT approve
    assert not can_perform(Role.CREATOR, "create_fact_version")

    # Reviewer permissions
    assert can_perform(Role.REVIEWER, "approve_asset")
    assert can_perform(Role.REVIEWER, "request_changes")
    assert not can_perform(Role.REVIEWER, "create_fact_version")  # Reviewer CANNOT edit facts
    assert not can_perform(Role.REVIEWER, "upload_draft")

    # Fact Owner permissions
    assert can_perform(Role.FACT_OWNER, "create_fact_version")
    assert can_perform(Role.FACT_OWNER, "trigger_drift_cascade")
    assert not can_perform(Role.FACT_OWNER, "approve_asset")  # Fact Owner CANNOT approve assets


def test_permission_enforcement_raises():
    """Verify enforce_permission raises PermissionError on violation."""
    with pytest.raises(PermissionError):
        enforce_permission(Role.CREATOR, "approve_asset")

    with pytest.raises(PermissionError):
        enforce_permission(Role.REVIEWER, "create_fact_version")

    with pytest.raises(PermissionError):
        enforce_permission(Role.FACT_OWNER, "approve_asset")


def test_audit_event_logging_and_retrieval(seeded_db):
    """Verify logging review events and retrieving chronological trail."""
    evt1 = log_review_event(
        asset_id="AST-001",
        actor="Alex Chen",
        role=Role.CREATOR,
        action="submit_for_review",
        comment="Initial draft submitted",
        db_path=seeded_db,
    )
    assert evt1.event_id.startswith("EVT-")

    evt2 = log_review_event(
        asset_id="AST-001",
        actor="Sarah Jenkins",
        role=Role.REVIEWER,
        action="approve",
        comment="Approved copy matches F-112 v3",
        db_path=seeded_db,
    )

    trail = get_asset_audit_trail("AST-001", db_path=seeded_db)
    assert len(trail) == 2
    assert trail[0].action == "submit_for_review"
    assert trail[1].action == "approve"


def test_audit_log_append_only_enforced_by_sqlite_triggers(seeded_db):
    """Verify that UPDATE or DELETE on review_events is blocked by SQL triggers."""
    evt = log_review_event(
        asset_id="AST-001",
        actor="Alex Chen",
        role=Role.CREATOR,
        action="submit_for_review",
        db_path=seeded_db,
    )

    with get_connection(seeded_db) as conn:
        # Test UPDATE violation
        with pytest.raises(sqlite3.DatabaseError) as exc_update:
            conn.execute(
                "UPDATE review_events SET comment = 'tampered' WHERE event_id = ?;",
                (evt.event_id,),
            )
        assert "append-only" in str(exc_update.value).lower()

        # Test DELETE violation
        with pytest.raises(sqlite3.DatabaseError) as exc_delete:
            conn.execute(
                "DELETE FROM review_events WHERE event_id = ?;",
                (evt.event_id,),
            )
        assert "append-only" in str(exc_delete.value).lower()
