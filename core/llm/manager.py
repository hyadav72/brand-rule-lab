"""
Brand Rule Lab — Unified Dual-Provider LLM Manager
Owned by Agent A3 (LLM & Retrieval Engineer).

Orchestrates multi-provider AI architecture across:
- Google Gemini (Primary by default, gemini-3.1-flash-lite)
- NVIDIA NIM (Secondary by default, OpenAI-compatible REST API)
- Deterministic Mock (Guaranteed offline fallback)

Architecture guarantees:
1. Fallback chain: Primary -> Secondary -> Deterministic Mock.
2. Zero duplicate parallel API calls: Secondary is only invoked if Primary fails.
3. Bounded retries: ReadTimeout does not retry; transient errors cap at 3 attempts.
4. Identical contracts: Both providers execute identical JSON schema validations,
   exact character offset alignments, and hallucination rejection.
5. Zero compliance authority: Python RuleEngine remains the sole arbiter of verdicts.
6. Zero database write permissions.
"""

from __future__ import annotations
import enum
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from core.llm.adapter import LLMAdapter
from core.llm.live import LiveLLM
from core.llm.mock import MockLLM
from core.llm.nvidia import NvidiaLLM
from core.models import ClaimSpan, FactVersion, Finding, RankedFact

logger = logging.getLogger(__name__)


class ProviderType(str, enum.Enum):
    GEMINI = "gemini"
    NVIDIA = "nvidia"
    MOCK = "mock"


