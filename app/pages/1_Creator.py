"""
Brand Rule Lab — Creator Workspace
Owned by Agent A4 (Frontend & UX Engineer).

Allows creators to upload marketing drafts, review highlighted findings,
accept/edit/dismiss suggested rewrites, and submit for reviewer approval.
"""

from __future__ import annotations
import uuid
import streamlit as st
from app.ui.components import render_annotated_draft, render_diff_html, render_status_badge
from app.ui.theme import apply_theme, render_banner
from core.audit import log_review_event
from core.db import execute_commit, execute_query
from core.extract.claims import extract_claims
from core.ingest import ingest
from core.lookup.facts import lookup_facts
from core.models import AssetStatus, CreatorActionState, ExtractedDoc, Finding, FindingKind, LinkState, Role, Severity
from core.rules.engine import RuleEngine

apply_theme()
render_banner()

DEMO_COPY = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."

st.title("✍️ Creator Review Workspace")
st.markdown('<div class="eyebrow">PRE-PUBLICATION BRAND COMPLIANCE AUDIT</div>', unsafe_allow_html=True)

# Role check
current_role = st.session_state.get("role", "creator")
if current_role != "creator":
    st.info(f"You are currently viewing as **{current_role.title()}**. Switch to **Creator** role to submit drafts.")

# Setup Session State for Active Asset & Findings
if "active_asset_id" not in st.session_state:
    st.session_state["active_asset_id"] = None
if "active_doc" not in st.session_state:
    st.session_state["active_doc"] = None
if "findings" not in st.session_state:
    st.session_state["findings"] = []
if "finding_actions" not in st.session_state:
    st.session_state["finding_actions"] = {}

