"""
Brand Rule Lab — Deterministic Predicates
Owned by Agent A2 (Rules & Accessibility Engineer).

All predicates are pure Python functions with ZERO LLM dependencies.
Deterministic, idempotent, and transparent.
"""

from __future__ import annotations
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image
from core.a11y.alt_text import validate_alt_text
from core.a11y.contrast import calculate_contrast_ratio, evaluate_wcag_aa


def predicate_term_list(
    text: str,
    disallowed_terms: List[str],
    case_sensitive: bool = False,
) -> List[str]:
    """Search for prohibited terms in text. Returns list of found terms."""
    matched: List[str] = []
    target = text if case_sensitive else text.lower()
    for term in disallowed_terms:
        search_term = term if case_sensitive else term.lower()
        # Word boundary or exact phrase check
        pattern = r"(?<!\w)" + re.escape(search_term) + r"(?!\w)"
        if re.search(pattern, target):
            matched.append(term)
    return matched


def predicate_regex(
    text: str,
    pattern: str,
    case_sensitive: bool = False,
) -> List[Tuple[int, int, str]]:
    """Match regex pattern in text. Returns list of (start, end, matched_text)."""
    flags = 0 if case_sensitive else re.IGNORECASE
    matches: List[Tuple[int, int, str]] = []
    for m in re.finditer(pattern, text, flags=flags):
        matches.append((m.start(), m.end(), m.group(0)))
    return matches


