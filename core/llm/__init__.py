"""
Brand Rule Lab — LLM Module Entry Point
Owned by Agent A3 (LLM & Retrieval Engineer).
"""

from __future__ import annotations
import os
from typing import Any, Dict, Optional
from dotenv import load_dotenv

from core.llm.adapter import LLMAdapter
from core.llm.mock import MockLLM
from core.llm.live import LiveLLM
from core.llm.nvidia import NvidiaLLM
from core.llm.manager import ProviderManager, ProviderType

load_dotenv()

# Module-level active adapter instance
_active_adapter: Optional[LLMAdapter] = None
_active_mode: Optional[str] = None


def get_llm_adapter(mode: str | None = None, provider: str | None = None) -> LLMAdapter:
    """
    Return active LLM adapter according to environment or override.
    Supports mode='mock', mode='live', mode='gemini', mode='nvidia',
    mode='dual', or explicit provider override.
    """
    global _active_adapter, _active_mode
    mode_from_secrets = None
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "LLM_MODE" in st.secrets:
            mode_from_secrets = str(st.secrets["LLM_MODE"]).strip().lower()
    except Exception:
        pass

    requested_mode = (mode or mode_from_secrets or os.getenv("LLM_MODE", "mock")).lower().strip()

    if _active_adapter is not None and _active_mode == requested_mode and mode is None and provider is None:
        return _active_adapter

    if requested_mode == "mock":
        adapter: LLMAdapter = MockLLM()
    elif requested_mode == "gemini":
        adapter = LiveLLM()
    elif requested_mode == "nvidia":
        adapter = NvidiaLLM()
    elif requested_mode in ("live", "dual"):
        adapter = ProviderManager(primary=provider)
    else:
        # Default fallback
        adapter = MockLLM()

    if mode is None and provider is None:
        _active_adapter = adapter
        _active_mode = requested_mode

    return adapter


def get_llm_status() -> Dict[str, Any]:
    """Retrieve runtime status, fallback detection, and telemetry of active LLM adapter."""
    adapter = get_llm_adapter()

    if isinstance(adapter, ProviderManager):
        return adapter.get_status()

    if isinstance(adapter, (LiveLLM, NvidiaLLM)):
        telemetry = adapter.get_telemetry()
        return {
            "mode": "live",
            "provider": adapter.provider,
            "model": adapter.model,
            "fallback_active": adapter.fallback_active,
            "fallback_reason": adapter.last_fallback_reason,
            "telemetry": telemetry,
        }

    return {
        "mode": "mock",
        "provider": "mock",
        "model": "deterministic-mock",
        "fallback_active": False,
        "fallback_reason": None,
        "telemetry": {},
    }


__all__ = [
    "LLMAdapter",
    "MockLLM",
    "LiveLLM",
    "NvidiaLLM",
    "ProviderManager",
    "ProviderType",
    "get_llm_adapter",
    "get_llm_status",
]