class ProviderManager(LLMAdapter):
    """
    Unified Dual-Provider Manager with configurable primary provider,
    strict sequential fallback ordering, and zero duplicate parallel calls.
    """

    def __init__(
        self,
        primary: Optional[str] = None,
        secondary: Optional[str] = None,
        fallback: Optional[str] = None,
        gemini_adapter: Optional[LiveLLM] = None,
        nvidia_adapter: Optional[NvidiaLLM] = None,
        mock_adapter: Optional[MockLLM] = None,
    ):
        self.primary_name: str = (
            primary
            or os.getenv("LLM_PRIMARY_PROVIDER")
            or os.getenv("LLM_PROVIDER")
            or "gemini"
        ).lower().strip()

        self.secondary_name: str = (
            secondary
            or os.getenv("LLM_SECONDARY_PROVIDER")
            or "nvidia"
        ).lower().strip()

        self.fallback_name: str = (
            fallback
            or os.getenv("LLM_FALLBACK_PROVIDER")
            or "mock"
        ).lower().strip()

        # Initialize provider adapters
        gemini_model = (
            os.getenv("GEMINI_MODEL")
            or os.getenv("LLM_MODEL")
            or "gemini-3.1-flash-lite"
        )
        self.gemini_adapter: LiveLLM = gemini_adapter or LiveLLM(model=gemini_model)
        self.nvidia_adapter: NvidiaLLM = nvidia_adapter or NvidiaLLM()
        self.mock_adapter: MockLLM = mock_adapter or MockLLM()

        # Telemetry & State
        self.active_provider: str = self.primary_name
        self.fallback_events: List[Dict[str, Any]] = []
        self.total_orchestrated_calls: int = 0

    def _get_adapter_by_name(self, name: str) -> Optional[LLMAdapter]:
        name_lower = name.lower().strip()
        if name_lower == "gemini":
            return self.gemini_adapter
        elif name_lower == "nvidia":
            return self.nvidia_adapter
        elif name_lower == "mock":
            return self.mock_adapter
        return None

    def _get_execution_chain(self) -> List[str]:
        """Return ordered list of unique providers to try sequentially."""
        raw_chain = [self.primary_name, self.secondary_name, self.fallback_name]
        seen = set()
        ordered = []
        for p in raw_chain:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    def _record_fallback(self, from_p: str, to_p: str, operation: str, reason: str):
        event = {
            "from_provider": from_p,
            "to_provider": to_p,
            "operation": operation,
            "reason": str(reason),
        }
        self.fallback_events.append(event)
        logger.warning(
            f"DualProvider fallback: {from_p} -> {to_p} during {operation}. Reason: {reason}"
        )

    # ========================================================================
    # 1. Claim-Span Extraction
    # ========================================================================

    def extract_claims(self, draft_text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
        """
        Extract claim spans using Primary -> Secondary -> Mock fallback.
        Zero duplicate parallel calls: Secondary is only invoked if Primary fails.
        """
        self.total_orchestrated_calls += 1
        chain = self._get_execution_chain()

        for idx, provider_name in enumerate(chain):
            adapter = self._get_adapter_by_name(provider_name)
            if adapter is None:
                continue

            if provider_name == "mock":
                self.active_provider = "mock"
                return self.mock_adapter.extract_claims(draft_text, product_hint)

            try:
                # Attempt live extraction without internal mock fallback
                if hasattr(adapter, "extract_claims_live"):
                    res = adapter.extract_claims_live(draft_text, product_hint)
                else:
                    res = adapter.extract_claims(draft_text, product_hint)

                if res is not None:
                    self.active_provider = provider_name
                    return res

                # Primary / Secondary returned None; record fallback
                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                reason = getattr(adapter, "last_fallback_reason", None) or "Live call returned no results"
                self._record_fallback(provider_name, next_p, "extract_claims", reason)

            except Exception as e:
                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                self._record_fallback(provider_name, next_p, "extract_claims", str(e))

        # Final guarantee: deterministic mock
        self.active_provider = "mock"
        return self.mock_adapter.extract_claims(draft_text, product_hint)

    # ========================================================================
    # 2. Complete Candidate-Fact Set Ranking
    # ========================================================================

    def rank_facts(self, claim_text: str, candidate_facts: List[FactVersion]) -> List[RankedFact]:
        """
        Rank candidate facts using Primary -> Secondary -> Mock fallback.
        Strict anti-hallucination and anti-truncation preservation.
        """
        if not candidate_facts:
            return []

        self.total_orchestrated_calls += 1
        chain = self._get_execution_chain()

        for idx, provider_name in enumerate(chain):
            adapter = self._get_adapter_by_name(provider_name)
            if adapter is None:
                continue

            if provider_name == "mock":
                self.active_provider = "mock"
                return self.mock_adapter.rank_facts(claim_text, candidate_facts)

            try:
                if hasattr(adapter, "rank_facts_live"):
                    res = adapter.rank_facts_live(claim_text, candidate_facts)
                else:
                    res = adapter.rank_facts(claim_text, candidate_facts)

                if res is not None:
                    self.active_provider = provider_name
                    return res

                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                reason = getattr(adapter, "last_fallback_reason", None) or "Live ranking returned no results"
                self._record_fallback(provider_name, next_p, "rank_facts", reason)

            except Exception as e:
                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                self._record_fallback(provider_name, next_p, "rank_facts", str(e))

        self.active_provider = "mock"
        return self.mock_adapter.rank_facts(claim_text, candidate_facts)

    # ========================================================================
    # 3. Intent-Preserving Rewrite Generation
    # ========================================================================

    def suggest_rewrite(self, finding: Finding, fact: Optional[FactVersion] = None) -> str:
        """
        Suggest rewrite using Primary -> Secondary -> Mock fallback.
        Zero duplicate parallel calls.
        """
        self.total_orchestrated_calls += 1
        chain = self._get_execution_chain()

        for idx, provider_name in enumerate(chain):
            adapter = self._get_adapter_by_name(provider_name)
            if adapter is None:
                continue

            if provider_name == "mock":
                self.active_provider = "mock"
                return self.mock_adapter.suggest_rewrite(finding, fact)

            try:
                if hasattr(adapter, "suggest_rewrite_live"):
                    res = adapter.suggest_rewrite_live(finding, fact)
                else:
                    res = adapter.suggest_rewrite(finding, fact)

                if res is not None:
                    self.active_provider = provider_name
                    return res

                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                reason = getattr(adapter, "last_fallback_reason", None) or "Live rewrite returned no results"
                self._record_fallback(provider_name, next_p, "suggest_rewrite", reason)

            except Exception as e:
                next_p = chain[idx + 1] if idx + 1 < len(chain) else "none"
                self._record_fallback(provider_name, next_p, "suggest_rewrite", str(e))

        self.active_provider = "mock"
        return self.mock_adapter.suggest_rewrite(finding, fact)

    # ========================================================================
    # Status & Telemetry
    # ========================================================================

    def get_telemetry(self) -> Dict[str, Any]:
        """Aggregate telemetry across all providers and orchestration state."""
        return {
            "orchestrated_calls": self.total_orchestrated_calls,
            "primary": self.primary_name,
            "secondary": self.secondary_name,
            "fallback": self.fallback_name,
            "active_provider": self.active_provider,
            "fallback_events": self.fallback_events,
            "providers": {
                "gemini": self.gemini_adapter.get_telemetry(),
                "nvidia": self.nvidia_adapter.get_telemetry(),
                "mock": {"call_count": getattr(self.mock_adapter, "call_count", 0)},
            },
        }

    def get_status(self) -> Dict[str, Any]:
        """Provide detailed runtime status for UI and monitoring."""
        active_adapter = self._get_adapter_by_name(self.active_provider)
        active_model = getattr(active_adapter, "model", "deterministic-mock")
        fallback_active = (self.active_provider != self.primary_name)

        fallback_reason = None
        if fallback_active and self.fallback_events:
            fallback_reason = self.fallback_events[-1].get("reason")
        elif fallback_active:
            primary_adapter = self._get_adapter_by_name(self.primary_name)
            fallback_reason = getattr(primary_adapter, "last_fallback_reason", None)

        mode = "mock" if self.primary_name == "mock" else "live"

        return {
            "mode": mode,
            "provider": f"{self.primary_name} -> {self.secondary_name} -> {self.fallback_name}",
            "primary_provider": self.primary_name,
            "secondary_provider": self.secondary_name,
            "fallback_provider": self.fallback_name,
            "active_provider": self.active_provider,
            "model": active_model,
            "fallback_active": fallback_active,
            "fallback_reason": fallback_reason,
            "telemetry": self.get_telemetry(),
        }
