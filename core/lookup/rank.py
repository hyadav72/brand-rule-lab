"""
Brand Rule Lab — Fact Candidate Ranking
Owned by Agent A3 (LLM & Retrieval Engineer).

Ranks fact candidates against extracted claim text.
Non-Negotiable Rule 6: No silent truncation.
"""

from __future__ import annotations
from typing import List
from core.llm import get_llm_adapter
from core.models import FactVersion, RankedFact


def rank_facts(claim_text: str, candidates: List[FactVersion]) -> List[RankedFact]:
    """Rank all eligible candidate facts without silent truncation."""
    if not candidates:
        return []
    adapter = get_llm_adapter()
    return adapter.rank_facts(claim_text, candidates)
