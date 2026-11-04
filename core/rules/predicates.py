"""
Brand Rule Lab — Deterministic Predicates
Owned by Agent A2 (Rules & Accessibility Engineer).

All predicates are pure Python functions with ZERO LLM dependencies.
Deterministic, idempotent, and transparent.
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
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

    # Also compare planned publish date against offer expiration
    if planned_publish_date_str:
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
