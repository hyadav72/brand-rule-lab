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

NOTE ON DEMO PERSONA SIMULATION:
In this Hackathon MVP, the UI persona switcher simulates role-based authorization boundaries
to prove deterministic governance and least-privilege separation without deploying heavy enterprise SSO.
It is an auditable demonstration harness, not cryptographic production authentication.
All privileged operations strictly require an explicit role and reject missing/None roles.
"""

from __future__ import annotations
from typing import Set
from core.models import Role

ROLE_PERMISSIONS: dict[Role, Set[str]] = {
    Role.CREATOR: {
        "upload_draft",
        "analyze_draft",
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
        "publish_fact",
        "trigger_drift_cascade",
        "sweep_expiry",
        "resolve_escalation",
    },
}


def can_perform(role: Role | str | None, action: str) -> bool:
    """Check if given role has authority for requested action. A missing role (None) never has authority."""
    if role is None:
        return False
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    return action in ROLE_PERMISSIONS.get(role, set())


def enforce_permission(role: Role | str | None, action: str) -> None:
    """
    Raise PermissionError if role lacks permission for action or if role is missing.
    A missing role must never implicitly grant permissions.
    """
    if role is None:
        raise PermissionError(f"Action '{action}' requires an explicit role; no role was provided (role cannot be None).")
    if not can_perform(role, action):
        role_name = role.value if isinstance(role, Role) else str(role)
        raise PermissionError(f"Role '{role_name}' is not permitted to execute action '{action}'.")
