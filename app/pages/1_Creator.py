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
from app.ui.theme import apply_theme, render_banner, render_sidebar_role_switcher
from core.audit import apply_creator_decision, log_creator_decision, log_review_event
from core.cycles import get_asset_review_cycle, load_revision_asset, start_revision_cycle
from core.db import execute_commit, execute_query
from core.extract.claims import extract_claims
from core.ingest import ingest
from core.llm import get_llm_adapter, get_llm_status
from core.lookup.facts import get_fact_version, lookup_facts
from core.models import AssetStatus, CreatorActionState, ExtractedDoc, Finding, FindingKind, LinkState, Role, Severity
from core.reconstruct import get_reconstruction_base_text, reconstruct_submitted_text
from core.rules.engine import RuleEngine
from core.snapshots import create_submission, get_original_snapshot, save_effective_snapshot, save_original_snapshot, submit_draft

apply_theme()
render_banner()

# Database readiness check
try:
    from core.db import ensure_app_database_ready
    ensure_app_database_ready()
except Exception as e:
    st.error(
        f"🚨 **Database Startup Initialization Failure:** {e}\n\n"
        "Application startup halted to prevent execution on an uninitialized or corrupt database."
    )
    st.stop()

current_role = render_sidebar_role_switcher()
is_creator = (current_role == "creator")

DEMO_COPY = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."

st.title("✍️ Creator Review Workspace")
st.markdown('<div class="eyebrow">PRE-PUBLICATION BRAND COMPLIANCE AUDIT</div>', unsafe_allow_html=True)

# LLM Status & Fallback Indicator
llm_status = get_llm_status()
if llm_status["mode"] == "live":
    if llm_status["fallback_active"]:
        st.warning(
            f"⚠️ **Running in deterministic-only mode:** Live LLM unavailable ({llm_status['fallback_reason']}). "
            "Rule findings and deterministic mock rewrites are active."
        )
    else:
        st.caption(f"⚡ **AI Mode:** Live Gemini ({llm_status['model']}) active for claim extraction & rewrites.")
else:
    st.caption("🛡️ **AI Mode:** Deterministic Mock (100% offline reproducible demo)")

# Role Boundary Notice
if not is_creator:
    st.warning(
        f"🚫 **Permission Denied:** You are currently viewing as **{current_role.title()}**. "
        "Under Brand Rule Lab governance rules, only the **Creator** persona can upload drafts, "
        "modify findings, or submit assets for review. Use the sidebar to switch to Creator."
    )


def _get_fact_context_signature(product_id: str | None, market: str) -> str:
    """
    Generate deterministic signature of all approved fact versions for this product and market.
    If a fact is updated (e.g. new version published or wording changed), this signature changes,
    invalidating stale cached rewrite verification results.
    """
    if not product_id:
        return f"none:{market}"
    from core.lookup.facts import lookup_all_valid_fact_versions
    facts = lookup_all_valid_fact_versions(product_id, market)
    items = [f"{f.fact_id}:v{f.version}:{f.expires_at or ''}:{f.permitted_wording}" for f in facts]
    return f"{product_id}:{market}:" + "|".join(sorted(items))


def _cached_check_rewrite(rule_engine: RuleEngine, rewrite_text: str, context: dict) -> tuple[bool, list[Finding]]:
    """
    Cached wrapper around RuleEngine.check_rewrite().
    Caches verification outcomes in st.session_state keyed by (rewrite_text, product_id, market, fact_signature).
    If underlying facts or text change, cache misses and deterministic check is re-run.
    """
    if not rewrite_text:
        return True, []
    if "rewrite_checks" not in st.session_state:
        st.session_state["rewrite_checks"] = {}

    product_id = context.get("product")
    market = context.get("market", "US")
    fact_sig = _get_fact_context_signature(product_id, market)
    cache_key = f"{rewrite_text.strip()}###{fact_sig}"

    if cache_key in st.session_state["rewrite_checks"]:
        return st.session_state["rewrite_checks"][cache_key]

    is_clean, violations = rule_engine.check_rewrite(rewrite_text, context)
    st.session_state["rewrite_checks"][cache_key] = (is_clean, violations)
    return is_clean, violations


