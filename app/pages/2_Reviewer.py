"""
Brand Rule Lab — Reviewer Dashboard
Owned by Agent A4 (Frontend & UX Engineer).

Provides the review queue, lineage verification, UNLINKED override guards,
and audit trail inspection.
"""

from __future__ import annotations
import streamlit as st
from app.ui.components import (
    format_age,
    get_reviewer_queue_data,
    has_column,
    render_annotated_draft,
    render_audit_event_item,
    render_reviewer_queue_table,
    render_state_chip,
    render_status_badge,
)
from app.ui.theme import apply_theme, render_banner, render_sidebar_role_switcher
from core.audit import get_asset_audit_trail, log_review_event
from core.db import execute_commit, execute_query
from core.ledger.approve import approve_claim, escalate_asset, request_changes
from core.models import AssetStatus, Decision, Finding, FindingKind, LinkState, Role

apply_theme()
render_banner()
current_role = render_sidebar_role_switcher()
is_reviewer = (current_role == "reviewer")

st.title("🔍 Reviewer Governance Dashboard")
st.markdown('<div class="eyebrow">ASSET APPROVAL QUEUE & FACT LINEAGE</div>', unsafe_allow_html=True)

# Role Boundary Notice
if not is_reviewer:
    st.warning(
        f"🚫 **Permission Denied:** You are currently viewing as **{current_role.title()}**. "
        "Under Brand Rule Lab governance rules, only the **Reviewer** persona can approve assets, "
        "request changes, or escalate evidence gaps. Use the sidebar to switch to Reviewer."
    )

# Retrieve Reviewer Queue Data
# Query all eligible assets awaiting review
queue_data = get_reviewer_queue_data(status_filter="ready_for_review")
if not queue_data:
    # Fallback to all queue assets if none currently ready_for_review
    queue_data = get_reviewer_queue_data(status_filter=None)

