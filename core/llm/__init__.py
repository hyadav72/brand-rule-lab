"""
Brand Rule Lab — LLM Module Entry Point
Owned by Agent A3 (LLM & Retrieval Engineer).
"""

from __future__ import annotations
import os
from dotenv import load_dotenv
from core.llm.adapter import LLMAdapter
from core.llm.mock import MockLLM
from core.llm.live import LiveLLM

load_dotenv()


def get_llm_adapter(mode: str | None = None) -> LLMAdapter:
    """Return active LLM adapter according to environment or override."""
    active_mode = (mode or os.getenv("LLM_MODE", "mock")).lower()
    if active_mode == "live":
        return LiveLLM()
    return MockLLM()


__all__ = ["LLMAdapter", "MockLLM", "LiveLLM", "get_llm_adapter"]
