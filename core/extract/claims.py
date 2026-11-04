"""
Brand Rule Lab — Claim Extraction Pipeline
Owned by Agent A3 (LLM & Retrieval Engineer).
"""

from __future__ import annotations
from typing import List, Optional
from core.llm import get_llm_adapter
from core.models import ClaimSpan


def extract_claims(text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
    """
    Extract claim spans with verified offsets from draft text.
    Uses configured LLM adapter (Mock or Live).
    """
    adapter = get_llm_adapter()
    return adapter.extract_claims(text, product_hint)