def _enrich_findings_with_rewrites(findings_list: list[Finding], rule_engine: RuleEngine, eval_context: dict) -> None:
    """
    Wire LLM adapter suggest_rewrite() into Creator findings workflow.
    Every generated rewrite proposal is deterministically rechecked by RuleEngine.check_rewrite().
    If it fails, it is not offered as an accepted suggestion.
    Results are cached in st.session_state to avoid redundant checks during reruns.
    """
    adapter = get_llm_adapter()
    for f in findings_list:
        fact = None
        if f.fact_id and f.fact_version_id:
            fact = get_fact_version(f.fact_id, f.fact_version_id)

        proposed = adapter.suggest_rewrite(f, fact)
        if proposed:
            is_clean, _ = _cached_check_rewrite(rule_engine, proposed, eval_context)
            if is_clean:
                f.suggested_rewrite = proposed
            elif f.suggested_rewrite:
                tmpl_clean, _ = _cached_check_rewrite(rule_engine, f.suggested_rewrite, eval_context)
                if not tmpl_clean:
                    f.suggested_rewrite = None


# Setup Session State for Active Asset & Findings
if "active_asset_id" not in st.session_state:
    st.session_state["active_asset_id"] = None

if "active_doc" not in st.session_state:
    st.session_state["active_doc"] = None

if "findings" not in st.session_state:
    st.session_state["findings"] = []

if "finding_actions" not in st.session_state:
    st.session_state["finding_actions"] = {}

if "rewrite_checks" not in st.session_state:
    st.session_state["rewrite_checks"] = {}


# Revision Queue: Explicit CAS Transition for Assets with Changes Requested
try:
    rev_assets = execute_query(
        "SELECT asset_id, name, review_cycle, status FROM assets WHERE status = 'changes_requested' ORDER BY created_at DESC;"
    )
except Exception:
    try:
        rev_assets = execute_query(
            "SELECT asset_id, name, status FROM assets WHERE status = 'changes_requested' ORDER BY created_at DESC;"
        )
    except Exception:
        rev_assets = []

if rev_assets:
    st.markdown('<div class="eyebrow">REVISION QUEUE &bull; REVIEWER FEEDBACK</div>', unsafe_allow_html=True)
    for ra in rev_assets:
        r_cols = st.columns([3, 1])
        ra_dict = dict(ra)
        c_cycle = ra_dict.get("review_cycle", 1) or 1
        with r_cols[0]:
            st.markdown(f"**{ra_dict['name']}** (`{ra_dict['asset_id']}`) — Currently Cycle {c_cycle} (Changes Requested)")
            try:
                note_rows = execute_query(
                    "SELECT comment, actor FROM review_events WHERE asset_id = ? AND action = 'request_changes' ORDER BY timestamp DESC LIMIT 1;",
                    (ra_dict["asset_id"],),
                )
                if note_rows:
                    nr_dict = dict(note_rows[0])
                    if nr_dict.get("comment"):
                        st.info(f"💬 **Reviewer Feedback ({nr_dict.get('actor', 'Reviewer')}):** {nr_dict['comment']}")
            except Exception:
                pass
        with r_cols[1]:
            rev_btn_disabled = not is_creator
            rev_btn_help = None if is_creator else "Disabled: Switch to Creator role in sidebar to revise assets"
            if st.button(f"🔄 Revise (Cycle {c_cycle + 1})", key=f"btn_rev_{ra_dict['asset_id']}", disabled=rev_btn_disabled, help=rev_btn_help):
                if not is_creator:
                    st.error(f"Permission Denied: Role '{current_role}' is not permitted to revise assets.")
                else:
                    succ = start_revision_cycle(ra_dict["asset_id"])
                    try:
                        data = load_revision_asset(ra_dict["asset_id"])
                        st.session_state["active_asset_id"] = data["asset"]["asset_id"]
                        st.session_state["active_doc"] = data["doc"]
                        st.session_state["active_context"] = data["context"]
                        st.session_state["findings"] = data["findings"]
                        st.session_state["finding_actions"] = data["actions"]
                        st.session_state["rewrite_checks"] = {}
                        st.success(f"Asset `{ra_dict['asset_id']}` loaded into Creator workspace (Cycle {data['review_cycle']})!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Failed to load asset for revision: {ex}")

