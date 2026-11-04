"""
Brand Rule Lab — Accessibility & WCAG Contrast Calculations
Owned by Agent A2 (Rules & Accessibility Engineer).

Calculates WCAG 2.1 relative luminance and contrast ratios using the official W3C formula.
WCAG AA: 4.5:1 for standard text, 3.0:1 for large text (>=18pt or >=14pt bold).
"""

from __future__ import annotations
import re
from typing import Tuple


def hex_to_rgb(hex_code: str) -> Tuple[int, int, int]:
    """Parse #RRGGBB or #RGB string to (R, G, B) tuple."""
    cleaned = hex_code.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join([c * 2 for c in cleaned])
    if len(cleaned) != 6 or not re.match(r"^[0-9a-fA-F]{6}$", cleaned):
        raise ValueError(f"Invalid hex color code: '{hex_code}'")

    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return r, g, b


def channel_luminance(channel_8bit: int) -> float:
    """Compute relative luminance channel value."""
    s = channel_8bit / 255.0
    if s <= 0.04045:
        return s / 12.92
    else:
        return ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance per W3C WCAG 2.1 specification."""
    r_lum = channel_luminance(r)
    g_lum = channel_luminance(g)
    b_lum = channel_luminance(b)
    return 0.2126 * r_lum + 0.7152 * g_lum + 0.0722 * b_lum


def calculate_contrast_ratio(foreground_hex: str, background_hex: str) -> float:
    """
    Compute contrast ratio between two hex colors.
    Returns ratio value between 1.0 and 21.0.
    Formula: (L1 + 0.05) / (L2 + 0.05), where L1 is the lighter color.
    """
    fg_rgb = hex_to_rgb(foreground_hex)
    bg_rgb = hex_to_rgb(background_hex)

    l1 = relative_luminance(*fg_rgb)
    l2 = relative_luminance(*bg_rgb)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    ratio = (lighter + 0.05) / (darker + 0.05)
    return round(ratio, 2)


def evaluate_wcag_aa(foreground_hex: str, background_hex: str, is_large_text: bool = False) -> Tuple[bool, float]:
    """
    Evaluate if color pair meets WCAG Level AA contrast.
    Returns (passes: bool, ratio: float).
    """
    ratio = calculate_contrast_ratio(foreground_hex, background_hex)
    threshold = 3.0 if is_large_text else 4.5
    return (ratio >= threshold, ratio)
