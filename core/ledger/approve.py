"""
Brand Rule Lab — Claim Approval and Stable ID Minting
Owned by Agent A1 (Backend & Data Engineer).

Implements the official approval contract:
1. Normalizes approved claim text (NFC, collapse whitespace, trim).
2. Generates SHA-256 approved_text_hash.
3. Mints stable_claim_id as 'SC-' + first 4 hex characters of SHA-256 over:
   f"{asset_id}:{normalised_text}:{fact_version_id}", extending on collision.
4. Registers claim into approved_claims ledger linked to fact_id and fact_version_id.
"""

from __future__ import annotations
import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Optional, Tuple
from core.audit import log_review_event
from core.db import execute_commit, execute_query, get_connection
from core.models import DriftStatus, Role


def normalize_claim_text(text: str) -> str:
    """Normalize text per specification: Unicode NFC, trim, collapse whitespace."""
    nfc_text = unicodedata.normalize("NFC", text.strip())
    return re.sub(r"\s+", " ", nfc_text)


def compute_approved_text_hash(normalized_text: str) -> str:
    """Compute SHA-256 hash over normalized text."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def mint_stable_claim_id(
    asset_id: str,
    normalized_text: str,
    fact_version_id: int,
    db_path: Optional[str] = None,
) -> str:
    """
    Generate stable_claim_id as SC- + first 4 hex characters of SHA-256 over
    asset_id, normalised claim text and fact_version_id, extended on collision.
    """
    hash_input = f"{asset_id}:{normalized_text}:{fact_version_id}".encode("utf-8")
    full_hex = hashlib.sha256(hash_input).hexdigest()

    # Try 4 chars, then 6, then 8 on collision
    for length in (4, 6, 8, 12):
        candidate_id = f"SC-{full_hex[:length]}"
        existing = execute_query(
            "SELECT stable_claim_id FROM approved_claims WHERE stable_claim_id = ?;",
            (candidate_id,),
            db_path=db_path,
        )
        if not existing:
            return candidate_id

    return f"SC-{full_hex[:16]}"


def approve_claim(
    asset_id: str,
    claim_text: str,
    fact_id: str,
    fact_version_id: int,
    reviewer_id: str = "Sarah Jenkins (Reviewer)",
    db_path: Optional[str] = None,
) -> str:
    """
    Formally approve claim and register into the immutable ledger.
    Returns minted stable_claim_id.
    """
    normalized = normalize_claim_text(claim_text)
    text_hash = compute_approved_text_hash(normalized)
    stable_id = mint_stable_claim_id(asset_id, normalized, fact_version_id, db_path=db_path)
    now_ts = datetime.utcnow().isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO approved_claims (
                stable_claim_id, asset_id, claim_text, approved_text_hash,
                fact_id, fact_version_id, drift_status, approved_by, approved_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'CURRENT', ?, ?);
            """,
            (stable_id, asset_id, normalized, text_hash, fact_id, fact_version_id, reviewer_id, now_ts),
        )
        # Update asset status to approved
        conn.execute(
            "UPDATE assets SET status = 'approved' WHERE asset_id = ?;",
            (asset_id,),
        )

    # Log to append-only audit trail
    log_review_event(
        asset_id=asset_id,
        actor=reviewer_id,
        role=Role.REVIEWER,
        action="approve",
        comment=f"Minted {stable_id} linked to {fact_id} v{fact_version_id}",
        db_path=db_path,
    )

    return stable_id
