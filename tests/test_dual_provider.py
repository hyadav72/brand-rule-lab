"""
Brand Rule Lab — Dual-Provider Architecture Test Suite
Owned by Agent A3 (LLM & Retrieval Engineer).

Tests for Dual-Provider Architecture (Gemini + NVIDIA NIM + Deterministic Mock):
1. Gemini live adapter test.
2. NVIDIA live adapter test.
3. Gemini-to-NVIDIA fallback.
4. NVIDIA-to-Mock fallback.
5. Both providers unavailable.
6. Malformed JSON handling for both providers.
7. Identical schema and governance tests.
8. Confirm zero duplicate calls on successful primary requests.
"""

import json as json_lib
import pytest
from typing import Any, Dict, List

from core.llm.live import LiveLLM
from core.llm.mock import MockLLM
from core.llm.nvidia import NvidiaLLM
from core.llm.manager import ProviderManager, ProviderType
from core.models import ClaimSpan, FactVersion, Finding, FindingKind, LinkState, Severity


class MockHttpResponse:
    def __init__(self, json_data: Any, status_code: int = 200, headers: Dict[str, str] = None, text: str = ""):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text or json_lib.dumps(json_data)

    def json(self):
        return self._json_data


# ============================================================================
# 1. Gemini Live Adapter Test
# ============================================================================

def test_gemini_live_adapter_extraction_and_telemetry(monkeypatch):
    """Verify Gemini adapter parses valid JSON response, accounts tokens, and aligns offsets."""
    monkeypatch.setenv("LLM_API_KEY", "test_gemini_key_123")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    adapter = LiveLLM(model="gemini-3.1-flash-lite")

    def mock_post(url, **kwargs):
        assert "models/gemini-3.1-flash-lite:generateContent" in url
        return MockHttpResponse({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json_lib.dumps([
                            {"text": "clears breakouts in 3 days", "start": 0, "end": 26, "product_alias": "Monsoon Clear Skin"}
                        ])
                    }]
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 120,
                "candidatesTokenCount": 45
            }
        }, 200)

    monkeypatch.setattr("requests.post", mock_post)

    draft = "clears breakouts in 3 days with natural tea tree oil."
    claims = adapter.extract_claims(draft, product_hint="Monsoon Clear Skin")

    assert len(claims) == 1
    assert claims[0].text == "clears breakouts in 3 days"
    assert claims[0].start == 0
    assert claims[0].end == 26
    assert claims[0].product_alias == "Monsoon Clear Skin"

    telemetry = adapter.get_telemetry()
    assert telemetry["call_count"] == 1
    assert telemetry["total_prompt_tokens"] == 120
    assert telemetry["total_completion_tokens"] == 45
    assert telemetry["fallback_active"] is False


# ============================================================================
# 2. NVIDIA Live Adapter Test
# ============================================================================

