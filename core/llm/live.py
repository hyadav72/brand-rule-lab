"""
Brand Rule Lab — Production Live LLM Adapter (Google Gemini)
Owned by Agent A3 (LLM & Retrieval Engineer).

Integrates Google Gemini REST API with:
- Three-Prompt LLM Pipeline:
  1. Claim-span extraction with exact character offsets.
  2. Complete candidate-fact set ranking without silent truncation.
  3. Intent-preserving rewrite generation constrained to permitted_wording.
- Strict Prompt-Injection Sandboxing (<draft_text>, <claim_text>, <candidate_facts>).
- Strict JSON Schema Validation and single-retry recovery.
- Transparent Fallback to MockLLM on network/auth failure with visible UI telemetry.
- Zero authority over compliance verdicts; zero database write access.
"""

from __future__ import annotations
import json
import logging
import os
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import requests
from dotenv import load_dotenv

from core.llm.adapter import LLMAdapter, verify_and_align_offsets
from core.llm.mock import MockLLM
from core.llm.prompts import (
    build_extraction_prompt,
    build_ranking_prompt,
    build_rewrite_prompt,
    validate_extraction_schema,
    validate_ranking_schema,
    validate_rewrite_schema,
)
from core.models import ClaimSpan, FactVersion, Finding, LinkState, RankedFact

load_dotenv()
logger = logging.getLogger(__name__)