# In-Progress Revision Drafts (drafts with review_cycle > 1)
try:
    draft_rev_assets = execute_query(
        "SELECT asset_id, name, review_cycle, status FROM assets WHERE status = 'draft' AND review_cycle > 1 ORDER BY created_at DESC;"
    )
except Exception:
    draft_rev_assets = []

if draft_rev_assets:
    # Only show if not currently loaded as active
    unloaded_drafts = [d for d in draft_rev_assets if d["asset_id"] != st.session_state.get("active_asset_id")]
    if unloaded_drafts:
        st.markdown('<div class="eyebrow">IN-PROGRESS REVISION DRAFTS</div>', unsafe_allow_html=True)
        for dra in unloaded_drafts:
            d_cols = st.columns([3, 1])
            dra_dict = dict(dra)
            d_cycle = dra_dict.get("review_cycle", 2) or 2
            with d_cols[0]:
                st.markdown(f"**{dra_dict['name']}** (`{dra_dict['asset_id']}`) — Cycle {d_cycle} (Draft in Progress)")
            with d_cols[1]:
                resume_disabled = not is_creator
                resume_help = None if is_creator else "Disabled: Switch to Creator role in sidebar to resume drafts"
                if st.button(f"📂 Open Draft (Cycle {d_cycle})", key=f"btn_resume_{dra_dict['asset_id']}", disabled=resume_disabled, help=resume_help):
                    if not is_creator:
                        st.error(f"Permission Denied: Role '{current_role}' is not permitted to open drafts.")
                    else:
                        try:
                            data = load_revision_asset(dra["asset_id"])
                            st.session_state["active_asset_id"] = data["asset"]["asset_id"]
                            st.session_state["active_doc"] = data["doc"]
                            st.session_state["active_context"] = data["context"]
                            st.session_state["findings"] = data["findings"]
                            st.session_state["finding_actions"] = data["actions"]
                            st.session_state["rewrite_checks"] = {}
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Failed to load draft: {ex}")

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
        "Upload Draft (PDF, DOCX, TXT, PNG, JPG) — Max 10 MB",
        type=["pdf", "docx", "txt", "png", "jpg", "jpeg", "webp"],
        help="Maximum file size 10 MB.",
    )

    st.markdown("**— OR —**")
    btn_demo_disabled = not is_creator
    demo_help = None if is_creator else "Disabled: Switch to Creator role in sidebar to load and analyze drafts"
    if st.button("🚀 Load Hackathon Demo Draft (Monsoon Clear Skin)", type="primary", disabled=btn_demo_disabled, help=demo_help):
        if not is_creator:
            st.error(f"Permission Denied: Role '{current_role}' is not permitted to load or analyze drafts.")
        else:
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
            _enrich_findings_with_rewrites(findings, engine, context)

            # Store in session state
            st.session_state["active_asset_id"] = asset_id
            st.session_state["active_doc"] = doc
            st.session_state["active_context"] = context
            st.session_state["findings"] = findings
            st.session_state["finding_actions"] = {f.finding_id: {"action": "pending", "text": f.suggested_rewrite or ""} for f in findings}
            st.session_state["rewrite_checks"] = {}

            # Persist asset to DB
            execute_commit(
                """
                INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
                VALUES (?, ?, ?, ?, ?, 'draft', 'Alex Chen (Creator)', ?, ?, ?);
                """,
                (asset_id, "Monsoon Clear Skin Paid Social Caption", selected_prod, selected_market, selected_channel, doc.source_hash, doc.text, str(planned_date or "2026-11-10")),
            )
            st.rerun()

    if uploaded_file is not None:
        file_size = getattr(uploaded_file, "size", 0)
        max_size = 10 * 1024 * 1024  # 10 MB
        if file_size > max_size:
            st.error(
                f"File '{uploaded_file.name}' exceeds the strict 10 MB maximum limit "
                f"({file_size / (1024 * 1024):.1f} MB). Please upload a smaller file."
            )
        else:
            btn_analyze_disabled = not is_creator
            analyze_help = None if is_creator else "Disabled: Switch to Creator role in sidebar"
            if st.button("Analyze Uploaded File", disabled=btn_analyze_disabled, help=analyze_help):
                if not is_creator:
                    st.error(f"Permission Denied: Role '{current_role}' is not permitted to upload or analyze drafts.")
                else:
                    try:
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
                        _enrich_findings_with_rewrites(findings, engine, context)

                        st.session_state["active_asset_id"] = asset_id
                        st.session_state["active_doc"] = doc
                        st.session_state["active_context"] = context
                        st.session_state["findings"] = findings
                        st.session_state["finding_actions"] = {f.finding_id: {"action": "pending", "text": f.suggested_rewrite or ""} for f in findings}
                        st.session_state["rewrite_checks"] = {}

                        execute_commit(
                            """
                            INSERT INTO assets (asset_id, name, product_id, market, channel, status, created_by, source_hash, text_content, planned_publish_date)
                            VALUES (?, ?, ?, ?, ?, 'draft', 'Alex Chen (Creator)', ?, ?, ?);
                            """,
                            (asset_id, uploaded_file.name, selected_prod, selected_market, selected_channel, doc.source_hash, doc.text, str(planned_date or "2026-11-10")),
                        )
                        st.rerun()
                    except ValueError as ve:
                        err_text = str(ve)
                        if "We could not read this PDF" in err_text:
                            st.error("We could not read this PDF. Try DOCX or TXT")
                        else:
                            st.error(f"Validation error: {err_text}")
                    except Exception as ex:
                        if uploaded_file.name.lower().endswith(".pdf"):
                            st.error("We could not read this PDF. Try DOCX or TXT")
                        else:
                            st.error(f"Failed to process file: {ex}")

