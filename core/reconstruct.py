"""
Brand Rule Lab — Submitted Copy Reconstruction Utility
Owned by Agent A1 & A4.

Reconstructs the effective submitted marketing text by applying accepted and custom-edited
finding rewrites to their exact character spans in reverse offset order.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from core.models import Finding
from core.snapshots import get_original_snapshot


def get_reconstruction_base_text(
    asset_id: Optional[str],
    doc_text: str,
    findings: List[Finding],
    db_path: Optional[str] = None,
) -> str:
    """
    Determine the correct base text for span replacement.
    If an immutable original snapshot exists and findings spans match it, use original snapshot text.
    Otherwise use doc_text.
    """
    if not asset_id:
        return doc_text
    orig_snap = get_original_snapshot(asset_id, db_path=db_path)
    if orig_snap and orig_snap.get("original_text"):
        ot = orig_snap["original_text"]
        if any(0 <= f.span_start < f.span_end <= len(ot) and ot[f.span_start:f.span_end] == f.source_text for f in findings):
            return ot
    return doc_text


def reconstruct_submitted_text(
    original_text: str,
    findings: List[Finding],
    actions: Dict[str, Any],
) -> str:
    """
    Reconstruct the effective submitted draft text by applying accepted or edited
    replacements to their exact character spans in reverse offset order.
    Findings that are dismissed or pending retain their original text.
    """
    replacements = []
    for f in findings:
        act = actions.get(f.finding_id, {})
        action_type = act.get("action")
        if action_type in ("accepted", "edited"):
            rep_text = act.get("text")
            if rep_text is not None and rep_text != f.source_text:
                replacements.append((f.span_start, f.span_end, rep_text))

    # Sort descending by start span so earlier string slices remain valid as text is replaced
    replacements.sort(key=lambda x: x[0], reverse=True)

    reconstructed = original_text
    for start, end, rep_text in replacements:
        reconstructed = reconstructed[:start] + rep_text + reconstructed[end:]

    return reconstructed