def test_nvidia_live_adapter_extraction_and_telemetry(monkeypatch):
    """Verify NVIDIA NIM adapter uses OpenAI chat completions format and updates telemetry."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test_nvapi_key_456")

    adapter = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3")

    recorded_headers = []
    recorded_payload = []

    def mock_post(url, **kwargs):
        headers = kwargs.get("headers", {})
        body = kwargs.get("json", {})
        recorded_headers.append(headers)
        recorded_payload.append(body)
        assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert headers.get("Authorization") == "Bearer test_nvapi_key_456"
        assert body.get("model") == "mistralai/mistral-7b-instruct-v0.3"

        return MockHttpResponse({
            "id": "chat-123",
            "model": "mistralai/mistral-7b-instruct-v0.3",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json_lib.dumps([
                        {"text": "reduces acne by 80%", "start": 0, "end": 20, "product_alias": "Monsoon Wash"}
                    ])
                }
            }],
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 40,
                "total_tokens": 190
            }
        }, 200)

    monkeypatch.setattr("requests.post", mock_post)

    draft = "reduces acne by 80% clinically proven."
    claims = adapter.extract_claims(draft, product_hint="Monsoon Wash")

    assert len(claims) == 1
    assert claims[0].text == "reduces acne by 80%"
    assert claims[0].start == 0
    assert claims[0].end == 19

    telemetry = adapter.get_telemetry()
    assert telemetry["call_count"] == 1
    assert telemetry["total_prompt_tokens"] == 150
    assert telemetry["total_completion_tokens"] == 40
    assert telemetry["fallback_active"] is False
    assert telemetry["verified_live"] is True


# ============================================================================
# 3. Gemini-to-NVIDIA Fallback
# ============================================================================

def test_gemini_to_nvidia_fallback_when_gemini_fails(monkeypatch):
    """Verify ProviderManager seamlessly falls back to NVIDIA when Gemini fails, without calling mock."""
    gemini = LiveLLM(model="gemini-3.1-flash-lite", api_key="bad_gemini_key")
    nvidia = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3", api_key="valid_nvapi_key")
    mock = MockLLM()

    call_counts = {"gemini": 0, "nvidia": 0}

    def mock_post(url, **kwargs):
        if "generativelanguage.googleapis.com" in url:
            call_counts["gemini"] += 1
            # HTTP 401: non-retryable error, immediately returns None and engages fallback
            return MockHttpResponse({"error": "Unauthorized"}, status_code=401)
        elif "integrate.api.nvidia.com" in url:
            call_counts["nvidia"] += 1
            return MockHttpResponse({
                "choices": [{
                    "message": {
                        "content": json_lib.dumps([
                            {"text": "reduces blemishes in 48 hours", "start": 0, "end": 29, "product_alias": "Monsoon"}
                        ])
                    }
                }],
                "usage": {"prompt_tokens": 80, "completion_tokens": 30}
            }, 200)
        return MockHttpResponse({}, status_code=404)

    monkeypatch.setattr("requests.post", mock_post)

    manager = ProviderManager(
        primary="gemini",
        secondary="nvidia",
        fallback="mock",
        gemini_adapter=gemini,
        nvidia_adapter=nvidia,
        mock_adapter=mock,
    )

    draft = "reduces blemishes in 48 hours guaranteed."
    claims = manager.extract_claims(draft, product_hint="Monsoon")

    assert len(claims) == 1
    assert claims[0].text == "reduces blemishes in 48 hours"
    assert manager.active_provider == "nvidia"
    assert call_counts["gemini"] == 1
    assert call_counts["nvidia"] == 1
    assert len(manager.fallback_events) == 1
    assert manager.fallback_events[0]["from_provider"] == "gemini"
    assert manager.fallback_events[0]["to_provider"] == "nvidia"


# ============================================================================
# 4. NVIDIA-to-Mock Fallback
# ============================================================================

def test_nvidia_to_mock_fallback_on_unauthorized(monkeypatch):
    """Verify fallback from NVIDIA to deterministic Mock on 401 Unauthorized."""
    nvidia = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3", api_key="invalid_hex_key")
    mock = MockLLM()

    def mock_post(url, **kwargs):
        return MockHttpResponse(
            {"status": 401, "title": "Unauthorized", "detail": "Invalid JWT serialization"},
            status_code=401,
            text='{"status": 401, "detail": "Invalid JWT serialization"}'
        )

    monkeypatch.setattr("requests.post", mock_post)

    manager = ProviderManager(
        primary="nvidia",
        secondary="mock",
        fallback="mock",
        nvidia_adapter=nvidia,
        mock_adapter=mock,
    )

    draft = "Say goodbye to acne forever! Clears breakouts in 3 days."
    claims = manager.extract_claims(draft, product_hint="Monsoon Clear Skin")

    assert len(claims) > 0
    assert manager.active_provider == "mock"
    assert len(manager.fallback_events) >= 1
    assert manager.fallback_events[0]["from_provider"] == "nvidia"
    assert manager.fallback_events[0]["to_provider"] == "mock"


# ============================================================================
# 5. Both Providers Unavailable
# ============================================================================

def test_both_providers_unavailable_falls_back_to_mock(monkeypatch):
    """Verify graceful recovery to deterministic mock when both Gemini and NVIDIA fail."""
    gemini = LiveLLM(model="gemini-3.1-flash-lite", api_key="failing_key")
    nvidia = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3", api_key="failing_key")
    mock = MockLLM()

    def mock_post(url, **kwargs):
        raise ConnectionError("Network unreachable [sandbox socket blocked]")

    monkeypatch.setattr("requests.post", mock_post)

    manager = ProviderManager(
        primary="gemini",
        secondary="nvidia",
        fallback="mock",
        gemini_adapter=gemini,
        nvidia_adapter=nvidia,
        mock_adapter=mock,
    )

    draft = "Say goodbye to acne forever! 2.5% BPO wash clears breakouts in 3 days."
    claims = manager.extract_claims(draft, product_hint="Monsoon Clear Skin")

    assert len(claims) == 3
    assert manager.active_provider == "mock"
    assert len(manager.fallback_events) >= 2
    assert manager.fallback_events[0]["from_provider"] == "gemini"
    assert manager.fallback_events[0]["to_provider"] == "nvidia"
    assert manager.fallback_events[1]["from_provider"] == "nvidia"
    assert manager.fallback_events[1]["to_provider"] == "mock"

    status = manager.get_status()
    assert status["mode"] == "live"
    assert status["fallback_active"] is True
    assert status["active_provider"] == "mock"


# ============================================================================
# 6. Malformed JSON Handling for Both Providers
# ============================================================================

def test_malformed_json_recovery_and_unlinked_handling(monkeypatch):
    """Verify single-retry repair loop on malformed JSON for both Gemini and NVIDIA."""
    # Test 6A: Gemini recovers on single retry
    gemini = LiveLLM(model="gemini-3.1-flash-lite", api_key="valid_key")
    attempts = [0]

    def mock_gemini_post(url, **kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            # First attempt returns malformed JSON
            return MockHttpResponse({
                "candidates": [{"content": {"parts": [{"text": "NOT_JSON_AT_ALL"}]}}]
            }, 200)
        else:
            # Second attempt (corrective prompt) returns valid JSON
            return MockHttpResponse({
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": json_lib.dumps([
                                {"text": "heals skin rapidly", "start": 0, "end": 18, "product_alias": "Serum"}
                            ])
                        }]
                    }
                }]
            }, 200)

    monkeypatch.setattr("requests.post", mock_gemini_post)

    draft = "heals skin rapidly with vitamins."
    claims = gemini.extract_claims(draft, product_hint="Serum")
    assert attempts[0] == 2
    assert len(claims) == 1
    assert claims[0].text == "heals skin rapidly"

    # Test 6B: NVIDIA rewrite fails both attempts and marks finding UNLINKED
    nvidia = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3", api_key="valid_key")

    def mock_nvidia_malformed(url, **kwargs):
        return MockHttpResponse({
            "choices": [{"message": {"content": "INVALID_JSON"}}]
        }, 200)

    monkeypatch.setattr("requests.post", mock_nvidia_malformed)

    finding = Finding(
        finding_id="FND-01",
        asset_id="AST-01",
        kind=FindingKind.CLAIM,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=17,
        source_text="cure acne forever",
        rule_id="V-04",
        message="Total cure claim",
    )
    fact = FactVersion(
        fact_id="F-112",
        version=3,
        product_id="PRD-01",
        market="US",
        fact_text="Salicylic Acid helps reduce breakouts",
        permitted_wording="helps reduce breakouts",
        valid_from="2026-01-01",
    )

    rewrite = nvidia.suggest_rewrite(finding, fact)
    assert finding.link_state == LinkState.UNLINKED
    assert "model output invalid" in finding.message
    assert "Manual review required" in finding.next_step


# ============================================================================
# 7. Identical Schema and Governance Tests
# ============================================================================

def test_identical_schema_and_anti_hallucination_for_both_providers(monkeypatch):
    """Verify both Gemini and NVIDIA reject hallucinated facts and preserve unranked candidates."""
    candidate_facts = [
        FactVersion(
            fact_id="F-101",
            version=1,
            product_id="PRD-01",
            market="US",
            fact_text="Zinc supports barrier",
            permitted_wording="supports skin",
            valid_from="2026-01-01",
        ),
        FactVersion(
            fact_id="F-102",
            version=1,
            product_id="PRD-01",
            market="US",
            fact_text="Niacinamide calms redness",
            permitted_wording="calms redness",
            valid_from="2026-01-01",
        ),
    ]

    # Model attempts to return hallucinated fact F-999
    hallucinated_output = [
        {"fact_id": "F-999", "version": 1, "score": 0.99, "rationale": "Hallucinated"},
        {"fact_id": "F-101", "version": 1, "score": 0.85, "rationale": "Valid match"},
    ]

    # Test Gemini
    gemini = LiveLLM(api_key="valid_key")
    monkeypatch.setattr("requests.post", lambda url, **kw: MockHttpResponse({
        "candidates": [{"content": {"parts": [{"text": json_lib.dumps(hallucinated_output)}]}}]
    }, 200))

    ranked_gemini = gemini.rank_facts("soothes redness", candidate_facts)
    fact_ids_gemini = [r.fact.fact_id for r in ranked_gemini]
    assert "F-999" not in fact_ids_gemini
    assert "F-102" in fact_ids_gemini
    f102_gemini = next(r for r in ranked_gemini if r.fact.fact_id == "F-102")
    assert f102_gemini.score == 0.0

    # Test NVIDIA
    nvidia = NvidiaLLM(api_key="valid_key")
    monkeypatch.setattr("requests.post", lambda url, **kw: MockHttpResponse({
        "choices": [{"message": {"content": json_lib.dumps(hallucinated_output)}}]
    }, 200))

    ranked_nvidia = nvidia.rank_facts("soothes redness", candidate_facts)
    fact_ids_nvidia = [r.fact.fact_id for r in ranked_nvidia]
    assert "F-999" not in fact_ids_nvidia
    assert "F-102" in fact_ids_nvidia
    f102_nvidia = next(r for r in ranked_nvidia if r.fact.fact_id == "F-102")
    assert f102_nvidia.score == 0.0


# ============================================================================
# 8. Confirm Zero Duplicate Calls on Successful Primary Requests
# ============================================================================

def test_zero_duplicate_calls_on_successful_primary(monkeypatch):
    """Verify that when primary provider succeeds, secondary and mock providers receive zero calls."""
    gemini = LiveLLM(model="gemini-3.1-flash-lite", api_key="valid_key")
    nvidia = NvidiaLLM(model="mistralai/mistral-7b-instruct-v0.3", api_key="valid_key")
    mock = MockLLM()

    call_records = {"gemini": 0, "nvidia": 0}

    def mock_post(url, **kwargs):
        if "generativelanguage.googleapis.com" in url:
            call_records["gemini"] += 1
            return MockHttpResponse({
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": json_lib.dumps([
                                {"text": "fast relief", "start": 0, "end": 11, "product_alias": "Gel"}
                            ])
                        }]
                    }
                }],
                "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20}
            }, 200)
        elif "integrate.api.nvidia.com" in url:
            call_records["nvidia"] += 1
            return MockHttpResponse({}, 200)
        return MockHttpResponse({}, 404)

    monkeypatch.setattr("requests.post", mock_post)

    manager = ProviderManager(
        primary="gemini",
        secondary="nvidia",
        fallback="mock",
        gemini_adapter=gemini,
        nvidia_adapter=nvidia,
        mock_adapter=mock,
    )

    claims = manager.extract_claims("fast relief within hours.", product_hint="Gel")

    assert len(claims) == 1
    assert claims[0].text == "fast relief"
    # Primary called exactly once
    assert call_records["gemini"] == 1
    # Secondary had ZERO duplicate calls
    assert call_records["nvidia"] == 0
    # Active provider is Gemini
    assert manager.active_provider == "gemini"
    assert len(manager.fallback_events) == 0
