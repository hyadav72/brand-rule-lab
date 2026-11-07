"""
Brand Rule Lab — Reusable UI Components
Owned by Agent A4 (Frontend & UX Engineer).
"""

from __future__ import annotations
from datetime import datetime
import difflib
import html
from typing import Any, Dict, List, Optional
import streamlit as st
from core.db import execute_query
from core.models import AssetStatus, DriftStatus, Finding, FindingKind, LinkState, ReviewEvent, Severity


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
    """
    Return HTML state chip with accessible tooltip defining the state.
    Provides canonical definitions for CURRENT, REVIEW_REQUIRED, EXPIRED, UNLINKED, NOT_OBSERVED.
    """
    state_str = state.value if hasattr(state, "value") else str(state)
    css_class = {
        "CURRENT": "chip-current",
        "REVIEW_REQUIRED": "chip-review-required",
        "EXPIRED": "chip-expired",
        "UNLINKED": "chip-unlinked",
        "LINKED": "chip-current",
        "NOT_OBSERVED": "chip-not-observed",
    }.get(state_str, "chip-unlinked")

    STATE_DEFINITIONS = {
        "CURRENT": "Claim is actively verified against an approved, non-expired brand fact version.",
        "REVIEW_REQUIRED": "Underlying fact version has changed; claim must be re-evaluated for brand compliance.",
        "EXPIRED": "Underlying fact version has passed its expiry date; substantiation is no longer valid.",
        "UNLINKED": "Claim has no verified matching approved brand fact in the factual ledger.",
        "LINKED": "Claim is officially linked to an approved fact version.",
        "NOT_OBSERVED": "Unregistered live copy outside Brand Rule Lab recorded coverage boundaries.",
    }
    tip = tooltip or STATE_DEFINITIONS.get(state_str, "")
    title_attr = f'title="{html.escape(tip)}"' if tip else ""
    aria_attr = f'aria-label="{html.escape(f"{state_str}: {tip}")}"' if tip else ""
    return f'<span class="chip-state {css_class}" {title_attr} {aria_attr} tabindex="0">{state_str}</span>'


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