def _strip_markdown_json(text: str) -> str:
    """Strip markdown code fence blocks if returned by the LLM."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    return clean.strip()


class LiveLLM(LLMAdapter):
    """Production LLM adapter with adversarial defenses, schema enforcement, and telemetry."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        # Support LLM_API_KEY, GEMINI_API_KEY, or GOOGLE_API_KEY
        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
        self.model = (model or os.getenv("LLM_MODEL") or "gemini-3.8-flash").strip()
        self.mock_fallback = MockLLM()

        # Timeout configuration (separate connect and read timeouts)
        try:
            self.connect_timeout: float = float(os.getenv("LLM_CONNECT_TIMEOUT", "5.0"))
        except (ValueError, TypeError):
            self.connect_timeout = 5.0

        try:
            self.read_timeout: float = float(os.getenv("LLM_READ_TIMEOUT", "60.0"))
        except (ValueError, TypeError):
            self.read_timeout = 60.0

        self.timeout: Tuple[float, float] = (self.connect_timeout, self.read_timeout)

        # Telemetry & Status
        self.call_count: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.fallback_active: bool = False
        self.last_fallback_reason: Optional[str] = None

        # Truthful provider validation
        if self.provider != "gemini":
            self.fallback_active = True
            self.last_fallback_reason = (
                f"Configured LLM_PROVIDER '{self.provider}' is not supported; "
                "only 'gemini' is supported as the live provider."
            )
            logger.warning(self.last_fallback_reason)

    def get_telemetry(self) -> Dict[str, Any]:
        """Return live telemetry metrics."""
        return {
            "call_count": self.call_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "fallback_active": self.fallback_active,
            "last_fallback_reason": self.last_fallback_reason,
        }

    def _call_gemini(self, prompt: str, retry_on_transient: bool = True) -> Optional[str]:
        """
        Execute raw HTTP request to Gemini REST API with bounded retries, exponential backoff,
        read-timeout protection, and token accounting.
        Redacts API credentials from all logs.
        """
        if self.provider != "gemini":
            self.fallback_active = True
            self.last_fallback_reason = (
                f"Configured LLM_PROVIDER '{self.provider}' is not supported; "
                "only 'gemini' is supported."
            )
            return None

        if not self.api_key or self.api_key == "your_api_key_here":
            self.fallback_active = True
            self.last_fallback_reason = "No valid LLM_API_KEY / GEMINI_API_KEY configured."
            logger.info("No valid LLM_API_KEY provided; engaging MockLLM fallback.")
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }

        max_attempts = 3 if retry_on_transient else 1
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usageMetadata", {})
                    p_tokens = usage.get("promptTokenCount", 0)
                    c_tokens = usage.get("candidatesTokenCount", 0)
                    self.total_prompt_tokens += p_tokens
                    self.total_completion_tokens += c_tokens
                    self.call_count += 1

                    # Gemini Flash estimated cost: $0.075 / 1M prompt, $0.30 / 1M output
                    call_cost = (p_tokens * 0.075 / 1_000_000) + (c_tokens * 0.30 / 1_000_000)
                    self.total_cost_usd += call_cost

                    logger.info(
                        f"LiveLLM Gemini call #{self.call_count} success | Tokens: {p_tokens} prompt, {c_tokens} completion | "
                        f"Est. cost: ${call_cost:.6f} | Cumulative: ${self.total_cost_usd:.6f}"
                    )
                    self.fallback_active = False
                    self.last_fallback_reason = None
                    return data["candidates"][0]["content"]["parts"][0]["text"]

                # Retryable HTTP status codes (rate limits or server errors)
                if resp.status_code in (429, 500, 503):
                    if attempt < max_attempts:
                        # Respect Retry-After header if provided
                        delay = None
                        headers = getattr(resp, "headers", {}) or {}
                        retry_after_str = headers.get("Retry-After")
                        if retry_after_str:
                            try:
                                parsed_delay = float(retry_after_str.strip())
                                delay = min(max(0.0, parsed_delay), 30.0)
                            except (ValueError, TypeError):
                                delay = None

                        if delay is None:
                            # Exponential backoff with jitter: 1s, 2s + jitter
                            delay = min(10.0, (1.0 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5))

                        logger.warning(
                            f"Live LLM API HTTP {resp.status_code} on attempt {attempt}/{max_attempts}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        continue

                    # Retries exhausted for retryable error
                    self.fallback_active = True
                    self.last_fallback_reason = (
                        f"Gemini API HTTP error {resp.status_code} on model {self.model} after {max_attempts} attempts"
                    )
                    logger.warning(
                        f"Live LLM API HTTP error {resp.status_code} (model: {self.model}) after {max_attempts} attempts; "
                        "engaging MockLLM fallback."
                    )
                    return None

                # Non-retryable HTTP status code (e.g. 400, 401, 403, 404)
                self.fallback_active = True
                self.last_fallback_reason = f"Gemini API HTTP error {resp.status_code} on model {self.model}"
                logger.warning(f"Live LLM API non-retryable HTTP error {resp.status_code} (model: {self.model})")
                return None

            except requests.exceptions.ReadTimeout as e:
                # Do NOT automatically retry ReadTimeout: the server may have processed
                # the request and retrying risks duplicate generation/cost.
                clean_err = re.sub(r"key=[^\s&'\"]+", "key=[REDACTED]", str(e))
                self.fallback_active = True
                self.last_fallback_reason = (
                    f"Gemini API read timed out (no automatic retry to avoid duplicate generation): {clean_err}"
                )
                logger.warning(
                    f"Live LLM read timed out ({clean_err}); engaging MockLLM fallback without retry."
                )
                return None

            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
                # Connection failures may be retried where safe
                if attempt < max_attempts:
                    delay = min(5.0, (0.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25))
                    logger.warning(
                        f"Live LLM connection error on attempt {attempt}/{max_attempts}: {type(e).__name__}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    continue

                clean_err = re.sub(r"key=[^\s&'\"]+", "key=[REDACTED]", str(e))
                self.fallback_active = True
                self.last_fallback_reason = (
                    f"Gemini API connection failed after {max_attempts} attempts: {type(e).__name__}: {clean_err}"
                )
                logger.warning(
                    f"Live LLM connection failed after {max_attempts} attempts ({type(e).__name__}: {clean_err}); "
                    "engaging MockLLM fallback."
                )
                return None

            except Exception as e:
                # Other unexpected exceptions: do not retry indefinitely
                clean_err = re.sub(r"key=[^\s&'\"]+", "key=[REDACTED]", str(e))
                self.fallback_active = True
                self.last_fallback_reason = f"Gemini API request failed: {type(e).__name__}: {clean_err}"
                logger.warning(f"Live LLM request failed ({type(e).__name__}: {clean_err}); engaging MockLLM fallback.")
                return None

        return None

    def _call_gemini_json_with_retry(
        self,
        prompt: str,
        validator_fn: Callable[[Any], Tuple[bool, Any, str]],
    ) -> Tuple[Optional[Any], bool]:
        """
        Execute Gemini call, parse JSON, validate against schema, and execute single-retry recovery if invalid.
        Returns: (validated_data_or_none, live_attempted_bool)
        """
        raw_text = self._call_gemini(prompt)
        if raw_text is None:
            return None, False

        # Attempt 1: Parse and validate
        try:
            clean_text = _strip_markdown_json(raw_text)
            parsed_json = json.loads(clean_text)
            is_valid, validated_data, err_msg = validator_fn(parsed_json)
            if is_valid:
                return validated_data, True
        except Exception as e:
            err_msg = str(e)

        logger.warning(f"Live LLM JSON schema validation failed: {err_msg}. Executing single-retry recovery...")

        # Attempt 2: Corrective single-retry
        corrective_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL RETRY INSTRUCTION:\n"
            f"Your previous output failed schema validation: {err_msg}\n"
            f"Return ONLY valid raw JSON conforming strictly to the requested schema. No code fences, no extra text."
        )

        retry_text = self._call_gemini(corrective_prompt, retry_on_transient=False)
        if retry_text is None:
            return None, True

        try:
            clean_retry = _strip_markdown_json(retry_text)
            parsed_retry = json.loads(clean_retry)
            is_valid, validated_data, err_msg = validator_fn(parsed_retry)
            if is_valid:
                return validated_data, True
            logger.error(f"Live LLM single-retry validation failed: {err_msg}.")
            return None, True
        except Exception as e:
            logger.error(f"Live LLM single-retry JSON parse error: {e}.")
            return None, True

    # ========================================================================
    # 1. Claim-Span Extraction
    # ========================================================================

    def extract_claims_live(self, draft_text: str, product_hint: Optional[str] = None) -> Optional[List[ClaimSpan]]:
        """Attempt live extraction without automatic MockLLM fallback."""
        prompt = build_extraction_prompt(draft_text, product_hint)
        validated_items, live_attempted = self._call_gemini_json_with_retry(
            prompt,
            validate_extraction_schema,
        )

        if not validated_items:
            return None

        claims = [
            ClaimSpan(
                text=item["text"],
                start=item["start"],
                end=item["end"],
                product_alias=item.get("product_alias", product_hint),
            )
            for item in validated_items
        ]

        verified = verify_and_align_offsets(draft_text, claims)
        if not verified:
            return None

        return verified

    def extract_claims(self, draft_text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
        """
        Extract factual claim spans with exact character offsets from draft text.
        Employs adversarial sandboxing and schema enforcement with mock fallback.
        """
        res = self.extract_claims_live(draft_text, product_hint)
        if res is not None:
            return res
        logger.info("Engaging MockLLM for claim extraction fallback.")
        return self.mock_fallback.extract_claims(draft_text, product_hint)

    # ========================================================================
    # 2. Complete Candidate-Fact Set Ranking
    # ========================================================================

    def rank_facts_live(self, claim_text: str, candidate_facts: List[FactVersion]) -> Optional[List[RankedFact]]:
        """Attempt live candidate fact ranking without automatic MockLLM fallback."""
        if not candidate_facts:
            return []

        allowed_keys: Set[Tuple[str, int]] = {(f.fact_id, f.version) for f in candidate_facts}
        facts_map: Dict[Tuple[str, int], FactVersion] = {(f.fact_id, f.version): f for f in candidate_facts}

        # Handle large candidate sets through pagination to stay within context limits
        max_batch_size = 20
        all_ranked_items: List[Dict[str, Any]] = []

        batches = [
            candidate_facts[i : i + max_batch_size]
            for i in range(0, len(candidate_facts), max_batch_size)
        ]

        for batch in batches:
            prompt = build_ranking_prompt(claim_text, batch)
            batch_keys = {(f.fact_id, f.version) for f in batch}

            validated_batch, live_attempted = self._call_gemini_json_with_retry(
                prompt,
                lambda data: validate_ranking_schema(data, batch_keys),
            )

            if validated_batch is None:
                return None

            all_ranked_items.extend(validated_batch)

        # Ensure NO SILENT TRUNCATION: any candidate in candidate_facts that was not ranked by the model
        # is preserved with score = 0.0 at the end of the ranking list
        ranked_keys = {(item["fact_id"], item["version"]) for item in all_ranked_items}
        for f in candidate_facts:
            key = (f.fact_id, f.version)
            if key not in ranked_keys:
                all_ranked_items.append({
                    "fact_id": f.fact_id,
                    "version": f.version,
                    "score": 0.0,
                    "rationale": "Retained candidate: unranked by model",
                })

        # Sort descending by score
        all_ranked_items.sort(key=lambda x: x["score"], reverse=True)

        return [
            RankedFact(
                fact=facts_map[(item["fact_id"], item["version"])],
                score=round(item["score"], 4),
            )
            for item in all_ranked_items
            if (item["fact_id"], item["version"]) in facts_map
        ]

    def rank_facts(self, claim_text: str, candidate_facts: List[FactVersion]) -> List[RankedFact]:
        """
        Rank the complete eligible candidate set against extracted claim text.
        Never silently truncates candidate facts. Validates that every returned fact ID/version
        belongs to the candidate set and assigns zero-score to any unranked candidates.
        """
        ranked = self.rank_facts_live(claim_text, candidate_facts)
        if ranked is not None:
            return ranked
        logger.info("Engaging MockLLM for candidate fact ranking fallback.")
        return self.mock_fallback.rank_facts(claim_text, candidate_facts)

    # ========================================================================
    # 3. Intent-Preserving Rewrite Generation
    # ========================================================================

    def suggest_rewrite_live(self, finding: Finding, fact: Optional[FactVersion] = None) -> Optional[str]:
        """Attempt live rewrite generation without automatic MockLLM fallback."""
        prompt = build_rewrite_prompt(finding, fact)
        validated_rewrite, live_attempted = self._call_gemini_json_with_retry(
            prompt,
            validate_rewrite_schema,
        )
        return validated_rewrite

    def suggest_rewrite(self, finding: Finding, fact: Optional[FactVersion] = None) -> str:
        """
        Generate intent-preserving rewrite constrained to permitted_wording.
        If live call fails, falls back to MockLLM. If output remains invalid after single retry,
        safely marks the finding UNLINKED with note 'model output invalid - manual review required'.
        """
        prompt = build_rewrite_prompt(finding, fact)

        validated_rewrite, live_attempted = self._call_gemini_json_with_retry(
            prompt,
            validate_rewrite_schema,
        )

        if validated_rewrite is not None:
            # Valid rewrite generated by live LLM
            return validated_rewrite

        # If live mode was attempted but schema was invalid after single retry:
        if live_attempted:
            logger.warning(
                f"Live LLM rewrite output invalid for finding {finding.finding_id}; "
                "marking UNLINKED with 'model output invalid' note."
            )
            finding.link_state = LinkState.UNLINKED
            if "model output invalid" not in finding.message:
                finding.message = f"{finding.message} [model output invalid - manual review required]".strip()
            finding.next_step = "Manual review required: Model output failed schema validation."
            # Fall back to deterministic template if permitted_wording or standard substitution exists
            return self.mock_fallback.suggest_rewrite(finding, fact)

        # Fallback to MockLLM when live API is unavailable or unconfigured
        return self.mock_fallback.suggest_rewrite(finding, fact)
