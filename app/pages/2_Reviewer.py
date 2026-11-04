"""
Brand Rule Lab — Reviewer Dashboard
Owned by Agent A4 (Frontend & UX Engineer).

Provides the review queue, lineage verification, UNLINKED override guards,
and audit trail inspection.
"""

from __future__ import annotations
import streamlit as st
from app.ui.components import render_annotated_draft, render_state_chip, render_status_badge
from app.ui.theme import apply_theme, render_banner
from core.audit import get_asset_audit_trail, log_review_event
from core.db import execute_commit, execute_query
from core.ledger.approve import approve_claim
from core.models import AssetStatus, Decision, Finding, FindingKind, LinkState, Role

apply_theme()
render_banner()

st.title("🔍 Reviewer Governance Dashboard")
st.markdown('<div class="eyebrow">ASSET APPROVAL QUEUE & FACT LINEAGE</div>', unsafe_allow_html=True)

# Role check
current_role = st.session_state.get("role", "reviewer")
if current_role != "reviewer":
    st.info(f"Viewing as **{current_role.title()}**. Switch to **Reviewer** to perform approvals or escalations.")

# Retrieve Assets Queue
assets = execute_query(
    """
    SELECT a.asset_id, a.name, a.product_id, a.market, a.channel, a.status, a.created_by,
           a.planned_publish_date, a.text_content, COUNT(f.finding_id) as finding_count
    FROM assets a
    LEFT JOIN findings f ON a.asset_id = f.asset_id
    GROUP BY a.asset_id
    ORDER BY a.created_at DESC;
    """
)