def format_age(
    created_at: Optional[str | datetime],
    reference_time: Optional[datetime] = None,
) -> str:
    """
    Calculate and format human-readable age from a database timestamp.
    Returns truthful fallback '—' if created_at is missing, empty, or unparseable.
    """
    if not created_at:
        return "—"

    if isinstance(created_at, datetime):
        dt = created_at
    else:
        created_str = str(created_at).strip()
        if not created_str or created_str.lower() in ("none", "null", "—"):
            return "—"
        try:
            clean_ts = created_str.replace("T", " ")
            if "." in clean_ts:
                clean_ts = clean_ts.split(".")[0]
            dt = datetime.strptime(clean_ts[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return "—"

    ref = reference_time or datetime.now()
    diff = ref - dt
    total_seconds = int(diff.total_seconds())

    if total_seconds < 0:
        return "Just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def has_column(table_name: str, column_name: str, db_path: Optional[str] = None) -> bool:
    """Check if a table contains a specific column in the given database."""
    try:
        rows = execute_query(f"PRAGMA table_info({table_name});", db_path=db_path)
        return any(
            (r["name"] if hasattr(r, "keys") and "name" in r.keys() else (r[1] if isinstance(r, (tuple, list)) else str(r))) == column_name
            for r in rows
        )
    except Exception:
        return False


def get_reviewer_queue_data(
    status_filter: Optional[str] = "ready_for_review",
    db_path: Optional[str] = None,
    reference_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve eligible assets awaiting review with findings counts, owner, and calculated age.
    Compatible with both protected unmigrated production schema (lacking review_cycle)
    and migrated/disposable schemas (possessing review_cycle).
    """
    where_clause = ""
    params: list[Any] = []
    if status_filter and status_filter.upper() != "ALL":
        where_clause = "WHERE a.status = ?"
        params.append(status_filter)

    has_asset_cycle = has_column("assets", "review_cycle", db_path=db_path)
    has_finding_cycle = has_column("findings", "review_cycle", db_path=db_path)

    if has_asset_cycle and has_finding_cycle:
        query = f"""
        SELECT a.asset_id, a.name, a.product_id, a.market, a.channel, a.status, a.created_by,
               a.planned_publish_date, a.text_content, a.review_cycle, a.created_at,
               COUNT(f.finding_id) as finding_count
        FROM assets a
        LEFT JOIN findings f ON a.asset_id = f.asset_id AND f.review_cycle = a.review_cycle
        {where_clause}
        GROUP BY a.asset_id
        ORDER BY a.created_at DESC;
        """
    else:
        # Schema-compatible query for protected production database lacking review_cycle
        query = f"""
        SELECT a.asset_id, a.name, a.product_id, a.market, a.channel, a.status, a.created_by,
               a.planned_publish_date, a.text_content, a.created_at,
               COUNT(f.finding_id) as finding_count
        FROM assets a
        LEFT JOIN findings f ON a.asset_id = f.asset_id
        {where_clause}
        GROUP BY a.asset_id
        ORDER BY a.created_at DESC;
        """

    rows = execute_query(query, tuple(params), db_path=db_path)
    result = []
    for r in rows:
        d = dict(r)
        d["owner"] = d.get("created_by") or "Unassigned"
        d["age"] = format_age(d.get("created_at"), reference_time=reference_time)
        d["finding_count"] = d.get("finding_count") or 0
        d["review_cycle"] = d.get("review_cycle", 1) or 1
        d["asset_label"] = f"{d.get('name', 'Untitled')} ({d.get('asset_id')})"
        result.append(d)
    return result


def render_reviewer_queue_table(
    queue_data: List[Dict[str, Any]],
    selected_asset_id: Optional[str] = None,
) -> str:
    """Render compact HTML queue overview table with Asset, Findings, Status, Owner, and Age."""
    if not queue_data:
        return '<div class="brand-card" style="text-align:center; padding: 1.5rem; color:var(--text-secondary);">No assets awaiting review in queue.</div>'

    rows_html = []
    for item in queue_data:
        aid = html.escape(str(item.get("asset_id", "—")))
        name = html.escape(str(item.get("name", "Untitled Asset")))
        f_cnt = item.get("finding_count", 0)
        status = item.get("status", "ready_for_review")
        owner = html.escape(str(item.get("owner") or item.get("created_by") or "Unassigned"))
        age = html.escape(str(item.get("age", "—")))

        is_selected = (selected_asset_id == item.get("asset_id"))
        row_class = "selected-row" if is_selected else ""
        row_style = "background-color: var(--nav-active-bg); font-weight: 600;" if is_selected else ""
        selected_marker = ' <span style="color:var(--accent-text); font-weight:700;">👈 Active</span>' if is_selected else ""

        status_badge = render_status_badge(status)

        rows_html.append(
            f'<tr class="{row_class}" style="border-bottom: 1px solid var(--border-subtle); {row_style}">'
            f'<td style="padding: 10px 14px;"><strong style="color:var(--text-primary);">{name}</strong><br><code class="mono-id">{aid}</code>{selected_marker}</td>'
            f'<td style="padding: 10px 14px; text-align: center;"><span style="font-size:1.15rem; font-weight:800; color:var(--accent-text);">{f_cnt}</span></td>'
            f'<td style="padding: 10px 14px;">{status_badge}</td>'
            f'<td style="padding: 10px 14px; color:var(--text-secondary);">{owner}</td>'
            f'<td style="padding: 10px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.82rem; color:var(--text-muted);">{age}</td>'
            f'</tr>'
        )

    tbody = "".join(rows_html)
    return (
        f'<div class="brand-card" style="padding: 0; overflow-x: auto; margin-bottom: 1rem; border: 1px solid var(--border-subtle); border-radius: 14px; background: var(--bg-card);">'
        f'<table class="queue-table" style="width: 100%; border-collapse: collapse; font-size: 0.9rem; text-align: left;">'
        f'<thead>'
        f'<tr style="background: var(--table-header-bg); border-bottom: 2px solid var(--border-subtle);">'
        f'<th style="padding: 12px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; text-transform:uppercase; color:var(--accent-text); letter-spacing:0.08em;">Asset</th>'
        f'<th style="padding: 12px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; text-transform:uppercase; color:var(--accent-text); letter-spacing:0.08em; text-align:center;">Findings</th>'
        f'<th style="padding: 12px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; text-transform:uppercase; color:var(--accent-text); letter-spacing:0.08em;">Status</th>'
        f'<th style="padding: 12px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; text-transform:uppercase; color:var(--accent-text); letter-spacing:0.08em;">Owner</th>'
        f'<th style="padding: 12px 14px; font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; text-transform:uppercase; color:var(--accent-text); letter-spacing:0.08em;">Age</th>'
        f'</tr>'
        f'</thead>'
        f'<tbody>{tbody}</tbody>'
        f'</table>'
        f'</div>'
    )


def _extract_field(item: Any, attr: str, default: Any = None) -> Any:
    """Safely extract field from dict, sqlite3.Row, or object model."""
    if isinstance(item, dict):
        return item.get(attr, default)
    if hasattr(item, "keys") and hasattr(item, "__getitem__"):
        try:
            val = item[attr]
            return val if val is not None else default
        except (KeyError, IndexError):
            return default
    return getattr(item, attr, default)


def render_annotated_draft(text: str, findings: Optional[List[Any]]) -> str:
    """
    Render draft text with highlighted span markers and numbered labels.
    Safely handles overlapping, nested, duplicate, and invalid spans without
    crashing and without altering draft text or finding offsets.
    Provides anchor IDs for bi-directional navigation between spans and finding cards.
    """
    if not text:
        return '<div class="brand-card" style="font-size: 1.05rem; line-height: 1.65; white-space: pre-wrap;"></div>'
    if not findings:
        return f'<div class="brand-card" style="font-size: 1.05rem; line-height: 1.65; white-space: pre-wrap;">{html.escape(text)}</div>'

    L = len(text)
    valid_findings = []
    for idx, f in enumerate(findings, 1):
        fid = _extract_field(f, "finding_id", f"FND-{idx}")
        start = _extract_field(f, "span_start")
        end = _extract_field(f, "span_end")
        kind = _extract_field(f, "kind", "claim")
        rule_or_fact = _extract_field(f, "rule_id") or _extract_field(f, "fact_id")

        if hasattr(kind, "value"):
            kind_str = kind.value
        else:
            kind_str = str(kind) if kind is not None else "claim"

        # Validate span offsets
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 0 or start >= L or end <= start:
            continue

        clamped_end = min(end, L)
        valid_findings.append({
            "idx": idx,
            "finding_id": str(fid),
            "start": start,
            "end": clamped_end,
            "kind": kind_str.lower(),
            "rule_or_fact": str(rule_or_fact) if rule_or_fact else "",
        })

    if not valid_findings:
        return f'<div class="brand-card" style="font-size: 1.05rem; line-height: 1.65; white-space: pre-wrap;">{html.escape(text)}</div>'

    kind_colors = {
        "tone": "#FFE0B2",        # soft orange
        "terminology": "#FFCDD2", # soft red
        "claim": "#E1BEE7",       # soft purple
        "offer_date": "#FFF9C4",  # soft yellow
        "accessibility": "#B2DFDB",# soft teal
        "visual_text": "#CFD8DC", # soft blue-grey
    }

    # Collect all unique boundary points within [0, L]
    pts = sorted(set([0, L] + [f["start"] for f in valid_findings] + [f["end"] for f in valid_findings]))
    html_out = []

    for p1, p2 in zip(pts[:-1], pts[1:]):
        seg = text[p1:p2]
        active = [f for f in valid_findings if f["start"] <= p1 and p2 <= f["end"]]
        if not active:
            html_out.append(html.escape(seg))
        else:
            # Emit anchor target for any finding that starts at this exact boundary p1
            anchors = "".join([f'<span id="span-{f["finding_id"]}" class="finding-anchor"></span>' for f in active if f["start"] == p1])

            # Innermost / most specific finding determines the highlight background color
            active_sorted = sorted(active, key=lambda x: (x["end"] - x["start"]))
            innermost = active_sorted[0]
            color = kind_colors.get(innermost["kind"], "#FFE0B2")

            # Check if any findings end at this exact boundary p2
            ending = [f for f in active if f["end"] == p2]
            badges = []
            for ef in sorted(ending, key=lambda x: x["idx"]):
                badges.append(
                    f'<sup style="background:var(--bg-canvas); color:var(--accent-text); font-weight:800; border:1px solid var(--accent); padding:1px 6px; border-radius:10px; font-size:0.68rem; margin-left:3px; font-family:\'JetBrains Mono\',monospace;">'
                    f'<a href="#card-{ef["finding_id"]}" style="color:var(--accent-text); text-decoration:none;" title="Click to view Finding #{ef["idx"]} ({ef["rule_or_fact"]})">{ef["idx"]}</a>'
                    f'</sup>'
                )
            badge_html = (" " + "".join(badges)) if badges else ""

            # Tooltip for the span
            title_text = f"Finding #{innermost['idx']} • {innermost['kind'].upper()} • {innermost['rule_or_fact']}"
            html_out.append(
                f'{anchors}<mark class="annotated-span" title="{html.escape(title_text)}" style="background-color: {color}; color: #0B0B0C; font-weight: 500; padding: 2px 6px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.2);">'
                f'{html.escape(seg)}{badge_html}</mark>'
            )

    rendered_body = "".join(html_out)
    return (
        f'<div class="brand-card" style="font-size: 1.05rem; line-height: 1.7; white-space: pre-wrap; border-left: 4px solid var(--accent); background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-subtle);">'
        f'{rendered_body}'
        f'</div>'
    )


def render_audit_event_item(evt: ReviewEvent) -> str:
    """
    Render a single audit trail entry to HTML with truthful provenance display.
    If finding-level provenance is unavailable, displays the truthful fallback 'Asset-level event'.
    """
    actor_str = html.escape(str(evt.actor))
    role_str = html.escape(str(evt.role.value.upper() if hasattr(evt.role, "value") else str(evt.role).upper()))
    action_str = html.escape(str(evt.action).upper())
    ts_str = html.escape(str(evt.timestamp)[:19])

    override_text = f" &bull; <strong>Override:</strong> <em style='color:#F59E0B;'>{html.escape(str(evt.override_reason))}</em>" if evt.override_reason else ""
    comment_text = f" &bull; <span style='color:var(--text-secondary);'>{html.escape(str(evt.comment))}</span>" if evt.comment else ""
    prov_badge = f" &bull; <span style='font-size:0.72rem; background:var(--bg-card-elevated); color:var(--accent-text); border:1px solid var(--border-subtle); padding:2px 6px; border-radius:4px;'>{html.escape(str(evt.provenance))}</span>" if evt.provenance and evt.provenance != "USER_ACTION" else ""
    hist_bound = f" &bull; <span style='font-size:0.72rem; color:var(--text-muted);'>evidence: {html.escape(str(evt.known_before_timestamp)[:19])}</span>" if evt.known_before_timestamp else ""

    if evt.finding_id:
        scope_badge = f" &bull; <span style='font-size:0.72rem; background:var(--bg-card-elevated); color:var(--text-primary); border:1px solid var(--border-subtle); padding:2px 6px; border-radius:4px;'>Finding: {html.escape(str(evt.finding_id))}</span>"
    else:
        scope_badge = " &bull; <span style='font-size:0.72rem; color:var(--text-muted); background:var(--bg-card-elevated); border:1px solid var(--border-subtle); padding:2px 6px; border-radius:4px;'>Asset-level event</span>"

    return (
        f'<div class="audit-event-item" style="font-family:\'JetBrains Mono\',monospace; font-size:0.82rem; padding: 6px 0; border-bottom: 1px solid var(--border-subtle); color: var(--text-primary);">'
        f'<strong>{ts_str}</strong> &bull; <code class="mono-id">{actor_str}</code> <span style="color:var(--text-muted);">({role_str})</span> &bull; '
        f'<span style="color:var(--accent-text); font-weight:700;">{action_str}</span>{scope_badge}{comment_text}{override_text}{prov_badge}{hist_bound}'
        f'</div>'
    )
