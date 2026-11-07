"""
Brand Rule Lab — Fact Owner & Claim Ledger Dashboard
Owned by Agent A4 (Frontend & UX Engineer).

Manages approved brand facts, version updates, fact-drift propagation,
and expiration sweeps.
Non-Negotiable Rule 7: Fact update = 0 LLM calls, 0 web crawls, 1 SQL update.
"""

from __future__ import annotations
from datetime import datetime, timedelta
import streamlit as st
from app.ui.components import render_state_chip
from app.ui.theme import apply_theme, render_banner, render_sidebar_role_switcher
from core.db import execute_commit, execute_query
from core.ledger.drift import cascade_fact_update, sweep_expiry
from core.lookup.facts import publish_fact_version
from core.audit import log_review_event
from core.models import DriftStatus, Role

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
is_fact_owner = (current_role == "fact_owner")

st.title("🧪 Fact Owner & Claim Ledger")
st.markdown('<div class="eyebrow">APPROVED FACT GOVERNANCE & DRIFT CASCADE</div>', unsafe_allow_html=True)

# Role Boundary Notice
if not is_fact_owner:
    st.warning(
        f"🚫 **Permission Denied:** You are currently viewing as **{current_role.title()}**. "
        "Under Brand Rule Lab governance rules, only the **Fact Owner** persona can create/publish "
        "fact versions or execute drift and expiry cascades. Use the sidebar to switch to Fact Owner."
    )

# Top Drift Metrics Cards
st.markdown('<div class="eyebrow">CLAIM LEDGER DRIFT STATUS</div>', unsafe_allow_html=True)

