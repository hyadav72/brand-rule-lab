"""
Brand Rule Lab — Production Live LLM Adapter (NVIDIA NIM)
Owned by Agent A3 (LLM & Retrieval Engineer).

Integrates NVIDIA NIM OpenAI-Compatible REST API with:
- Three-Prompt LLM Pipeline:
  1. Claim-span extraction with exact character offsets.
  2. Complete candidate-fact set ranking without silent truncation.
  3. Intent-preserving rewrite generation constrained to permitted_wording.
- Strict Prompt-Injection Sandboxing (<draft_text>, <claim_text>, <candidate_facts>).
- Strict JSON Schema Validation and single-retry recovery.
- Transparent Fallback to MockLLM on network/auth failure with visible telemetry.
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


class NvidiaLLM(LLMAdapter):
    """NVIDIA NIM LLM adapter using OpenAI-compatible chat completions API."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fallback_adapter: Optional[LLMAdapter] = None,
    ):
        # Support NVIDIA_API_KEY or LLM_NVIDIA_API_KEY
        self.api_key = (
            api_key
            or os.getenv("NVIDIA_API_KEY")
            or os.getenv("LLM_NVIDIA_API_KEY")
            or ""
        ).strip()
        self.provider = "nvidia"
        self.model = (
            model
            or os.getenv("NVIDIA_MODEL")
            or "mistralai/mistral-7b-instruct-v0.3"
        ).strip()
        self.base_url = (
            base_url
            or os.getenv("NVIDIA_BASE_URL")
            or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")

        self.mock_fallback = fallback_adapter or MockLLM()

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
        self.verified_live: bool = False

        if not self.api_key:
            self.fallback_active = True
            self.last_fallback_reason = "No valid NVIDIA_API_KEY configured."

    def get_telemetry(self) -> Dict[str, Any]:
        """Return live telemetry metrics."""
        return {
            "call_count": self.call_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "fallback_active": self.fallback_active,
            "last_fallback_reason": self.last_fallback_reason,
            "verified_live": self.verified_live,
        }

    def _call_nvidia(self, prompt: str, retry_on_transient: bool = True) -> Optional[str]:
        """
        Execute raw HTTP request to NVIDIA NIM OpenAI-compatible API with bounded retries,
        exponential backoff, read-timeout protection, and token accounting.
        Redacts API credentials from all logs.
        """
        if not self.api_key:
            self.fallback_active = True
            self.last_fallback_reason = "No valid NVIDIA_API_KEY configured."
            logger.info("No valid NVIDIA_API_KEY provided; engaging fallback.")
            return None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        max_attempts = 3 if retry_on_transient else 1
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        self.fallback_active = True
                        self.last_fallback_reason = f"NVIDIA NIM response contained no choices for model {self.model}"
                        return None

                    content = choices[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    p_tokens = usage.get("prompt_tokens", 0)
                    c_tokens = usage.get("completion_tokens", 0)
                    self.total_prompt_tokens += p_tokens
                    self.total_completion_tokens += c_tokens
                    self.call_count += 1

                    # NVIDIA NIM estimated cost rate ($0.20 per 1M tokens)
                    call_cost = ((p_tokens + c_tokens) * 0.20 / 1_000_000)
                    self.total_cost_usd += call_cost

                    logger.info(
                        f"NvidiaLLM call #{self.call_count} success | Model: {self.model} | "
                        f"Tokens: {p_tokens} prompt, {c_tokens} completion | "
                        f"Est. cost: ${call_cost:.6f}"
                    )
                    self.fallback_active = False
                    self.last_fallback_reason = None
                    self.verified_live = True
                    return content

                # Transient / Retryable HTTP status codes (429, 500, 503)
                if resp.status_code in (429, 500, 503):
                    if attempt < max_attempts:
                        delay = None
                        headers_resp = getattr(resp, "headers", {}) or {}
                        retry_after_str = headers_resp.get("Retry-After")
                        if retry_after_str:
                            try:
                                parsed_delay = float(retry_after_str.strip())
                                delay = min(max(0.0, parsed_delay), 30.0)
                            except (ValueError, TypeError):
                                delay = None

                        if delay is None:
                            delay = min(10.0, (1.0 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5))

                        logger.warning(
                            f"NVIDIA API HTTP {resp.status_code} on attempt {attempt}/{max_attempts}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        continue

                    self.fallback_active = True
                    self.last_fallback_reason = (
                        f"NVIDIA API HTTP error {resp.status_code} on model {self.model} after {max_attempts} attempts"
                    )
                    logger.warning(
                        f"NVIDIA API HTTP error {resp.status_code} (model: {self.model}) after {max_attempts} attempts; "
                        "engaging fallback."
                    )
                    return None

                # Non-retryable HTTP client error (400, 401, 403, 404)
                err_text = resp.text.replace(self.api_key, "[REDACTED]")
                self.fallback_active = True
                self.last_fallback_reason = f"NVIDIA API HTTP error {resp.status_code} on model {self.model}: {err_text}"
                logger.warning(
                    f"NVIDIA API non-retryable HTTP error {resp.status_code} (model: {self.model}): {err_text}"
                )
                return None

            except requests.exceptions.ReadTimeout as e:
                clean_err = str(e).replace(self.api_key, "[REDACTED]")
                self.fallback_active = True
                self.last_fallback_reason = (
                    f"NVIDIA API read timed out (no automatic retry to avoid duplicate generation): {clean_err}"
                )
                logger.warning(f"NVIDIA API read timed out ({clean_err}); engaging fallback without retry.")
                return None

            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
                if attempt < max_attempts:
                    delay = min(5.0, (0.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25))
                    logger.warning(
                        f"NVIDIA API connection error on attempt {attempt}/{max_attempts}: {type(e).__name__}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    continue

                clean_err = str(e).replace(self.api_key, "[REDACTED]")
                self.fallback_active = True
                self.last_fallback_reason = (
                    f"NVIDIA API connection failed after {max_attempts} attempts: {type(e).__name__}: {clean_err}"
                )
                logger.warning(f"NVIDIA API connection failed after {max_attempts} attempts; engaging fallback.")
                return None

            except Exception as e:
                clean_err = str(e).replace(self.api_key, "[REDACTED]")
                self.fallback_active = True
                self.last_fallback_reason = f"NVIDIA API request failed: {type(e).__name__}: {clean_err}"
                logger.warning(f"NVIDIA API request failed ({type(e).__name__}: {clean_err}); engaging fallback.")
                return None

        return None

    def _call_nvidia_json_with_retry(
        self,
        prompt: str,
        validator_fn: Callable[[Any], Tuple[bool, Any, str]],
    ) -> Tuple[Optional[Any], bool]:
        """
        Execute NVIDIA call, parse JSON, validate against schema, and execute single-retry recovery if invalid.
        Returns: (validated_data_or_none, live_attempted_bool)
        """
        raw_text = self._call_nvidia(prompt)
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

        logger.warning(f"NVIDIA JSON schema validation failed: {err_msg}. Executing single-retry recovery...")

        # Attempt 2: Corrective single-retry
        corrective_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL RETRY INSTRUCTION:\n"
            f"Your previous output failed schema validation: {err_msg}\n"
            f"Return ONLY valid raw JSON conforming strictly to the requested schema. No code fences, no extra text."
        )

        retry_text = self._call_nvidia(corrective_prompt, retry_on_transient=False)
        if retry_text is None:
            return None, True

        try:
            clean_retry = _strip_markdown_json(retry_text)
            parsed_retry = json.loads(clean_retry)
            is_valid, validated_data, err_msg = validator_fn(parsed_retry)
            if is_valid:
                return validated_data, True
            logger.error(f"NVIDIA single-retry validation failed: {err_msg}.")
            return None, True
        except Exception as e:
            logger.error(f"NVIDIA single-retry JSON parse error: {e}.")
            return None, True

    # ========================================================================
    # 1. Claim-Span Extraction
    # ========================================================================

    def extract_claims_live(self, draft_text: str, product_hint: Optional[str] = None) -> Optional[List[ClaimSpan]]:
        """Attempt live extraction without automatic MockLLM fallback."""
        prompt = build_extraction_prompt(draft_text, product_hint)
        validated_items, live_attempted = self._call_nvidia_json_with_retry(
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
        logger.info("Engaging fallback for NVIDIA claim extraction.")
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

        max_batch_size = 20
        all_ranked_items: List[Dict[str, Any]] = []

        batches = [
            candidate_facts[i : i + max_batch_size]
            for i in range(0, len(candidate_facts), max_batch_size)
        ]

        for batch in batches:
            prompt = build_ranking_prompt(claim_text, batch)
            batch_keys = {(f.fact_id, f.version) for f in batch}

            validated_batch, live_attempted = self._call_nvidia_json_with_retry(
                prompt,
                lambda data: validate_ranking_schema(data, batch_keys),
            )

            if validated_batch is None:
                return None

            all_ranked_items.extend(validated_batch)

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
        logger.info("Engaging fallback for NVIDIA candidate fact ranking.")
        return self.mock_fallback.rank_facts(claim_text, candidate_facts)

    # ========================================================================
    # 3. Intent-Preserving Rewrite Generation
    # ========================================================================

    def suggest_rewrite_live(self, finding: Finding, fact: Optional[FactVersion] = None) -> Optional[str]:
        """Attempt live rewrite generation without automatic MockLLM fallback."""
        prompt = build_rewrite_prompt(finding, fact)
        validated_rewrite, live_attempted = self._call_nvidia_json_with_retry(
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

        validated_rewrite, live_attempted = self._call_nvidia_json_with_retry(
            prompt,
            validate_rewrite_schema,
        )

        if validated_rewrite is not None:
            return validated_rewrite

        if live_attempted:
            logger.warning(
                f"NVIDIA LLM rewrite output invalid for finding {finding.finding_id}; "
                "marking UNLINKED with 'model output invalid' note."
            )
            finding.link_state = LinkState.UNLINKED
            if "model output invalid" not in finding.message:
                finding.message = f"{finding.message} [model output invalid - manual review required]".strip()
            finding.next_step = "Manual review required: Model output failed schema validation."
            return self.mock_fallback.suggest_rewrite(finding, fact)

        return self.mock_fallback.suggest_rewrite(finding, fact)
