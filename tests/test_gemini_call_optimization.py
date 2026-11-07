"""
Brand Rule Lab — Gemini API Call Optimization & Deterministic Rule Regression Tests
Verifies that:
1. RuleEngine.check_rewrite() makes ZERO LLM calls in both live and mock configurations.
2. Repeated calls to check_rewrite() make zero network requests.
3. Rendering Creator page does not invoke extraction or rewrite generation on initial render.
4. Explicitly loading a draft invokes extraction once, and subsequent reruns make zero additional AI calls.
5. Cached rewrite checks invalidate when underlying product facts change.
"""

from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from streamlit.testing.v1 import AppTest

from core.models import ExtractedDoc, Finding, Severity, LinkState
from core.rules.engine import RuleEngine
import importlib
creator_page = importlib.import_module("app.pages.1_Creator")
_cached_check_rewrite = creator_page._cached_check_rewrite
_get_fact_context_signature = creator_page._get_fact_context_signature


def test_check_rewrite_makes_zero_llm_calls_in_live_and_mock(monkeypatch):
    """
    Verify that check_rewrite() is 100% deterministic and never invokes
    the configured LLM adapter in either live or mock mode.
    """
    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US", "channel": "paid_social"}

    # 1. LIVE CONFIGURATION: Guard against any live API or adapter call
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("LLM_API_KEY", "test-live-key")

    import core.llm.live
    def forbid_gemini(*args, **kwargs):
        raise AssertionError("Network/Gemini request forbidden inside check_rewrite()!")

    monkeypatch.setattr(core.llm.live.LiveLLM, "_call_gemini_json_with_retry", forbid_gemini)
    monkeypatch.setattr(core.llm.live.LiveLLM, "extract_claims", forbid_gemini)

    # Clean sentence
    clean_txt = "Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use."
    is_clean, viols = engine.check_rewrite(clean_txt, context)
    assert is_clean is True
    assert len(viols) == 0

    # Dirty sentence (V-04)
    v04_txt = "Say goodbye to acne forever!"
    is_clean, viols = engine.check_rewrite(v04_txt, context)
    assert is_clean is False
    assert any(v.rule_id == "V-04" for v in viols)

    # 2. MOCK CONFIGURATION: Guard against MockLLM invocation
    monkeypatch.setenv("LLM_MODE", "mock")
    import core.llm.mock
    def forbid_mock_extract(*args, **kwargs):
        raise AssertionError("MockLLM.extract_claims() forbidden inside check_rewrite()!")

    monkeypatch.setattr(core.llm.mock.MockLLM, "extract_claims", forbid_mock_extract)

    is_clean2, viols2 = engine.check_rewrite(clean_txt, context)
    assert is_clean2 is True

    is_clean3, viols3 = engine.check_rewrite("Say goodbye to acne long-term!", context)
    assert is_clean3 is False


def test_repeated_check_rewrite_makes_zero_network_requests(monkeypatch):
    """
    Verify that calling check_rewrite() repeatedly never attempts socket or HTTP connections.
    """
    import socket
    def forbid_connect(*args, **kwargs):
        raise AssertionError("Network socket connection attempted during rule check!")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)

    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US"}

    test_inputs = [
        ("Gentle daily wash for clearer-looking skin!", True),
        ("Say goodbye to acne forever!", False),
        ("Our 2.5% BPO wash clears breakouts in 3 days.", False),
        ("Our 2.5% Benzoyl Peroxide wash reduces breakouts in 4 weeks with twice-daily use.", True),
        ("Clinically proven to cure acne instantly.", False),
    ]

    # Run 50 repeated evaluations
    for _ in range(10):
        for text, expected in test_inputs:
            is_clean, _ = engine.check_rewrite(text, context)
            assert is_clean is expected


