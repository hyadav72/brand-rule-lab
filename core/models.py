"""
Brand Rule Lab — Shared Contracts & Data Models
Owned by Agent A0 (Architect & Integrator).

This file defines the immutable contract across all agents (A1-A5).
No agent may modify these contracts without explicit architectural consensus.

Key Architectural Principle:
AI proposes. Python decides. Humans approve.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# ENUMS
# ============================================================================

class Role(str, Enum):
    """System access roles (role picker in MVP)."""
    CREATOR = "creator"
    REVIEWER = "reviewer"
    FACT_OWNER = "fact_owner"


class Channel(str, Enum):
    """Marketing distribution channels."""
    PAID_SOCIAL = "paid_social"
    ORGANIC_SOCIAL = "organic_social"
    EMAIL = "email"
    PDP = "pdp"
    BANNER = "banner"


class Severity(str, Enum):
    """Compliance finding impact severity."""
    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


class FindingKind(str, Enum):
    """Classification of compliance finding."""
    TONE = "tone"
    TERMINOLOGY = "terminology"
    CLAIM = "claim"
    OFFER_DATE = "offer_date"
    VISUAL_TEXT = "visual_text"
    ACCESSIBILITY = "accessibility"


class LinkState(str, Enum):
    """
    Lineage link state.
    UNLINKED claims are never silently assumed compliant.
    """
    LINKED = "LINKED"
    UNLINKED = "UNLINKED"


class DriftStatus(str, Enum):
    """
    Status of an approved claim in the claim ledger.
    CURRENT: Linked fact version is active and valid.
    REVIEW_REQUIRED: Fact updated to a newer version; re-review required.
    EXPIRED: Fact validity window has ended.
    """
    CURRENT = "CURRENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EXPIRED = "EXPIRED"


class AssetStatus(str, Enum):
    """Lifecycle status of an ingested marketing asset."""
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    CHANGES_REQUESTED = "changes_requested"
    ESCALATED = "escalated"
    APPROVED = "approved"


class Decision(str, Enum):
    """Reviewer decision actions."""
    APPROVE = "approve"
    CHANGES = "changes"
    ESCALATE = "escalate"


class CreatorActionState(str, Enum):
    """Creator decision states on suggested findings."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    DISMISSED = "dismissed"


# ============================================================================
# DATACLASSES / ENTITIES
# ============================================================================

@dataclass
class ExtractedDoc:
    """Output of ingestion pipeline."""
    text: str
    pages: List[str] = field(default_factory=list)
    images: List[bytes] = field(default_factory=list)
    ocr_used: bool = False
    source_filename: str = ""
    source_hash: str = ""


@dataclass
class ClaimSpan:
    """Claim span extracted from draft text by LLM/parser."""
    text: str
    start: int
    end: int
    product_alias: Optional[str] = None


@dataclass
class FactVersion:
    """An approved brand fact version stored in the factual database."""
    fact_id: str
    version: int
    product_id: str
    market: str
    fact_text: str
    permitted_wording: str
    valid_from: str  # YYYY-MM-DD
    expires_at: Optional[str] = None  # YYYY-MM-DD or None if perpetual
    owner: str = "brand_science"


@dataclass
class RankedFact:
    """Ranked fact candidate with semantic relevance score."""
    fact: FactVersion
    score: float


@dataclass
class Finding:
    """
    A compliance finding emitted by deterministic rule checks.
    Every finding MUST cite a rule_id or fact_id + version.
    """
    finding_id: str
    asset_id: str
    kind: FindingKind
    severity: Severity
    span_start: int
    span_end: int
    source_text: str
    rule_id: Optional[str] = None
    fact_id: Optional[str] = None
    fact_version_id: Optional[int] = None
    link_state: LinkState = LinkState.UNLINKED
    message: str = ""
    next_step: str = ""
    suggested_rewrite: Optional[str] = None
    creator_action: CreatorActionState = CreatorActionState.PENDING
    dismiss_reason: Optional[str] = None


@dataclass
class ApprovedClaim:
    """A claim officially approved and entered into the immutable ledger."""
    stable_claim_id: str
    asset_id: str
    claim_text: str
    approved_text_hash: str
    fact_id: str
    fact_version_id: int
    drift_status: DriftStatus
    approved_by: str
    approved_at: str
    flagged_at: Optional[str] = None


@dataclass
class ReviewEvent:
    """Append-only audit log entry. Cannot be updated or deleted."""
    event_id: str
    asset_id: str
    actor: str
    role: Role
    action: str
    comment: Optional[str] = None
    override_reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Product:
    """Registered brand product definition."""
    product_id: str
    name: str
    sku_aliases: List[str]
    market: str


@dataclass
class RuleSpec:
    """Declarative JSON rule specification."""
    rule_id: str
    predicate_type: str
    scope: Dict[str, Any]
    parameters: Dict[str, Any]
    positive_test_cases: List[Dict[str, Any]]
    negative_test_cases: List[Dict[str, Any]]
    owner_approved: bool
    version: int


# ============================================================================
# FUNCTION SIGNATURE STUBS (Day 0 stubs; implementation starts Day 1)
# ============================================================================

def ingest(file_bytes: bytes, filename: str) -> ExtractedDoc:
    """Parse PDF, DOCX, TXT, or Image files into ExtractedDoc."""
    raise NotImplementedError("Ingest stub - Day 0 boundary")


def extract_claims(text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
    """Extract factual claim spans with exact offsets from raw draft text."""
    raise NotImplementedError("Extract claims stub - Day 0 boundary")


def lookup_facts(product_id: str, market: str, today: Optional[str] = None) -> List[FactVersion]:
    """Retrieve approved fact candidates for product and market within validity window."""
    raise NotImplementedError("Lookup facts stub - Day 0 boundary")


def rank_facts(claim_text: str, candidates: List[FactVersion]) -> List[RankedFact]:
    """Rank candidate facts against claim text. Never silently truncates."""
    raise NotImplementedError("Rank facts stub - Day 0 boundary")


def run_rules(doc: ExtractedDoc, claims: List[ClaimSpan], context: Dict[str, Any]) -> List[Finding]:
    """Execute deterministic Python rules on text and claims. Never relies on LLM pass/fail."""
    raise NotImplementedError("Run rules stub - Day 0 boundary")


def suggest_rewrite(finding: Finding, fact: Optional[FactVersion] = None) -> str:
    """Generate an intent-preserving rewrite constrained to permitted wording."""
    raise NotImplementedError("Suggest rewrite stub - Day 0 boundary")


def approve_claim(asset_id: str, finding_id: str, reviewer_id: str) -> str:
    """Mint a stable_claim_id, record text hash, and insert into approved_claims."""
    raise NotImplementedError("Approve claim stub - Day 0 boundary")


def cascade_fact_update(fact_id: str, new_version: int) -> int:
    """
    Single SQL update flagging dependent claims as REVIEW_REQUIRED.
    Zero LLM calls, zero web crawls.
    """
    raise NotImplementedError("Cascade fact update stub - Day 0 boundary")


def sweep_expiry(today: str) -> int:
    """
    Single SQL update flagging claims linked to expired facts as EXPIRED.
    """
    raise NotImplementedError("Sweep expiry stub - Day 0 boundary")