def predicate_numeric_timeframe(
    text: str,
    pattern: str = r"(\d+)\s*(days?|hours?|hrs?|weeks?|months?)",
    approved_timeframe_days_min: int = 28,
) -> Tuple[bool, Optional[int], str]:
    """
    Compare claimed turnaround against clinical trials minimum days.
    Returns (has_violation: bool, claimed_days: Optional[int], message: str).
    """
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return False, None, "No timeframe claim detected."

    num = int(match.group(1))
    unit = match.group(2).lower()

    # Convert to equivalent days
    if "hour" in unit or "hr" in unit:
        days = max(1, num // 24)
    elif "week" in unit:
        days = num * 7
    elif "month" in unit:
        days = num * 30
    else:
        days = num

    if days < approved_timeframe_days_min:
        return (
            True,
            days,
            f"Claimed turnaround of {num} {unit} (~{days} days) contradicts approved trial baseline (minimum {approved_timeframe_days_min} days).",
        )

    return False, days, "Timeframe meets or exceeds approved clinical baseline."


def predicate_date_window(
    text: str,
    approved_end_date_str: str,
    planned_publish_date_str: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verify offer dates against approved campaign expiration window.
    Returns (has_violation: bool, message: str).
    """
    try:
        approved_expiry = datetime.strptime(approved_end_date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, f"Invalid approved expiry date format: {approved_end_date_str}"

    # Check text for explicit offer dates
    # e.g., "Sale ends 15 Nov", "until November 20th", "through Nov 10"
    MONTHS_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"

    # Format 1: "ends 15 Nov", "until 20 November"
    m1 = re.search(rf"(?:ends|until|through)\s+(\d{{1,2}})\s+({MONTHS_RE})", text, flags=re.IGNORECASE)
    if m1:
        day = int(m1.group(1))
        month_abbr = m1.group(2)[:3].title()
        try:
            stated_date = datetime.strptime(f"{day} {month_abbr} {approved_expiry.year}", "%d %b %Y").date()
            if stated_date > approved_expiry:
                return True, f"Offer date '{stated_date}' exceeds approved campaign deadline '{approved_expiry}'."
        except Exception:
            pass

    # Format 2: "until November 20th", "through Nov 10"
    m2 = re.search(rf"(?:ends|until|through)\s+({MONTHS_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?", text, flags=re.IGNORECASE)
    if m2:
        month_abbr = m2.group(1)[:3].title()
        day = int(m2.group(2))
        try:
            stated_date = datetime.strptime(f"{day} {month_abbr} {approved_expiry.year}", "%d %b %Y").date()
            if stated_date > approved_expiry:
                return True, f"Offer date '{stated_date}' exceeds approved campaign deadline '{approved_expiry}'."
        except Exception:
            pass

    # Format 3: ISO date "2026-11-15"
    m3 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m3:
        try:
            stated_date = datetime.strptime(m3.group(1), "%Y-%m-%d").date()
            if stated_date > approved_expiry:
                return True, f"Offer date '{stated_date}' extends past approved campaign end '{approved_expiry}'."
        except Exception:
            pass

    # Also compare planned publish date against offer expiration if text has offer mentions or dates
    has_offer_context = bool(
        m1 or m2 or m3 or re.search(r"\b(?:sale|offer|promotion|deal|discount|save|ends?|until|through)\b", text, flags=re.IGNORECASE)
    )
    if planned_publish_date_str and has_offer_context:
        try:
            pub_date = datetime.strptime(planned_publish_date_str, "%Y-%m-%d").date()
            if pub_date > approved_expiry:
                return True, f"Planned publication date '{pub_date}' is after offer expires ({approved_expiry})."
        except ValueError:
            pass

    return False, "Offer dates within approved campaign window."


def predicate_required_text(
    text: str,
    required_phrases: List[str],
    case_sensitive: bool = False,
) -> List[str]:
    """Check for mandatory disclaimers or legal statements. Returns list of MISSING phrases."""
    missing: List[str] = []
    target = text if case_sensitive else text.lower()
    for phrase in required_phrases:
        search_phrase = phrase if case_sensitive else phrase.lower()
        if search_phrase not in target:
            missing.append(phrase)
    return missing


def compute_dhash(image_input: Union[bytes, Image.Image, str, Path], hash_size: int = 8) -> int:
    """
    Compute 64-bit difference hash (dHash) using Pillow.
    Normalizes image by converting to grayscale and scaling to (hash_size + 1, hash_size).
    Calculates differences between adjacent horizontal pixels to construct a deterministic bit hash.
    """
    if isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    elif isinstance(image_input, bytes):
        img = Image.open(io.BytesIO(image_input))
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    gray_resized = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(gray_resized.getdata())
    diff = 0
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            p1 = pixels[row_start + col]
            p2 = pixels[row_start + col + 1]
            if p1 > p2:
                diff |= 1 << (row * hash_size + col)
    return diff


def compute_hamming_distance(hash1: int, hash2: int) -> int:
    """Compute Hamming distance (differing bit count) between two 64-bit hashes."""
    return bin(hash1 ^ hash2).count("1")


def predicate_logo_hash(
    candidate_image: Optional[Union[bytes, Image.Image, str, Path]],
    reference_logo: Optional[Union[bytes, Image.Image, str, Path]],
    max_hamming_distance: int = 10,
) -> Tuple[bool, Optional[int], str]:
    """
    Compare candidate logo against registered reference brand logo.
    Threshold: max_hamming_distance (default: 10 out of 64 bits).
    Returns (has_violation: bool, hamming_distance: Optional[int], message: str).
    
    Coverage Boundary:
    If product has no registered reference logo asset, predicate returns has_violation=False
    with an informational notice explaining that the coverage boundary has been met.

    ARCHITECTURAL LIMITATION & SCOPE BOUNDARY:
    dHash computes global difference gradients across the normalized (9x8) image.
    This predicate strictly compares PRE-CROPPED candidate logo assets against pre-cropped
    reference logos. It does NOT perform object localization, bounding-box detection, or
    cropping from unsegmented full ad creatives. Passing an entire uncropped creative banner
    will compare the entire scene rather than the isolated logo glyph.
    """
    if candidate_image is None or (isinstance(candidate_image, bytes) and len(candidate_image) == 0):
        return False, None, "No candidate image provided for logo verification."

    if reference_logo is None or (isinstance(reference_logo, bytes) and len(reference_logo) == 0):
        return False, None, "No registered reference logo asset for this product; logo verification check skipped (coverage boundary notice)."

    try:
        cand_hash = compute_dhash(candidate_image)
        ref_hash = compute_dhash(reference_logo)
        distance = compute_hamming_distance(cand_hash, ref_hash)

        if distance > max_hamming_distance:
            return (
                True,
                distance,
                f"Logo perceptual difference (Hamming distance {distance}/64) exceeds threshold ({max_hamming_distance}). Unapproved logo alteration or spoofing detected.",
            )

        return (
            False,
            distance,
            f"Logo matches approved reference asset (Hamming distance {distance}/64 <= threshold {max_hamming_distance}).",
        )
    except Exception as e:
        return True, None, f"Failed to compute logo perceptual hash: {e}"

