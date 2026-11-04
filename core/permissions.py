"""
Brand Rule Lab — Role-Based Access Control (RBAC)
Owned by Agent A1 (Backend & Data Engineer).

Enforces role permissions across system actions:
- Creator: Ingests drafts, accepts/edits/dismisses findings, submits for review.
  CANNOT approve assets, edit facts, or resolve escalations.
- Reviewer: Approves, requests changes, escalates to fact owner, logs overrides.
  CANNOT edit brand facts or publish unapproved claims.
- Fact Owner: Creates/updates fact versions, runs drift propagation, resolves escalations.
  CANNOT approve marketing assets.
"""

from __future__ import annotations
from typing import Set
from core.models import Role

ROLE_PERMISSIONS: dict[Role, Set[str]] = {
    Role.CREATOR: {
        "upload_draft",
        "accept_finding",
        "edit_finding",
        "dismiss_finding",
        "submit_for_review",
    },
    Role.REVIEWER: {
        "view_queue",
        "approve_asset",
        "request_changes",
        "escalate_finding",
        "override_unlinked_claim",
    },
    Role.FACT_OWNER: {
        "view_facts",
        "create_fact_version",
        "trigger_drift_cascade",
        "sweep_expiry",
        "resolve_escalation",
    },
}


def can_perform(role: Role | str, action: str) -> bool:
    """Check if given role has authority for requested action."""
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    return action in ROLE_PERMISSIONS.get(role, set())


def enforce_permission(role: Role | str, action: str) -> None:
    """Raise PermissionError if role lacks permission for action."""
    if not can_perform(role, action):
        role_name = role.value if isinstance(role, Role) else role
        raise PermissionError(f"Role '{role_name}' is not permitted to execute action '{action}'.")
