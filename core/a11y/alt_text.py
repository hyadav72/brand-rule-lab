"""
Brand Rule Lab — Alt-Text Accessibility Validation
Owned by Agent A2 (Rules & Accessibility Engineer).
"""

from __future__ import annotations
from typing import List, Optional, Tuple

DEFAULT_FORBIDDEN_GENERIC = ["image", "photo", "picture", "graphic", "logo", "banner", "icon"]


def validate_alt_text(
    alt_text: Optional[str],
    min_length: int = 8,
    forbidden_generic: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Validate that an image has meaningful, non-generic alt-text.
    Returns (is_valid: bool, reason: str).
    """
    if alt_text is None or not alt_text.strip():
        return False, "Missing alternative text. Images must have descriptive alt-text."

    text = alt_text.strip()
    if len(text) < min_length:
        return False, f"Alt-text is too brief ({len(text)} chars). Minimum {min_length} characters required."

    forbidden = forbidden_generic or DEFAULT_FORBIDDEN_GENERIC
    if text.lower() in [f.lower() for f in forbidden]:
        return False, f"Generic alt-text '{text}' provides no informational value for screen readers."

    return True, "Valid alt-text"