# Upload & Configuration Form
with st.expander("📄 Upload or Load Marketing Draft", expanded=st.session_state["active_doc"] is None):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        products = execute_query("SELECT product_id, name FROM products;")
        prod_options = {p["product_id"]: p["name"] for p in products} or {"prod_monsoon": "Monsoon Clear Skin"}
        selected_prod = st.selectbox("Product", options=list(prod_options.keys()), format_func=lambda x: prod_options[x])
    with c2:
        selected_market = st.selectbox("Market", options=["US", "UK", "EU", "CA"])
    with c3:
        selected_channel = st.selectbox("Channel", options=["paid_social", "organic_social", "email", "pdp", "banner"])
    with c4:
        planned_date = st.date_input("Planned Publishing Date", value=None)

    uploaded_file = st.file_uploader(
        "Upload Draft (PDF, DOCX, TXT, PNG, JPG)",
        type=["txt", "docx", "pdf", "png", "jpg", "jpeg", "md"],
        help="Maximum file size 10 MB.",
    )

    st.markdown("**— OR —**")
    if st.button("🚀 Load Hackathon Demo Draft (Monsoon Clear Skin)", type="primary"):
        demo_bytes = DEMO_COPY.encode("utf-8")
        doc = ingest(demo_bytes, "monsoon_social_caption.txt")
        asset_id = f"AST-{uuid.uuid4().hex[:6]}"
        
        # Extract claims & run rules
        engine = RuleEngine()
        claims = extract_claims(doc.text, product_hint=prod_options.get(selected_prod, "Monsoon Clear Skin"))
        context = {
            "asset_id": asset_id,
            "product": selected_prod,
            "market": selected_market,
            "channel": selected_channel,
            "planned_publish_date": str(planned_date) if planned_date else "2026-11-10",
        }
        findings = engine.run_rules(doc, claims, context)

        # Store in session state
        st.session_state["active_asset_id"] = asset_id
        st.session_state["active_doc"] = doc
        st.session_state["findings"] = findings
        st.session_state["finding_actions"] = {f.finding_id: {"action": "pending", "text": f.suggested_rewrite} for f in findings}

        # Persist asset to DB
        execute_commit(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
            VALUES (?, ?, ?, ?, ?, 'draft', 'Alex Chen (Creator)', ?, ?, ?);
            """,
            (asset_id, "Monsoon Clear Skin Paid Social Caption", selected_prod, selected_market, selected_channel, doc.source_hash, doc.text, str(planned_date or "2026-11-10")),
        )
        st.rerun()

    if uploaded_file is not None and st.button("Analyze Uploaded File"):
        file_bytes = uploaded_file.read()
        doc = ingest(file_bytes, uploaded_file.name)
        asset_id = f"AST-{uuid.uuid4().hex[:6]}"
        
        engine = RuleEngine()
        claims = extract_claims(doc.text, product_hint=prod_options.get(selected_prod))
        context = {
            "asset_id": asset_id,
            "product": selected_prod,
            "market": selected_market,
            "channel": selected_channel,
            "planned_publish_date": str(planned_date) if planned_date else "2026-11-10",
        }
        findings = engine.run_rules(doc, claims, context)

        st.session_state["active_asset_id"] = asset_id
        st.session_state["active_doc"] = doc
        st.session_state["findings"] = findings
        st.session_state["finding_actions"] = {f.finding_id: {"action": "pending", "text": f.suggested_rewrite} for f in findings}

        execute_commit(
            """
            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
            VALUES (?, ?, ?, ?, ?, 'draft', 'Alex Chen (Creator)', ?, ?, ?);
            """,
            (asset_id, uploaded_file.name, selected_prod, selected_market, selected_channel, doc.source_hash, doc.text, str(planned_date or "2026-11-10")),
        )
        st.rerun()

# Display Audit Findings and Draft Highlights
if st.session_state["active_doc"]:
    doc: ExtractedDoc = st.session_state["active_doc"]
    findings: list[Finding] = st.session_state["findings"]
    actions: dict = st.session_state["finding_actions"]

    st.markdown("---")
    st.markdown('<div class="eyebrow">STEP 1: INSPECT AUDIT FINDINGS</div>', unsafe_allow_html=True)
    st.subheader(f"Draft Content & Highlights (`{st.session_state['active_asset_id']}`)")

    # Render Annotated Draft
    st.markdown(render_annotated_draft(doc.text, findings), unsafe_allow_html=True)

    st.markdown('<div class="eyebrow">STEP 2: RESOLVE COMPLIANCE FINDINGS</div>', unsafe_allow_html=True)
    st.write(f"Identified **{len(findings)} compliance findings**. Every item requires an action before review submission.")

    engine = RuleEngine()

    for idx, f in enumerate(findings, 1):
        with st.container():
            st.markdown(
                f"""
                <div class="brand-card">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="eyebrow">FINDING #{idx} &bull; {f.kind.value.upper()} &bull; {f.rule_id or f.fact_id}</span>
                        <span class="badge-pill {'badge-changes' if f.severity == Severity.BLOCK else 'badge-ready'}">{f.severity.value.upper()}</span>
                    </div>
                    <h4 style="margin: 0.3rem 0; color: #13171A;">"{f.source_text}"</h4>
                    <p style="color: #444; margin-bottom: 0.4rem;">{f.message}</p>
                    <div style="font-size: 0.85rem; color: #0B6E6A; margin-bottom: 0.5rem;">
                        <strong>Next Step:</strong> {f.next_step}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            current_act = actions[f.finding_id]["action"]
            
            # Action Tabs: Accept / Edit / Dismiss
            t_accept, t_edit, t_dismiss = st.tabs(["✅ Accept Suggestion", "✏️ Custom Edit", "🚫 Dismiss Finding"])

            with t_accept:
                if f.suggested_rewrite:
                    st.markdown("**Proposed Rewrite Diff:**")
                    st.markdown(render_diff_html(f.source_text, f.suggested_rewrite), unsafe_allow_html=True)
                    
                    # Live re-check verification badge
                    is_clean, _ = engine.check_rewrite(f.suggested_rewrite, {"product": "prod_monsoon"})
                    if is_clean:
                        st.caption("🛡️ Re-check: **PASS** (Zero blocking rule violations)")
                    else:
                        st.caption("⚠️ Re-check: **FAIL** (Rewrite violates rules)")

                    if st.button(f"Accept Proposed Rewrite for #{idx}", key=f"btn_acc_{f.finding_id}"):
                        actions[f.finding_id]["action"] = "accepted"
                        actions[f.finding_id]["text"] = f.suggested_rewrite
                        st.success(f"Accepted rewrite for #{idx}")
                        st.rerun()
                else:
                    st.info("No automatic rewrite available. Please use Custom Edit.")

            with t_edit:
                edited_text = st.text_input(
                    f"Edit text for #{idx}:",
                    value=actions[f.finding_id]["text"] or f.source_text,
                    key=f"edit_input_{f.finding_id}",
                )
                if edited_text != f.source_text:
                    is_clean, violations = engine.check_rewrite(edited_text, {"product": "prod_monsoon"})
                    if is_clean:
                        st.success("✅ Live Re-check: PASS — Clean under all rules!")
                    else:
                        st.error(f"❌ Live Re-check: FAIL — Triggers {violations[0].rule_id}: {violations[0].message}")

                if st.button(f"Save Edit for #{idx}", key=f"btn_save_{f.finding_id}"):
                    actions[f.finding_id]["action"] = "edited"
                    actions[f.finding_id]["text"] = edited_text
                    st.success(f"Custom edit saved for #{idx}")
                    st.rerun()

            with t_dismiss:
                dismiss_reason = st.selectbox(
                    f"Select Reason for #{idx} (Mandatory):",
                    options=["Artistic/Brand Discretion", "Approved Exception Granted", "Unrelated Contextual Phrasing", "Claim Substantiated Externally"],
                    key=f"dismiss_sel_{f.finding_id}",
                )
                dismiss_note = st.text_area(f"Add Context Note for Reviewer (Optional):", key=f"dismiss_note_{f.finding_id}")
                if st.button(f"Confirm Dismissal for #{idx}", key=f"btn_dism_{f.finding_id}"):
                    actions[f.finding_id]["action"] = "dismissed"
                    actions[f.finding_id]["dismiss_reason"] = f"{dismiss_reason} | {dismiss_note}".strip(" |")
                    st.warning(f"Finding #{idx} marked as dismissed. Reviewer will inspect dismissal rationale.")
                    st.rerun()

            # Status Badge for Current Action
            st.markdown(f"**Current Action Status:** `{current_act.upper()}`")
            st.markdown("---")

    # Review Submission Guard
    st.markdown('<div class="eyebrow">STEP 3: SUBMIT TO REVIEWER</div>', unsafe_allow_html=True)
    unresolved_count = sum(1 for v in actions.values() if v["action"] == "pending")

    if unresolved_count > 0:
        st.warning(f"⚠️ **Submission Locked:** {unresolved_count} of {len(findings)} findings still require a creator decision.")
        st.button("Submit Draft for Review", disabled=True)
    else:
        st.success("🎉 All findings resolved! Ready for reviewer approval.")
        if st.button("🚀 Submit Draft for Review", type="primary"):
            asset_id = st.session_state["active_asset_id"]
            
            # Persist findings to database
            for f in findings:
                act_data = actions[f.finding_id]
                execute_commit(
                    """
                    INSERT INTO findings (
                        finding_id, asset_id, kind, severity, span_start, span_end, source_text,
                        rule_id, fact_id, fact_version_id, link_state, message, next_step,
                        suggested_rewrite, creator_action, dismiss_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(finding_id) DO UPDATE SET
                        creator_action = excluded.creator_action,
                        dismiss_reason = excluded.dismiss_reason;
                    """,
                    (
                        f.finding_id,
                        asset_id,
                        f.kind.value,
                        f.severity.value,
                        f.span_start,
                        f.span_end,
                        f.source_text,
                        f.rule_id,
                        f.fact_id,
                        f.fact_version_id,
                        f.link_state.value,
                        f.message,
                        f.next_step,
                        act_data.get("text"),
                        act_data["action"],
                        act_data.get("dismiss_reason"),
                    ),
                )

            # Update asset status
            execute_commit("UPDATE assets SET status = 'ready_for_review' WHERE asset_id = ?;", (asset_id,))

            # Log audit trail event
            log_review_event(
                asset_id=asset_id,
                actor="Alex Chen (Creator)",
                role=Role.CREATOR,
                action="submit_for_review",
                comment=f"Submitted draft with {len(findings)} resolved findings.",
            )

            st.balloons()
            st.success(f"Asset `{asset_id}` submitted to Reviewer queue successfully!")
            st.session_state["active_doc"] = None
            st.session_state["findings"] = []
