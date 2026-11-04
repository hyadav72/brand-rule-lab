"""
Brand Rule Lab — LLM Adapter Interface
Owned by Agent A3 (LLM & Retrieval Engineer).

Defines the contract for LLM operations:
1. Claim-span extraction returning exact offsets and product alias.
2. Fact ranking over candidate fact versions.
3. Intent-preserving rewrite constrained to permitted wording.

Adheres to Non-Negotiable Rule 1:
AI proposes. Python decides. Humans approve.
LLM NEVER emits pass/fail verdicts or approves content.
"""

from __future__ import annotations
import abc
import logging
from typing import List, Optional
from core.models import ClaimSpan, FactVersion, Finding, RankedFact

logger = logging.getLogger(__name__)


class LLMAdapter(abc.ABC):
    """Abstract interface for LLM claim extraction, ranking, and rewrite generation."""

    @abc.abstractmethod
    def extract_claims(self, draft_text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
        """Extract factual claim spans with exact character offsets from draft text."""
        pass

    @abc.abstractmethod
    def rank_facts(self, claim_text: str, candidate_facts: List[FactVersion]) -> List[RankedFact]:
        """Rank candidate facts against claim text. Never silently truncates candidates."""
        pass

    @abc.abstractmethod
    def suggest_rewrite(self, finding: Finding, fact: Optional[FactVersion] = None) -> str:
        """Generate an intent-preserving rewrite compliant with permitted wording."""
        pass


def verify_and_align_offsets(source_text: str, raw_claims: List[ClaimSpan]) -> List[ClaimSpan]:
    """
    Validate that span offsets strictly match the source text.
    If offsets are misaligned but the exact text exists, realign offsets.
    If the text cannot be located in the source text, discard and log.
    """
    verified: List[ClaimSpan] = []
    for c in raw_claims:
        target_text = c.text.strip()
        if not target_text:
            continue

        # Check if declared offsets match directly
        if 0 <= c.start < len(source_text) and c.end <= len(source_text):
            if source_text[c.start:c.end] == c.text:
                verified.append(c)
                continue

        # Re-alignment search for exact substring
        idx = source_text.find(c.text)
        if idx != -1:
            verified.append(ClaimSpan(
                text=c.text,
                start=idx,
                end=idx + len(c.text),
                product_alias=c.product_alias,
            ))
        else:
            logger.warning(
                f"Discarding claim span '{c.text}': text not found in source draft."
            )

    return verified