stats = execute_query(
    """
    SELECT 
        SUM(CASE WHEN drift_status = 'CURRENT' THEN 1 ELSE 0 END) as current_cnt,
        SUM(CASE WHEN drift_status = 'REVIEW_REQUIRED' THEN 1 ELSE 0 END) as review_cnt,
        SUM(CASE WHEN drift_status = 'EXPIRED' THEN 1 ELSE 0 END) as expired_cnt,
        COUNT(*) as total_claims
    FROM approved_claims;
    """
)[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("CURRENT (Compliant)", stats["current_cnt"] or 0)
m2.metric("REVIEW_REQUIRED (Drifted)", stats["review_cnt"] or 0)
m3.metric("EXPIRED (Offer Ended)", stats["expired_cnt"] or 0)
m4.metric("Total Ledger Claims", stats["total_claims"] or 0)

st.caption("ℹ️ *Linked coverage only; unregistered live content is designated as **NOT_OBSERVED**.*")
st.markdown("---")

tab_facts, tab_ledger, tab_drift, tab_escalations = st.tabs([
    "📚 Approved Facts Table",
    "📜 Registered Claims Ledger",
    "⚡ Fact Update & Drift Cascade",
    "🚨 Reviewer Escalations",
])

# 1. APPROVED FACTS TABLE
with tab_facts:
    f_col1, f_col2 = st.columns([1, 1])
    with f_col1:
        products = execute_query("SELECT product_id, name FROM products;")
        prod_map = {p["product_id"]: p["name"] for p in products}
        filter_prod = st.selectbox("Filter Product:", options=["ALL"] + list(prod_map.keys()), format_func=lambda x: "All Products" if x == "ALL" else prod_map[x])
    with f_col2:
        filter_market = st.selectbox("Filter Market:", options=["ALL", "US", "UK", "EU"])

    where_clauses = []
    params = []
    if filter_prod != "ALL":
        where_clauses.append("product_id = ?")
        params.append(filter_prod)
    if filter_market != "ALL":
        where_clauses.append("market = ?")
        params.append(filter_market)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    facts = execute_query(
        f"""
        SELECT fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, expires_at, owner
        FROM fact_versions
        {where_sql}
        ORDER BY fact_id ASC, version DESC;
        """,
        tuple(params),
    )

    now_date = datetime.utcnow().date()
    soon_date = now_date + timedelta(days=30)

    for f in facts:
        exp_date_str = f["expires_at"]
        is_expiring_soon = False
        if exp_date_str:
            try:
                exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                if now_date <= exp_date <= soon_date:
                    is_expiring_soon = True
            except Exception:
                pass

        card_border = "#F59E0B" if is_expiring_soon else "#27272A"
        exp_warning = ' <span class="badge-pill badge-changes">EXPIRING IN 30 DAYS</span>' if is_expiring_soon else ""

        st.markdown(
            f"""
            <div class="brand-card" style="border-left: 4px solid {card_border};">
                <div style="display:flex; justify-content:space-between;">
                    <span class="eyebrow">{f['fact_id']} &bull; VERSION {f['version']}{exp_warning}</span>
                    <span style="font-size:0.8rem; color:#A1A1AA;">Scope: <code class="mono-id">{f['product_id']}</code> ({f['market']})</span>
                </div>
                <h4 style="margin: 0.3rem 0; color:#FFFFFF;">{f['fact_text']}</h4>
                <p style="font-size:0.9rem; margin-bottom:0.3rem; color:#D4D4D8;"><strong style="color:#FFFFFF;">Permitted Wording:</strong> <em style="color:#C6F432;">"{f['permitted_wording']}"</em></p>
                <div style="font-size:0.8rem; color:#A1A1AA;">
                    Owner: <code class="mono-id">{f['owner']}</code> &bull; Valid: {f['valid_from']} to {f['expires_at'] or 'Perpetual'}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# 2. REGISTERED CLAIMS LEDGER
with tab_ledger:
    st.markdown("#### Registered Approved Claims")
    claims_rows = execute_query(
        """
        SELECT c.stable_claim_id, c.asset_id, c.claim_text, c.fact_id, c.fact_version_id,
               c.drift_status, c.approved_by, c.approved_at, c.flagged_at
        FROM approved_claims c
        ORDER BY c.approved_at DESC;
        """
    )
    if not claims_rows:
        st.info("No approved claims registered yet. Claims enter the ledger when approved by a Reviewer.")
    else:
        for cr in claims_rows:
            flag_info = f" &bull; Flagged at: {cr['flagged_at'][:19]}" if cr["flagged_at"] else ""
            st.markdown(
                f"""
                <div class="brand-card">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="eyebrow">STABLE ID: <code class="mono-id">{cr['stable_claim_id']}</code> &bull; Tied to <code class="mono-id">{cr['fact_id']} v{cr['fact_version_id']}</code></span>
                        <span>{render_state_chip(cr['drift_status'])}</span>
                    </div>
                    <h4 style="margin: 0.3rem 0; color:#FFFFFF;">"{cr['claim_text']}"</h4>
                    <div style="font-size:0.8rem; color:#A1A1AA;">
                        Asset: <code class="mono-id">{cr['asset_id']}</code> &bull; Approved by: {cr['approved_by']} ({cr['approved_at'][:10]}){flag_info}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# 3. FACT UPDATE & DRIFT CASCADE
with tab_drift:
    st.markdown('<div class="eyebrow">DEMO PATH STEP 4: FACT DRIFT PROPAGATION</div>', unsafe_allow_html=True)
    st.markdown("Publish a new version of an existing brand fact. Watch how dependent claims automatically transition to `REVIEW_REQUIRED`.")

    # Target demo fact selector
    fact_choice = st.selectbox("Select Target Fact to Update:", options=["F-112 (Monsoon Acne Claim)", "F-OFFER-02 (Fall Sale)"])
    target_fid = "F-112" if "F-112" in fact_choice else "F-OFFER-02"

    # Count how many claims depend on this fact
    dependent_claims = execute_query(
        "SELECT COUNT(*) as count FROM approved_claims WHERE fact_id = ? AND drift_status = 'CURRENT';",
        (target_fid,),
    )[0]["count"]

    st.markdown(
        f"""
        <div class="brand-card" style="background:#1C1917; border:1px solid #F59E0B; border-left:4px solid #F59E0B; color:#FFFFFF;">
            <strong style="color:#F59E0B;">⚠️ IMPACT PREVIEW:</strong> There are currently <strong>{dependent_claims} registered claims</strong> 
            in the ledger linked to <code class="mono-id">{target_fid}</code>. 
            <br><em>Pre-Commit Confirmation:</em> <strong style="color:#C6F432;">"This will flag {dependent_claims} registered claims"</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

    new_fact_text = st.text_area(
        "New Clinical Trial Statement:",
        value="Clinically proven to reduce acne breakouts in 2 weeks with reformulated 2.5% Micronized Benzoyl Peroxide." if target_fid == "F-112" else "Flash Sale extended to 20 November 2026.",
    )
    new_permitted = st.text_input(
        "New Permitted Wording:",
        value="Reduces breakouts in 2 weeks with micronized formula." if target_fid == "F-112" else "Sale ends Nov 20.",
    )
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        new_version_num = st.number_input("New Version Number:", min_value=1, max_value=20, value=4 if target_fid == "F-112" else 2)
    with col_v2:
        val_from_date = st.date_input("Valid From:", value=datetime.utcnow().date())
    with col_v3:
        has_expiry = st.checkbox("Set Expiry Date", value=False if target_fid == "F-112" else True)
        exp_date_val = st.date_input("Expires At:", value=(datetime.utcnow() + timedelta(days=90)).date()) if has_expiry else None

    confirm_box = st.checkbox(
        f'I confirm: "This will flag {dependent_claims} registered claims"',
        value=True,
        help="Pre-commit governance confirmation required by Brand Rule Lab build plan.",
    )

    btn_pub_disabled = (not is_fact_owner) or (not confirm_box)
    pub_help = None if is_fact_owner else "Disabled: Switch to Fact Owner persona in sidebar"
    if st.button("🚀 Publish New Fact Version & Propagate Drift", type="primary", disabled=btn_pub_disabled, help=pub_help):
        if not is_fact_owner:
            st.error(f"Permission Denied: Role '{current_role}' is not permitted to publish brand facts.")
        else:
            try:
                # 1. Insert new fact version using backend function that enforces role boundaries
                publish_fact_version(
                    fact_id=target_fid,
                    version=int(new_version_num),
                    product_id="prod_monsoon",
                    market="US",
                    fact_text=new_fact_text,
                    permitted_wording=new_permitted,
                    valid_from=str(val_from_date),
                    expires_at=str(exp_date_val) if exp_date_val else None,
                    owner="brand_science",
                    role=current_role,
                )

                # 2. Execute Single SQL Cascade (0 LLM calls, 0 web crawls, 1 SQL UPDATE)
                flagged_count = cascade_fact_update(target_fid, int(new_version_num), role=current_role)

                # 3. Append-only audit trail logging for affected assets
                affected_assets = execute_query(
                    "SELECT DISTINCT asset_id FROM approved_claims WHERE fact_id = ?;",
                    (target_fid,),
                )
                for aa in affected_assets:
                    log_review_event(
                        asset_id=aa["asset_id"],
                        actor="Sarah Jenkins (Fact Owner)" if is_fact_owner else str(current_role),
                        role=Role.FACT_OWNER,
                        action="PUBLISH_FACT_VERSION",
                        comment=f"Published {target_fid} v{new_version_num}. Cascade flagged registered claims as REVIEW_REQUIRED.",
                    )

                st.session_state["recent_fact_cascade"] = {
                    "fact_id": target_fid,
                    "version": int(new_version_num),
                    "flagged": flagged_count,
                }
                st.success(f"🎉 Published `{target_fid} v{new_version_num}`! Single-SQL update executed: **{flagged_count} claims** flagged as `REVIEW_REQUIRED` (0 LLM calls, 0 web crawls).")
                st.rerun()
            except Exception as ex:
                st.error(f"Failed to publish fact version: {ex}")

    # Display Affected Claims Result List
    recent_cascade = st.session_state.get("recent_fact_cascade")
    if recent_cascade:
        c_fid = recent_cascade["fact_id"]
        c_ver = recent_cascade["version"]
        c_flg = recent_cascade["flagged"]
        st.markdown(f"#### 📋 Affected Claims Result List (`{c_fid} v{c_ver}` — {c_flg} Flagged)")
        affected_claims = execute_query(
            """
            SELECT c.stable_claim_id, c.asset_id, c.claim_text, c.fact_id, c.fact_version_id,
                   c.drift_status, c.approved_by, c.approved_at, c.flagged_at
            FROM approved_claims c
            WHERE c.fact_id = ? AND c.drift_status = 'REVIEW_REQUIRED'
            ORDER BY c.flagged_at DESC;
            """,
            (c_fid,),
        )
        if affected_claims:
            for ac in affected_claims:
                st.markdown(
                    f"""
                    <div class="brand-card" style="border-left: 4px solid #F59E0B;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span class="eyebrow">STABLE ID: <code class="mono-id">{ac['stable_claim_id']}</code> &bull; Tied to <code class="mono-id">{ac['fact_id']} v{ac['fact_version_id']}</code></span>
                            <span>{render_state_chip(ac['drift_status'])}</span>
                        </div>
                        <h4 style="margin: 0.3rem 0; color:#F59E0B;">"{ac['claim_text']}"</h4>
                        <div style="font-size:0.8rem; color:#A1A1AA;">
                            Asset: <code class="mono-id">{ac['asset_id']}</code> &bull; Approved by: {ac['approved_by']} &bull; Flagged: {ac['flagged_at'][:19] if ac['flagged_at'] else 'Now'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("No claims currently in REVIEW_REQUIRED status for this fact.")

    st.markdown("---")
    st.markdown("#### ⏳ Campaign Expiry Sweep")
    st.write("Run automated sweep to identify and transition claims linked to expired promotional campaigns.")
    sweep_date = st.date_input("Evaluation Date for Expiry Sweep:", value=datetime.utcnow().date())
    if st.button("Run Expiry Sweep", disabled=not is_fact_owner, help=None if is_fact_owner else "Disabled: Switch to Fact Owner persona in sidebar"):
        if not is_fact_owner:
            st.error(f"Permission Denied: Role '{current_role}' is not permitted to run expiry operations.")
        else:
            try:
                expired_count = sweep_expiry(str(sweep_date), role=current_role)
                st.info(f"Expiry sweep completed. **{expired_count} claims** transitioned to `EXPIRED` status.")
                st.rerun()
            except Exception as ex:
                st.error(f"Failed to run expiry sweep: {ex}")

# 4. REVIEWER ESCALATIONS
with tab_escalations:
    st.markdown("#### Evidence Gaps Escalated by Reviewers")
    escalated_assets = execute_query(
        """
        SELECT a.asset_id, a.name, a.product_id, a.created_by, r.comment, r.timestamp
        FROM assets a
        JOIN review_events r ON a.asset_id = r.asset_id
        WHERE a.status = 'escalated' AND r.action = 'escalate'
        ORDER BY r.timestamp DESC;
        """
    )
    if not escalated_assets:
        st.info("No active escalations. Reviewers escalate when copy makes claims unsupported by current brand facts.")
    else:
        for ea in escalated_assets:
            st.markdown(
                f"""
                <div class="brand-card" style="border-left: 4px solid #EF4444;">
                    <div class="eyebrow">ESCALATION &bull; ASSET <code class="mono-id">{ea['asset_id']}</code></div>
                    <h4 style="color:#FFFFFF; margin: 0.3rem 0;">{ea['name']}</h4>
                    <p style="color:#D4D4D8;"><strong style="color:#FFFFFF;">Reviewer Gap Note:</strong> <em style="color:#FCA5A5;">"{ea['comment']}"</em></p>
                    <div style="font-size:0.8rem; color:#A1A1AA;">
                        Product: <code class="mono-id">{ea['product_id']}</code> &bull; Escalated at: {ea['timestamp'][:19]}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