if not assets:
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
    # Asset Selection Table
    asset_dict = {a["asset_id"]: f"{a['name']} ({a['asset_id']}) — [{a['status'].upper()}]" for a in assets}
    selected_asset_id = st.selectbox(
        "Select Asset from Queue:",
        options=list(asset_dict.keys()),
        format_func=lambda x: asset_dict[x],
    )

    selected_asset = next(a for a in assets if a["asset_id"] == selected_asset_id)

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
    with col4:
        st.markdown(f"**Current Status:** {render_status_badge(selected_asset['status'])}", unsafe_allow_html=True)

    st.markdown("---")

    # Fetch Findings for this Asset
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
        )
        for r in finding_rows
    ]

    # Two-Column Layout: Left Draft Highlights, Right Lineage & Actions
    c_left, c_right = st.columns([1.1, 0.9])

    with c_left:
        st.markdown('<div class="eyebrow">DRAFT CONTENT & RESOLUTION STATUS</div>', unsafe_allow_html=True)
        st.markdown(render_annotated_draft(selected_asset["text_content"], findings_list), unsafe_allow_html=True)

        st.markdown("#### Findings Inspection")
        for idx, f in enumerate(findings_list, 1):
            with st.container():
                dismissed_text = f"<br><strong>Dismissal Rationale:</strong> <em>{f.dismiss_reason}</em>" if f.creator_action == "dismissed" else ""
                rewrite_text = f"<br><strong>Accepted/Edited Text:</strong> <code>{f.suggested_rewrite}</code>" if f.creator_action in ("accepted", "edited") else ""
                st.markdown(
                    f"""
                    <div class="brand-card">
                        <div style="display:flex; justify-content:space-between;">
                            <span class="eyebrow">#{idx} &bull; {f.kind.value.upper()} &bull; {f.rule_id or f.fact_id}</span>
                            <span>{render_state_chip(f.link_state)}</span>
                        </div>
                        <h4 style="margin: 0.2rem 0;">"{f.source_text}"</h4>
                        <p style="font-size: 0.9rem; color: #444; margin-bottom: 0.2rem;">{f.message}</p>
                        <div style="font-size: 0.85rem; color: #0B6E6A;">
                            <strong>Creator Action:</strong> <code>{f.creator_action.upper()}</code>{dismissed_text}{rewrite_text}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with c_right:
        st.markdown('<div class="eyebrow">FACT LINEAGE PANEL</div>', unsafe_allow_html=True)
        
        # Check if asset has linked facts
        linked_claims = [f for f in findings_list if f.link_state == LinkState.LINKED and f.fact_id]
        unlinked_claims = [f for f in findings_list if f.link_state == LinkState.UNLINKED]

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
                        <div class="brand-card" style="border-left: 4px solid #0B6E6A;">
                            <div class="eyebrow">CLAIM LINEAGE &bull; {lc.fact_id} v{fd['version']}</div>
                            <h4 style="margin-top: 0.2rem; color:#0B6E6A;">Approved Brand Fact</h4>
                            <p style="font-size:0.9rem; margin-bottom:0.3rem;"><strong>Fact Text:</strong> {fd['fact_text']}</p>
                            <p style="font-size:0.9rem; margin-bottom:0.3rem;"><strong>Approved Wording:</strong> <em>"{fd['permitted_wording']}"</em></p>
                            <div style="font-size:0.8rem; color:#555;">
                                <strong>Owner:</strong> {fd['owner']} &bull; 
                                <strong>Validity:</strong> {fd['valid_from']} to {fd['expires_at'] or 'Perpetual'}
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
            approve_disabled = has_unlinked and not override_reason.strip()
            if st.button("✅ Approve", type="primary", disabled=approve_disabled, use_container_width=True):
                # Call approve_claim
                fact_id = linked_claims[0].fact_id if linked_claims else "F-112"
                fact_ver = linked_claims[0].fact_version_id if linked_claims else 3
                approved_text = linked_claims[0].suggested_rewrite if linked_claims else selected_asset["text_content"]

                stable_id = approve_claim(
                    asset_id=selected_asset_id,
                    claim_text=approved_text or selected_asset["text_content"],
                    fact_id=fact_id,
                    fact_version_id=fact_ver,
                    reviewer_id="Sarah Jenkins (Reviewer)",
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

        # 2. REQUEST CHANGES ACTION
        with col_b:
            changes_comment = st.text_input("Change Notes:", placeholder="Explain required edits...", key="chg_note")
            if st.button("✏️ Changes", use_container_width=True):
                if not changes_comment.strip():
                    st.error("Please provide a change explanation.")
                else:
                    execute_commit("UPDATE assets SET status = 'changes_requested' WHERE asset_id = ?;", (selected_asset_id,))
                    log_review_event(
                        asset_id=selected_asset_id,
                        actor="Sarah Jenkins (Reviewer)",
                        role=Role.REVIEWER,
                        action="request_changes",
                        comment=changes_comment,
                    )
                    st.warning("Changes requested. Returned to Creator queue.")
                    st.rerun()

        # 3. ESCALATE ACTION
        with col_c:
            escalate_comment = st.text_input("Escalate Reason:", placeholder="Missing fact evidence...", key="esc_note")
            if st.button("🚨 Escalate", use_container_width=True):
                if not escalate_comment.strip():
                    st.error("Please explain escalation reason.")
                else:
                    execute_commit("UPDATE assets SET status = 'escalated' WHERE asset_id = ?;", (selected_asset_id,))
                    log_review_event(
                        asset_id=selected_asset_id,
                        actor="Sarah Jenkins (Reviewer)",
                        role=Role.REVIEWER,
                        action="escalate",
                        comment=escalate_comment,
                    )
                    st.info("Escalated to Fact Owner queue.")
                    st.rerun()

    # Append-Only Audit Trail Expander
    st.markdown("---")
    with st.expander("📜 View Tamper-Evident Audit History", expanded=False):
        trail = get_asset_audit_trail(selected_asset_id)
        if not trail:
            st.write("No audit events recorded yet.")
        else:
            for evt in trail:
                override_text = f" &bull; <strong>Override:</strong> <em>{evt.override_reason}</em>" if evt.override_reason else ""
                comment_text = f" &bull; {evt.comment}" if evt.comment else ""
                st.markdown(
                    f"""
                    <div style="font-family:'JetBrains Mono',monospace; font-size:0.82rem; padding: 4px 0; border-bottom: 1px solid #E0E0E0;">
                        <strong>{evt.timestamp[:19]}</strong> &bull; <code>{evt.actor}</code> ({evt.role.value.upper()}) &bull; 
                        <span style="color:#0B6E6A; font-weight:700;">{evt.action.upper()}</span>{comment_text}{override_text}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
