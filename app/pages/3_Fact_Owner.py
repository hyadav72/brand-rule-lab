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
from app.ui.theme import apply_theme, render_banner
from core.db import execute_commit, execute_query
from core.ledger.drift import cascade_fact_update, sweep_expiry
from core.models import DriftStatus, Role

apply_theme()
render_banner()

st.title("🧪 Fact Owner & Claim Ledger")
st.markdown('<div class="eyebrow">APPROVED FACT GOVERNANCE & DRIFT CASCADE</div>', unsafe_allow_html=True)

# Role check
current_role = st.session_state.get("role", "fact_owner")
if current_role != "fact_owner":
    st.info(f"Viewing as **{current_role.title()}**. Switch to **Fact Owner** role to create fact versions or trigger drift propagation.")

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

        card_border = "#B4521A" if is_expiring_soon else "#D9D6CC"
        exp_warning = ' <span class="badge-pill badge-changes">EXPIRING IN 30 DAYS</span>' if is_expiring_soon else ""

        st.markdown(
            f"""
            <div class="brand-card" style="border-left: 4px solid {card_border};">
                <div style="display:flex; justify-content:space-between;">
                    <span class="eyebrow">{f['fact_id']} &bull; VERSION {f['version']}{exp_warning}</span>
                    <span style="font-size:0.8rem; color:#666;">Scope: <code>{f['product_id']}</code> ({f['market']})</span>
                </div>
                <h4 style="margin: 0.2rem 0; color:#13171A;">{f['fact_text']}</h4>
                <p style="font-size:0.9rem; margin-bottom:0.3rem;"><strong>Permitted Wording:</strong> <em>"{f['permitted_wording']}"</em></p>
                <div style="font-size:0.8rem; color:#555;">
                    Owner: <code>{f['owner']}</code> &bull; Valid: {f['valid_from']} to {f['expires_at'] or 'Perpetual'}
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
                        <span class="eyebrow">STABLE ID: <code>{cr['stable_claim_id']}</code> &bull; Tied to <code>{cr['fact_id']} v{cr['fact_version_id']}</code></span>
                        <span>{render_state_chip(cr['drift_status'])}</span>
                    </div>
                    <h4 style="margin: 0.3rem 0;">"{cr['claim_text']}"</h4>
                    <div style="font-size:0.8rem; color:#555;">
                        Asset: <code>{cr['asset_id']}</code> &bull; Approved by: {cr['approved_by']} ({cr['approved_at'][:10]}){flag_info}
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
        <div class="brand-card" style="background:#FFF9C4; border:1px solid #FBC02D;">
            <strong>⚠️ IMPACT PREVIEW:</strong> There are currently <strong>{dependent_claims} registered claims</strong> 
            in the ledger linked to <code>{target_fid}</code>. 
            Publishing a new version will immediately flag all {dependent_claims} claims as <code>REVIEW_REQUIRED</code>.
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
    new_version_num = st.number_input("New Version Number:", min_value=1, max_value=20, value=4 if target_fid == "F-112" else 2)

    if st.button("🚀 Publish New Fact Version & Propagate Drift", type="primary"):
        # 1. Insert new fact version
        execute_commit(
            """
            INSERT INTO fact_versions (fact_id, version, product_id, market, fact_text, permitted_wording, valid_from, owner)
            VALUES (?, ?, 'prod_monsoon', 'US', ?, ?, CURRENT_DATE, 'brand_science')
            ON CONFLICT(fact_id, version) DO UPDATE SET
                fact_text = excluded.fact_text,
                permitted_wording = excluded.permitted_wording;
            """,
            (target_fid, new_version_num, new_fact_text, new_permitted),
        )

        # 2. Execute Single SQL Cascade (0 LLM calls, 1 SQL UPDATE)
        flagged_count = cascade_fact_update(target_fid, new_version_num)

        st.success(f"🎉 Published `{target_fid} v{new_version_num}`! Single-SQL update executed: **{flagged_count} claims** flagged as `REVIEW_REQUIRED` (0 LLM calls, 0 web crawls).")
        st.rerun()

    st.markdown("---")
    st.markdown("#### ⏳ Campaign Expiry Sweep")
    st.write("Run automated sweep to identify and transition claims linked to expired promotional campaigns.")
    sweep_date = st.date_input("Evaluation Date for Expiry Sweep:", value=datetime.utcnow().date())
    if st.button("Run Expiry Sweep"):
        expired_count = sweep_expiry(str(sweep_date))
        st.info(f"Expiry sweep completed. **{expired_count} claims** transitioned to `EXPIRED` status.")
        st.rerun()

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
                <div class="brand-card" style="border-left: 4px solid #13171A;">
                    <div class="eyebrow">ESCALATION &bull; ASSET <code>{ea['asset_id']}</code></div>
                    <h4>{ea['name']}</h4>
                    <p><strong>Reviewer Gap Note:</strong> <em>"{ea['comment']}"</em></p>
                    <div style="font-size:0.8rem; color:#666;">
                        Product: <code>{ea['product_id']}</code> &bull; Escalated at: {ea['timestamp'][:19]}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