# Display Audit Findings and Draft Highlights
if st.session_state["active_doc"]:
    doc: ExtractedDoc = st.session_state["active_doc"]
    findings: list[Finding] = st.session_state["findings"]
    actions: dict = st.session_state["finding_actions"]

    st.markdown("---")
    st.markdown('<div class="eyebrow">STEP 1: INSPECT AUDIT FINDINGS</div>', unsafe_allow_html=True)
    cur_asset_id = st.session_state.get("active_asset_id")
    cur_cycle = st.session_state.get("active_context", {}).get("review_cycle", 1)

    col_hdr, col_cls = st.columns([4, 1])
    with col_hdr:
        st.subheader(f"Draft Content & Highlights (`{cur_asset_id}` — Cycle {cur_cycle})")
    with col_cls:
        if st.button("❌ Close Draft", key="btn_close_active_draft"):
            st.session_state["active_doc"] = None
            st.session_state["active_asset_id"] = None
            st.session_state["active_context"] = None
            st.session_state["findings"] = []
            st.session_state["finding_actions"] = {}
            st.session_state["rewrite_checks"] = {}
            st.rerun()

    # If this is a revised draft (cycle > 1), display any reviewer change request notes
    if cur_asset_id and cur_cycle > 1:
        try:
            rev_notes = execute_query(
                "SELECT comment, actor FROM review_events WHERE asset_id = ? AND action = 'request_changes' ORDER BY timestamp DESC LIMIT 1;",
                (cur_asset_id,),
            )
            if rev_notes:
                rn_dict = dict(rev_notes[0])
                if rn_dict.get("comment"):
                    st.warning(f"💬 **Reviewer Feedback for Cycle {cur_cycle} ({rn_dict.get('actor', 'Reviewer')}):** {rn_dict['comment']}")
        except Exception:
            pass

    # Render Annotated Draft
    base_display_text = get_reconstruction_base_text(cur_asset_id, doc.text, findings)
    st.markdown(render_annotated_draft(base_display_text, findings), unsafe_allow_html=True)

    st.markdown('<div class="eyebrow">STEP 2: RESOLVE COMPLIANCE FINDINGS</div>', unsafe_allow_html=True)
    st.write(f"Identified **{len(findings)} compliance findings**. Every item requires an action before review submission.")

    engine = RuleEngine()
    active_context = st.session_state.get(
        "active_context",
        {
            "asset_id": st.session_state.get("active_asset_id", "AST-MONSOON-01"),
            "product": "prod_monsoon",
            "market": "US",
            "channel": "paid_social",
        },
    )

    for idx, f in enumerate(findings, 1):
        with st.container():
            # Provenance resolution (Brand Fact, Deterministic Rule, or Guideline)
            if f.fact_id and f.fact_version_id:
                provenance = f"Brand Fact {f.fact_id} (v{f.fact_version_id})"
            elif f.fact_id:
                provenance = f"Brand Fact {f.fact_id}"
            elif f.rule_id:
                provenance = f"Rule {f.rule_id}"
            else:
                provenance = "Brand Compliance Guideline"

            st.markdown(
                f"""
                <div id="card-{f.finding_id}" class="brand-card" style="scroll-margin-top: 80px; border-left: 4px solid {'#EF4444' if f.severity == Severity.BLOCK else '#F59E0B'};">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <a href="#span-{f.finding_id}" style="text-decoration:none; color:inherit; cursor:pointer;" title="Click to jump to draft span">
                            <span class="eyebrow">FINDING #{idx} &bull; {f.kind.value.upper()} &bull; {f.rule_id or f.fact_id} ↖</span>
                        </a>
                        <div style="display:flex; gap:0.5rem; align-items:center;">
                            <a href="#span-{f.finding_id}" class="badge-pill badge-ready" style="text-decoration:none; font-size:0.75rem;" title="Scroll to span in draft">📍 View in Draft ↖</a>
                            <span class="badge-pill {'badge-changes' if f.severity == Severity.BLOCK else 'badge-ready'}">{f.severity.value.upper()}</span>
                        </div>
                    </div>
                    <h4 style="margin: 0.4rem 0; color: var(--text-primary); font-size: 1.15rem;">"{f.source_text}"</h4>
                    <p style="color: var(--text-secondary); margin-bottom: 0.4rem; font-size: 0.92rem;">{f.message}</p>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.3rem;">
                        <strong style="color: var(--text-primary);">Provenance:</strong> {provenance}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--accent-text); margin-bottom: 0.5rem;">
                        <strong>Next Step:</strong> {f.next_step}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            act_info = actions.setdefault(f.finding_id, {"action": "pending", "text": f.suggested_rewrite or ""})
            current_act = act_info["action"]
            
            # Action Tabs: Accept / Edit / Dismiss
            t_accept, t_edit, t_dismiss = st.tabs(["✅ Accept Suggestion", "✏️ Custom Edit", "🚫 Dismiss Finding"])

            with t_accept:
                if f.suggested_rewrite:
                    st.markdown("**Proposed Rewrite Diff:**")
                    st.markdown(render_diff_html(f.source_text, f.suggested_rewrite), unsafe_allow_html=True)
                    
                    # Live re-check verification badge (uses cached deterministic verification)
                    is_clean, violations = _cached_check_rewrite(engine, f.suggested_rewrite, active_context)
                    if is_clean:
                        st.caption("🛡️ Re-check: **PASS** (Zero blocking rule violations)")
                    else:
                        st.caption(f"⚠️ Re-check: **FAIL** ({violations[0].message if violations else 'Rewrite violates rules'})")

                    if st.button(
                        f"Accept Proposed Rewrite for #{idx}",
                        key=f"btn_acc_{f.finding_id}",
                        disabled=not is_clean,
                        help="Rewrite passes deterministic compliance checks" if is_clean else "Disabled: Proposed rewrite violates compliance rules",
                    ):
                        prev_act = actions[f.finding_id].get("action", "pending")
                        active_asset = st.session_state.get("active_asset_id")
                        cycle = get_asset_review_cycle(active_asset) if active_asset else 1
                        try:
                            apply_creator_decision(
                                finding=f,
                                action="accepted",
                                new_text=f.suggested_rewrite,
                                actor="Alex Chen (Creator)",
                                role=current_role,
                                asset_id=active_asset,
                                previous_action=prev_act,
                                review_cycle=cycle,
                            )
                            # Update Streamlit session state only after database transaction succeeds
                            actions[f.finding_id]["action"] = "accepted"
                            actions[f.finding_id]["text"] = f.suggested_rewrite
                            st.success(f"Accepted rewrite for #{idx}")
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Failed to record decision: {ex}")
                else:
                    st.info("No automatic rewrite available. Please use Custom Edit.")

            with t_edit:
                edited_text = st.text_input(
                    f"Edit text for #{idx}:",
                    value=actions[f.finding_id]["text"] or f.source_text,
                    key=f"edit_input_{f.finding_id}",
                )
                is_edit_clean = True
                if edited_text != f.source_text:
                    is_edit_clean, violations = _cached_check_rewrite(engine, edited_text, active_context)
                    if is_edit_clean:
                        st.success("✅ Live Re-check: PASS — Clean under all rules!")
                    else:
                        st.error(f"❌ Live Re-check: FAIL — Triggers {violations[0].rule_id}: {violations[0].message}")

                if st.button(
                    f"Save Edit for #{idx}",
                    key=f"btn_save_{f.finding_id}",
                    disabled=not is_edit_clean,
                    help="Custom edit passes deterministic compliance checks" if is_edit_clean else "Disabled: Custom edit violates compliance rules",
                ):
                    prev_act = actions[f.finding_id].get("action", "pending")
                    active_asset = st.session_state.get("active_asset_id")
                    cycle = get_asset_review_cycle(active_asset) if active_asset else 1
                    try:
                        apply_creator_decision(
                            finding=f,
                            action="edited",
                            new_text=edited_text,
                            actor="Alex Chen (Creator)",
                            role=current_role,
                            asset_id=active_asset,
                            previous_action=prev_act,
                            review_cycle=cycle,
                        )
                        # Update Streamlit session state only after database transaction succeeds
                        actions[f.finding_id]["action"] = "edited"
                        actions[f.finding_id]["text"] = edited_text
                        st.success(f"Custom edit saved for #{idx}")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Failed to save edit: {ex}")

            with t_dismiss:
                standard_reasons = [
                    "Artistic/Brand Discretion",
                    "Approved Exception Granted",
                    "Unrelated Contextual Phrasing",
                    "Claim Substantiated Externally",
                    "Market-Specific Exemption",
                ]
                dismiss_reason = st.selectbox(
                    f"Select Reason for #{idx} (Mandatory):",
                    options=standard_reasons,
                    key=f"dismiss_sel_{f.finding_id}",
                )
                dismiss_note = st.text_area(f"Add Context Note for Reviewer (Optional):", key=f"dismiss_note_{f.finding_id}")
                if st.button(f"Confirm Dismissal for #{idx}", key=f"btn_dism_{f.finding_id}"):
                    if not dismiss_reason or not dismiss_reason.strip():
                        st.error("A standard dismissal reason is mandatory.")
                    else:
                        prev_act = actions[f.finding_id].get("action", "pending")
                        if dismiss_note and dismiss_note.strip():
                            dismiss_full = f"{dismiss_reason.strip()} | {dismiss_note.strip()}"
                        else:
                            dismiss_full = dismiss_reason.strip()
                        active_asset = st.session_state.get("active_asset_id")
                        cycle = get_asset_review_cycle(active_asset) if active_asset else 1
                        try:
                            apply_creator_decision(
                                finding=f,
                                action="dismissed",
                                dismiss_reason=dismiss_full,
                                actor="Alex Chen (Creator)",
                                role=current_role,
                                asset_id=active_asset,
                                previous_action=prev_act,
                                review_cycle=cycle,
                            )
                            # Update Streamlit session state only after database transaction succeeds
                            actions[f.finding_id]["action"] = "dismissed"
                            actions[f.finding_id]["dismiss_reason"] = dismiss_full
                            st.warning(f"Finding #{idx} marked as dismissed. Reviewer will inspect dismissal rationale.")
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Failed to save dismissal: {ex}")

            # Status Badge for Current Action
            st.markdown(f"**Current Action Status:** `{current_act.upper()}`")
            st.markdown("---")

    # Review Submission Guard
    st.markdown('<div class="eyebrow">STEP 3: SUBMIT TO REVIEWER</div>', unsafe_allow_html=True)
    unresolved_count = sum(1 for v in actions.values() if v["action"] == "pending")

    # Guard: verify that all accepted or custom-edited rewrites pass deterministic re-check
    invalid_submissions = []
    for f in findings:
        act = actions.get(f.finding_id, {})
        if act.get("action") in ("accepted", "edited"):
            text_val = act.get("text", "")
            if text_val:
                is_val_clean, val_viols = _cached_check_rewrite(engine, text_val, active_context)
                if not is_val_clean:
                    invalid_submissions.append((f.finding_id, val_viols))

    # Run the complete reconstructed draft through deterministic Python compliance checks immediately before submission
    if not invalid_submissions and doc and doc.text and unresolved_count == 0:
        base_preview = get_reconstruction_base_text(st.session_state.get("active_asset_id"), doc.text, findings)
        reconstructed_preview = reconstruct_submitted_text(base_preview, findings, actions)
        is_draft_clean, draft_viols = engine.check_rewrite(reconstructed_preview, active_context)
        if not is_draft_clean:
            invalid_submissions.append(("COMPLETE_DRAFT", draft_viols))

    if unresolved_count > 0:
        st.warning(f"⚠️ **Submission Locked:** {unresolved_count} of {len(findings)} findings still require a creator decision.")
        st.button("Submit Draft for Review", disabled=True)
    elif invalid_submissions:
        st.error(f"⚠️ **Submission Locked:** {len(invalid_submissions)} accepted or edited rewrite(s) fail live compliance re-checks. Fix or dismiss before submission.")
        st.button("Submit Draft for Review", disabled=True)
    elif not is_creator:
        st.warning(f"🚫 **Submission Locked:** You are viewing as **{current_role.title()}**. Switch to **Creator** role in the sidebar to submit drafts.")
        st.button("Submit Draft for Review", disabled=True, help="Disabled: Only Creator role can submit drafts")
    else:
        st.success("🎉 All findings resolved! Ready for reviewer approval.")
        if st.button("🚀 Submit Draft for Review", type="primary"):
            asset_id = st.session_state["active_asset_id"]
            base_text = get_reconstruction_base_text(asset_id, doc.text, findings)
            original_text = base_text
            submitted_text = reconstruct_submitted_text(base_text, findings, actions)
            review_cycle = get_asset_review_cycle(asset_id)
            actor_name = "Alex Chen (Creator)"

            try:
                res = submit_draft(
                    asset_id=asset_id,
                    original_text=original_text,
                    submitted_text=submitted_text,
                    findings=findings,
                    actions=actions,
                    actor_name=actor_name,
                    role=current_role,
                    review_cycle=review_cycle,
                )
                st.balloons()
                st.success(f"Asset `{asset_id}` submitted to Reviewer queue successfully (Cycle {review_cycle})!")
                st.session_state["active_doc"] = None
                st.session_state["findings"] = []
                st.session_state["finding_actions"] = {}
                st.session_state["active_asset_id"] = None
                st.session_state["active_context"] = None
                st.session_state["rewrite_checks"] = {}
                st.rerun()
            except Exception as ex:
                st.error(f"Submission failed: {ex}")
else:
    st.markdown("---")
    st.info("👋 **Welcome to the Creator Review Workspace!** Click **'🚀 Load Hackathon Demo Draft'** or upload a marketing asset above to begin the brand compliance audit.")

# Mandatory Footer Note (Slide 8 / Build Plan Section 9)
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #71717A; font-size: 0.85rem; padding: 1.5rem 0 1rem 0;">
        <em>AI-assisted review: suggestions are drafts; the model receives claim text and approved fact fields only.</em>
        <div style="font-size: 0.78rem; color: #52525B; margin-top: 0.35rem;">
            Note on privacy boundary: Initial claim extraction scans the draft text to locate candidate spans; downstream rewrite and suggestion generation receives only isolated claim text and approved fact fields.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
