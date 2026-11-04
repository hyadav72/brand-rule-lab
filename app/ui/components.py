"""
Brand Rule Lab — Reusable UI Components
Owned by Agent A4 (Frontend & UX Engineer).
"""

from __future__ import annotations
import difflib
import html
from typing import List, Optional
import streamlit as st
from core.models import AssetStatus, DriftStatus, Finding, FindingKind, LinkState, Severity


def render_status_badge(status: AssetStatus | str) -> str:
    """Return HTML status badge with text and colour."""
    status_str = status.value if isinstance(status, AssetStatus) else str(status)
    css_class = {
        "ready_for_review": "badge-ready",
        "changes_requested": "badge-changes",
        "approved": "badge-approved",
        "escalated": "badge-escalated",
        "draft": "badge-ready",
    }.get(status_str, "badge-ready")

    label = status_str.replace("_", " ").title()
    return f'<span class="badge-pill {css_class}">{label}</span>'


def render_state_chip(state: DriftStatus | LinkState | str, tooltip: str = "") -> str:
    """Return HTML state chip with tooltip."""
    state_str = state.value if hasattr(state, "value") else str(state)
    css_class = {
        "CURRENT": "chip-current",
        "REVIEW_REQUIRED": "chip-review-required",
        "EXPIRED": "chip-expired",
        "UNLINKED": "chip-unlinked",
        "LINKED": "chip-current",
        "NOT_OBSERVED": "chip-not-observed",
    }.get(state_str, "chip-unlinked")

    title_attr = f'title="{html.escape(tooltip)}"' if tooltip else ""
    return f'<span class="chip-state {css_class}" {title_attr}>{state_str}</span>'


def render_diff_html(original: str, rewrite: str) -> str:
    """Render inline word-level diff HTML between original and rewrite."""
    orig_words = original.split()
    rewr_words = rewrite.split()

    matcher = difflib.SequenceMatcher(None, orig_words, rewr_words)
    diff_chunks = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            diff_chunks.append(" ".join(orig_words[i1:i2]))
        elif tag == "delete":
            diff_chunks.append(f'<span class="diff-del">{" ".join(orig_words[i1:i2])}</span>')
        elif tag == "insert":
            diff_chunks.append(f'<span class="diff-add">{" ".join(rewr_words[j1:j2])}</span>')
        elif tag == "replace":
            diff_chunks.append(f'<span class="diff-del">{" ".join(orig_words[i1:i2])}</span>')
            diff_chunks.append(f'<span class="diff-add">{" ".join(rewr_words[j1:j2])}</span>')

    return f'<div class="diff-box">{" ".join(diff_chunks)}</div>'


def render_annotated_draft(text: str, findings: List[Finding]) -> str:
    """
    Render draft text with highlighted span markers and numbered labels.
    Non-overlapping span replacement.
    """
    if not findings:
        return f'<div class="brand-card" style="white-space: pre-wrap;">{html.escape(text)}</div>'

    # Sort findings by span_start
    sorted_findings = sorted(findings, key=lambda x: x.span_start)
    html_out = []
    last_idx = 0

    for idx, f in enumerate(sorted_findings, 1):
        # Text before finding
        if f.span_start > last_idx:
            html_out.append(html.escape(text[last_idx:f.span_start]))

        # Highlighted span
        kind_color = {
            FindingKind.TONE: "#FFE0B2",        # soft orange
            FindingKind.TERMINOLOGY: "#FFCDD2", # soft red
            FindingKind.CLAIM: "#E1BEE7",       # soft purple
            FindingKind.OFFER_DATE: "#FFF9C4",  # soft yellow
            FindingKind.ACCESSIBILITY: "#B2DFDB",# soft teal
            FindingKind.VISUAL_TEXT: "#CFD8DC", # soft blue-grey
        }.get(f.kind, "#FFF3E0")

        span_content = html.escape(f.source_text)
        badge = f'<sup style="background:#13171A; color:#FFF; padding:1px 5px; border-radius:10px; font-size:0.65rem;">{idx}</sup>'
        html_out.append(
            f'<mark style="background-color: {kind_color}; padding: 2px 4px; border-radius: 4px; border: 1px solid #B0BEC5;">'
            f'{span_content} {badge}'
            f'</mark>'
        )
        last_idx = max(last_idx, f.span_end)

    if last_idx < len(text):
        html_out.append(html.escape(text[last_idx:]))

    rendered_body = "".join(html_out)
    return f'<div class="brand-card" style="font-size: 1.05rem; line-height: 1.65; white-space: pre-wrap;">{rendered_body}</div>'