if not queue_data:
    st.markdown(
        """
        <div class="brand-card" style="text-align:center; padding: 2.5rem;">
            <h3>Queue is Empty</h3>
            <p style="color: #666;">No marketing assets are currently awaiting review.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    # 1. Reviewer Queue Overview Table
    st.markdown('<div class="eyebrow">REVIEWER QUEUE OVERVIEW &bull; AWAITING APPROVAL</div>', unsafe_allow_html=True)

    asset_ids = [a["asset_id"] for a in queue_data]
    current_selected = st.session_state.get("reviewer_selected_asset_id")
    if current_selected not in asset_ids:
        current_selected = asset_ids[0]

    # Render compact queue overview table
    st.markdown(
        render_reviewer_queue_table(queue_data, selected_asset_id=current_selected),
        unsafe_allow_html=True,
    )

    # 2. Asset Selector for Detail View
    selected_asset_id = st.selectbox(
        "Select Asset from Queue to Inspect / Review:",
        options=asset_ids,
        index=asset_ids.index(current_selected),
        format_func=lambda aid: next(
            f"{a['name']} ({a['asset_id']}) — {a['finding_count']} Findings [{a['status'].upper()}]"
            for a in queue_data if a["asset_id"] == aid
        ),
        key="reviewer_asset_selector",
    )
    st.session_state["reviewer_selected_asset_id"] = selected_asset_id

    selected_asset = next(a for a in queue_data if a["asset_id"] == selected_asset_id)

    # Asset Metadata Header Card
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**Asset ID:** `{selected_asset['asset_id']}`")
        st.markdown(f"**Creator:** {selected_asset['created_by']}")
    with col2:
        st.markdown(f"**Product:** `{selected_asset['product_id']}`")
        st.markdown(f"**Market / Channel:** {selected_asset['market']} / {selected_asset['channel']}")
    with col3:
        st.markdown(f"**Planned Publish:** {selected_asset['planned_publish_date']}")
        st.markdown(f"**Review Cycle:** `{selected_asset.get('review_cycle', 1) or 1}`")
    with col4:
        st.markdown(f"**Current Status:** {render_status_badge(selected_asset['status'])}", unsafe_allow_html=True)

    st.markdown("---")

    # Fetch Findings for this Asset (matching review cycle if schema supports it)
    asset_cycle = selected_asset.get("review_cycle", 1) or 1
    if has_column("findings", "review_cycle"):
        finding_rows = execute_query(
            "SELECT * FROM findings WHERE asset_id = ? AND review_cycle = ?;",
            (selected_asset_id, asset_cycle),
        )
        if not finding_rows:
            finding_rows = execute_query("SELECT * FROM findings WHERE asset_id = ?;", (selected_asset_id,))
    else:
        finding_rows = execute_query("SELECT * FROM findings WHERE asset_id = ?;", (selected_asset_id,))

    findings_list = [
        Finding(
            finding_id=r["finding_id"],
            asset_id=r["asset_id"],
            kind=FindingKind(r["kind"]),
            severity=r["severity"],
            span_start=r["span_start"],
            span_end=r["span_end"],
            source_text=r["source_text"],
            rule_id=r["rule_id"],
            fact_id=r["fact_id"],
            fact_version_id=r["fact_version_id"],
            link_state=LinkState(r["link_state"]),
            message=r["message"],
            next_step=r["next_step"],
            suggested_rewrite=r["suggested_rewrite"],
            creator_action=r["creator_action"],
            dismiss_reason=r["dismiss_reason"],
            review_cycle=r["review_cycle"] if ("review_cycle" in r.keys() and r["review_cycle"] is not None) else 1,
        )
        for r in finding_rows
    ]

    # Two-Column Layout: Left Draft Highlights, Right Lineage & Actions
    c_left, c_right = st.columns([1.1, 0.9])

    with c_left:
        st.markdown('<div class="eyebrow">SUBMITTED DRAFT COPY (ANNOTATED SPANS)</div>', unsafe_allow_html=True)
        st.markdown(
            render_annotated_draft(selected_asset["text_content"], findings_list),
            unsafe_allow_html=True,
        )

        st.markdown("#### Findings Inspection & Creator Resolutions")
        for idx, f in enumerate(findings_list, 1):
            with st.container():
                dismissed_text = f"<br><strong style='color:#F59E0B;'>Dismissal Rationale:</strong> <em>{f.dismiss_reason}</em>" if f.creator_action == "dismissed" else ""
                rewrite_text = f"<br><strong style='color:#C6F432;'>Accepted/Edited Text:</strong> <code class='mono-id'>{f.suggested_rewrite}</code>" if f.creator_action in ("accepted", "edited") else ""
                st.markdown(
                    f"""
                    <div class="brand-card" id="card-{f.finding_id}" style="border-left: 3px solid {'#EF4444' if f.severity == 'block' else '#F59E0B'};">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span class="eyebrow">
                                <a href="#span-{f.finding_id}" style="color:#C6F432; text-decoration:none;" title="Click to navigate to span in draft">
                                    #{idx} &bull; {f.kind.value.upper()} &bull; {f.rule_id or f.fact_id}
                                </a>
                            </span>
                            <span>{render_state_chip(f.link_state)}</span>
                        </div>
                        <h4 style="margin: 0.3rem 0; color: #FFFFFF;">
                            <a href="#span-{f.finding_id}" style="color:#FFFFFF; text-decoration:none;" title="Click to jump to annotated span in draft">
                                "{f.source_text}"
                            </a>
                        </h4>
                        <p style="font-size: 0.9rem; color: #D4D4D8; margin-bottom: 0.3rem;">{f.message}</p>
                        <div style="font-size: 0.85rem; color: #C6F432;">
                            <strong style="color:#FFFFFF;">Creator Action:</strong> <code class="mono-id">{f.creator_action.upper()}</code>{dismissed_text}{rewrite_text}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with c_right:
        st.markdown('<div class="eyebrow">FACT LINEAGE PANEL</div>', unsafe_allow_html=True)
        
        # Check if asset has linked facts
        linked_claims = [f for f in findings_list if f.link_state == LinkState.LINKED and f.fact_id]
        unlinked_claims = [
            f for f in findings_list
            if f.link_state == LinkState.UNLINKED and (
                f.kind == FindingKind.CLAIM or f.creator_action in ("dismissed", "pending")
            )
        ]

        if linked_claims:
            for lc in linked_claims:
                fact_data = execute_query(
                    "SELECT * FROM fact_versions WHERE fact_id = ? AND version = ?;",
                    (lc.fact_id, lc.fact_version_id or 3),
                )
                if fact_data:
                    fd = fact_data[0]
                    st.markdown(
                        f"""
                        <div class="brand-card" style="border-left: 4px solid #C6F432;">
                            <div class="eyebrow">CLAIM LINEAGE &bull; {lc.fact_id} v{fd['version']}</div>
                            <h4 style="margin-top: 0.2rem; color:#C6F432;">Approved Brand Fact</h4>
                            <p style="font-size:0.9rem; margin-bottom:0.3rem; color:#E4E4E7;"><strong style="color:#FFFFFF;">Fact Text:</strong> {fd['fact_text']}</p>
                            <p style="font-size:0.9rem; margin-bottom:0.3rem; color:#D4D4D8;"><strong style="color:#FFFFFF;">Approved Wording:</strong> <em style="color:#C6F432;">"{fd['permitted_wording']}"</em></p>
                            <div style="font-size:0.8rem; color:#A1A1AA;">
                                <strong style="color:#FFFFFF;">Owner:</strong> {fd['owner']} &bull; 
                                <strong style="color:#FFFFFF;">Validity:</strong> {fd['valid_from']} to {fd['expires_at'] or 'Perpetual'}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No approved brand facts linked to this asset.")

        # Reviewer Governance Decision Actions
        st.markdown('<div class="eyebrow">REVIEWER DECISION</div>', unsafe_allow_html=True)
        
        has_unlinked = len(unlinked_claims) > 0
        override_reason = ""

        if has_unlinked:
            st.warning(f"⚠️ **UNLINKED Claims Present:** This draft contains {len(unlinked_claims)} unlinked claims. Under corporate compliance rules, approval is disabled unless an explicit legal override reason is recorded.")
            override_reason = st.text_input(
                "Mandatory UNLINKED Override Justification:",
                placeholder="e.g. Substantiated by external lab report #1042-B; legal counsel approved.",
            )

        col_a, col_b, col_c = st.columns(3)

        # 1. APPROVE ACTION
        with col_a:
            approve_disabled = (not is_reviewer) or (has_unlinked and not override_reason.strip())
            approve_help = "Disabled: Switch to Reviewer persona in sidebar" if not is_reviewer else ("Disabled: Record UNLINKED justification first" if (has_unlinked and not override_reason.strip()) else None)
            if st.button("✅ Approve", type="primary", disabled=approve_disabled, help=approve_help, use_container_width=True):
                if not is_reviewer:
                    st.error(f"Permission Denied: Role '{current_role}' is not permitted to approve assets.")
                else:
                    fact_id = linked_claims[0].fact_id if linked_claims else "F-112"
                    fact_ver = linked_claims[0].fact_version_id if linked_claims else 3
                    approved_text = linked_claims[0].suggested_rewrite if linked_claims else selected_asset["text_content"]

                    try:
                        stable_id = approve_claim(
                            asset_id=selected_asset_id,
                            claim_text=approved_text or selected_asset["text_content"],
                            fact_id=fact_id,
                            fact_version_id=fact_ver,
                            reviewer_id="Sarah Jenkins (Reviewer)",
                            role=current_role,
                        )

                        if override_reason.strip():
                            log_review_event(
                                asset_id=selected_asset_id,
                                actor="Sarah Jenkins (Reviewer)",
                                role=Role.REVIEWER,
                                action="unlinked_override",
                                override_reason=override_reason,
                            )

                        st.success(f"Approved! Minted stable claim: `{stable_id}` tied to `{fact_id} v{fact_ver}`.")
                        st.balloons()
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Approval failed: {ex}")

        # 2. REQUEST CHANGES ACTION
        with col_b:
            changes_comment = st.text_input("Change Notes:", placeholder="Explain required edits...", key="chg_note")
            if st.button("✏️ Changes", disabled=not is_reviewer, help=None if is_reviewer else "Disabled: Switch to Reviewer persona in sidebar", use_container_width=True):
                if not is_reviewer:
                    st.error(f"Permission Denied: Role '{current_role}' is not permitted to request changes.")
                elif not changes_comment.strip():
                    st.error("Please provide a change explanation.")
                else:
                    try:
                        request_changes(
                            asset_id=selected_asset_id,
                            comment=changes_comment,
                            actor="Sarah Jenkins (Reviewer)",
                            role=current_role,
                        )
                        st.warning("Changes requested. Returned to Creator queue.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Failed to request changes: {ex}")

        # 3. ESCALATE ACTION
        with col_c:
            escalate_comment = st.text_input("Escalate Reason:", placeholder="Missing fact evidence...", key="esc_note")
            if st.button("🚨 Escalate", disabled=not is_reviewer, help=None if is_reviewer else "Disabled: Switch to Reviewer persona in sidebar", use_container_width=True):
                if not is_reviewer:
                    st.error(f"Permission Denied: Role '{current_role}' is not permitted to escalate findings.")
                elif not escalate_comment.strip():
                    st.error("Please explain escalation reason.")
                else:
                    try:
                        escalate_asset(
                            asset_id=selected_asset_id,
                            comment=escalate_comment,
                            actor="Sarah Jenkins (Reviewer)",
                            role=current_role,
                        )
                        st.info("Escalated to Fact Owner queue.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Failed to escalate: {ex}")

    # Append-Only Audit Trail Expander
    st.markdown("---")
    with st.expander("📜 View Tamper-Evident Audit History", expanded=False):
        trail = get_asset_audit_trail(selected_asset_id)
        if not trail:
            st.write("No audit events recorded yet.")
        else:
            for evt in trail:
                st.markdown(render_audit_event_item(evt), unsafe_allow_html=True)