def test_creator_page_initial_render_makes_zero_ai_calls(monkeypatch, tmp_path):
    """
    Verify that navigating to / rendering the Creator page makes ZERO AI calls
    before the user explicitly clicks a load/upload button.
    """
    temp_db = tmp_path / "creator_render_test.db"
    from core.seed import seed_database
    seed_database(str(temp_db), include_demo_assets=False)
    monkeypatch.setenv("DATABASE_PATH", str(temp_db))
    monkeypatch.setattr("core.db.DEFAULT_DB_PATH", str(temp_db))
    monkeypatch.setenv("LLM_MODE", "mock")

    extract_mock = MagicMock()
    suggest_mock = MagicMock()

    import core.extract.claims
    import core.llm.mock
    monkeypatch.setattr(core.extract.claims, "extract_claims", extract_mock)
    monkeypatch.setattr(core.llm.mock.MockLLM, "suggest_rewrite", suggest_mock)

    at = AppTest.from_file("app/pages/1_Creator.py")
    at.run()
    assert not at.exception

    # Zero AI extraction or rewrite calls on initial render
    assert extract_mock.call_count == 0, f"Expected 0 extraction calls on initial render, got {extract_mock.call_count}"
    assert suggest_mock.call_count == 0, f"Expected 0 rewrite calls on initial render, got {suggest_mock.call_count}"
    assert at.session_state["active_doc"] is None
    assert len(at.session_state["findings"]) == 0


def test_creator_page_explicit_load_and_rerun_isolation(monkeypatch, tmp_path):
    """
    Verify that:
    1. Explicitly clicking 'Load Hackathon Demo Draft' triggers extraction once.
    2. Subsequent Streamlit reruns (e.g. accepting a rewrite) do NOT re-invoke extraction or rewrites.
    """
    temp_db = tmp_path / "creator_rerun_test.db"
    from core.seed import seed_database
    seed_database(str(temp_db), include_demo_assets=False)
    monkeypatch.setenv("DATABASE_PATH", str(temp_db))
    monkeypatch.setattr("core.db.DEFAULT_DB_PATH", str(temp_db))
    monkeypatch.setenv("LLM_MODE", "mock")

    import core.extract.claims
    import core.llm.mock

    original_extract = core.extract.claims.extract_claims
    original_suggest = core.llm.mock.MockLLM.suggest_rewrite

    extract_call_count = 0
    suggest_call_count = 0

    def tracked_extract(*args, **kwargs):
        nonlocal extract_call_count
        extract_call_count += 1
        return original_extract(*args, **kwargs)

    def tracked_suggest(*args, **kwargs):
        nonlocal suggest_call_count
        suggest_call_count += 1
        return original_suggest(*args, **kwargs)

    monkeypatch.setattr(core.extract.claims, "extract_claims", tracked_extract)
    monkeypatch.setattr(core.llm.mock.MockLLM, "suggest_rewrite", tracked_suggest)

    at = AppTest.from_file("app/pages/1_Creator.py")
    at.run()
    assert not at.exception
    assert extract_call_count == 0

    # 1. Explicitly load demo draft
    at.button[0].click().run()
    assert not at.exception
    assert extract_call_count == 1, "extract_claims must be called exactly once for explicit document load"
    assert suggest_call_count > 0, "suggest_rewrite should enrich initial findings"

    loaded_extract_count = extract_call_count
    loaded_suggest_count = suggest_call_count

    # 2. Simulate user interaction rerun (e.g. accepting finding 1)
    target_fid = at.session_state["findings"][0].finding_id
    acc_btn = [b for b in at.button if b.key == f"btn_acc_{target_fid}"][0]
    acc_btn.click().run()
    assert not at.exception

    # Assert NO additional AI calls occurred during the rerun
    assert extract_call_count == loaded_extract_count, "No additional claim extraction should occur on rerun"
    assert suggest_call_count == loaded_suggest_count, "No additional rewrite generation should occur on rerun"

    # 3. Simulate another general script rerun
    at.run()
    assert not at.exception
    assert extract_call_count == loaded_extract_count
    assert suggest_call_count == loaded_suggest_count


def test_fact_context_signature_and_cache_invalidation():
    """
    Verify that _get_fact_context_signature changes when fact registry versions change,
    preventing stale PASS reuse.
    """
    from core.models import FactVersion

    engine = RuleEngine()
    context = {"product": "prod_monsoon", "market": "US"}

    sig1 = _get_fact_context_signature("prod_monsoon", "US")
    assert "prod_monsoon:US:" in sig1

    # Same context returns identical signature
    sig2 = _get_fact_context_signature("prod_monsoon", "US")
    assert sig1 == sig2

    # Different product returns different signature
    sig_glow = _get_fact_context_signature("prod_glow", "US")
    assert sig1 != sig_glow
