"""
Brand Rule Lab — Deterministic Mock LLM Adapter
Owned by Agent A3 (LLM & Retrieval Engineer).

Provides 100% reproducible, offline responses for:
- Testing and CI.
- The official hackathon demo scenario (Monsoon Clear Skin).
- Zero network latency and zero API failures.
"""

from __future__ import annotations
import re
from typing import List, Optional
from core.llm.adapter import LLMAdapter, verify_and_align_offsets
from core.models import ClaimSpan, FactVersion, Finding, RankedFact

DEMO_DRAFT = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."


class MockLLM(LLMAdapter):
    """Deterministic mock adapter implementing canned and heuristic outputs."""

    def extract_claims(self, draft_text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
        """Extract claim spans with verified offsets."""
        claims: List[ClaimSpan] = []

        # Target Hackathon Demo Exact Match
        if DEMO_DRAFT.lower() in draft_text.lower():
            # Span 1: "acne forever"
            start1 = draft_text.find("acne forever")
            if start1 != -1:
                claims.append(ClaimSpan(
                    text="acne forever",
                    start=start1,
                    end=start1 + len("acne forever"),
                    product_alias="Monsoon Clear Skin",
                ))
            # Span 2: "2.5% BPO"
            start2 = draft_text.find("2.5% BPO")
            if start2 != -1:
                claims.append(ClaimSpan(
                    text="2.5% BPO",
                    start=start2,
                    end=start2 + len("2.5% BPO"),
                    product_alias="Monsoon Clear Skin",
                ))
            # Span 3: "clears breakouts in 3 days"
            start3 = draft_text.find("clears breakouts in 3 days")
            if start3 != -1:
                claims.append(ClaimSpan(
                    text="clears breakouts in 3 days",
                    start=start3,
                    end=start3 + len("clears breakouts in 3 days"),
                    product_alias="Monsoon Clear Skin",
                ))
            return verify_and_align_offsets(draft_text, claims)

        # General Heuristic Fallback
        patterns = [
            r"(\b\d+(?:\.\d+)?%\s+[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?)",  # e.g., 2.5% BPO, 10% Vitamin C
            r"(clears?\s+[\w\s]{3,20}\s+in\s+\d+\s+(?:days?|weeks?|hours?))",  # e.g. clears breakouts in 3 days
            r"(reduces?\s+[\w\s]{3,20}\s+in\s+\d+\s+(?:days?|weeks?|hours?))",
            r"(hydrates?\s+[\w\s]{3,20}\s+by\s+\d+%)",
            r"(\b(?:forever|guaranteed|100%|instant|no\.1)\b[\w\s]{0,25})",  # absolute claims
            r"(\b(?:100%\s+organic|chemical\s+free|all\s+natural)\b)",  # unlinked claims
        ]

        found_spans = []
        for pat in patterns:
            for match in re.finditer(pat, draft_text, flags=re.IGNORECASE):
                start, end = match.span()
                matched_text = draft_text[start:end]
                # Avoid overlapping spans
                if not any(s <= start < e or s < end <= e for s, e in found_spans):
                    found_spans.append((start, end))
                    claims.append(ClaimSpan(
                        text=matched_text,
                        start=start,
                        end=end,
                        product_alias=product_hint or "Brand Product",
                    ))

        if not claims and len(draft_text.strip()) > 0:
            # Fallback: treat draft sentence as a claim
            sentence = draft_text.strip().split(".")[0]
            claims.append(ClaimSpan(
                text=sentence,
                start=0,
                end=len(sentence),
                product_alias=product_hint,
            ))

        return verify_and_align_offsets(draft_text, claims)

    def rank_facts(self, claim_text: str, candidate_facts: List[FactVersion]) -> List[RankedFact]:
        """Rank candidate facts by lexical and semantic overlap."""
        if not candidate_facts:
            return []

        ranked: List[RankedFact] = []
        claim_lower = claim_text.lower()
        claim_tokens = set(re.findall(r"\w+", claim_lower))

        for fact in candidate_facts:
            fact_tokens = set(re.findall(r"\w+", fact.fact_text.lower()))
            overlap = len(claim_tokens.intersection(fact_tokens))

            # Prioritize matching topic keywords
            score = overlap / max(len(claim_tokens), 1)

            # Specific boosts for demo facts
            if "breakout" in claim_lower and fact.fact_id == "F-112":
                score += 0.8
            if "bpo" in claim_lower and fact.fact_id == "F-113":
                score += 0.8
            if "radiance" in claim_lower and fact.fact_id == "F-201":
                score += 0.8
            if "hydration" in claim_lower and fact.fact_id == "F-301":
                score += 0.8

            ranked.append(RankedFact(fact=fact, score=round(min(score, 1.0), 4)))

        # Sort descending by score, never truncating candidates
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked

    def suggest_rewrite(self, finding: Finding, fact: Optional[FactVersion] = None) -> str:
        """Propose compliant rewrite using permitted wording or standard substitution."""
        if fact and fact.permitted_wording:
            return fact.permitted_wording

        text = finding.source_text

        # Sentence-level tone rewrite for demo case / absolute acne elimination claims
        if re.search(r"\bsay goodbye to acne\b", text, flags=re.IGNORECASE):
            return "Gentle daily wash for clearer-looking skin!"

        # Terminology substitution
        text = re.sub(r"\bBPO\b", "Benzoyl Peroxide", text, flags=re.IGNORECASE)
        # Tone substitution
        text = re.sub(r"\bforever\b", "with regular daily use", text, flags=re.IGNORECASE)
        text = re.sub(r"\bguaranteed\b", "trusted care", text, flags=re.IGNORECASE)
        text = re.sub(r"\binstant\b", "fast-acting", text, flags=re.IGNORECASE)
        text = re.sub(r"\bclears breakouts in 3 days\b", "reduces breakouts in 4 weeks with twice-daily use", text, flags=re.IGNORECASE)

        return text
