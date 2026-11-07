"""
Brand Rule Lab — Main Application Entry & Dashboard
Owned by Agent A4 (Frontend & UX Engineer).

Midnight Black, Pure White & Lime Green Editorial SaaS Theme.
"""

import sys
from pathlib import Path

# Ensure project root is available on sys.path for Streamlit execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from app.ui.components import render_audit_event_item
from app.ui.theme import apply_theme, render_banner, render_sidebar_role_switcher
from core.db import execute_query, init_db
from core.llm import get_llm_status
from core.models import ReviewEvent, Role
from core.seed import seed_database
from core.snapshots import migrate_add_snapshots_table

# Configure Streamlit page layout
st.set_page_config(
    page_title="Brand Rule Lab",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
render_banner()

# Startup database readiness check and permanent protection
try:
    from core.db import ensure_app_database_ready
    db_status = ensure_app_database_ready()
    st.session_state["db_initialized"] = True
    st.session_state["db_status"] = db_status
except Exception as e:
    st.error(
        f"🚨 **Database Startup Initialization Failure:** {e}\n\n"
        "Application startup halted to prevent execution on an uninitialized or corrupt database."
    )
    st.stop()

# Global Sidebar Persona Switcher & Environment Info
current_role = render_sidebar_role_switcher()

# Main Landing Header
st.markdown('<div class="eyebrow">ENTERPRISE GOVERNANCE & CLAIM LEDGER</div>', unsafe_allow_html=True)
st.title("Brand Rule Lab")
st.markdown(
    """
    <p style="font-size: 1.1rem; color: var(--text-secondary); margin-top: -0.5rem; margin-bottom: 1.5rem;">
        Pre-Publication Brand Compliance Platform with Immutable Claim-to-Fact Lineage Ledger.
    </p>
    """,
    unsafe_allow_html=True,
)

# Core Architecture Philosophy Hero Card
st.markdown(
    """
    <div class="brand-card" style="border-left: 4px solid var(--accent);">
        <div class="eyebrow">CORE ARCHITECTURAL PHILOSOPHY</div>
        <h3 style="margin-top: 0.2rem; color: var(--text-primary); font-size: 1.45rem;">
            AI proposes. Python decides. <span style="color: var(--accent-text);">Humans approve.</span>
        </h3>
        <p style="margin-bottom: 0; color: var(--text-secondary); line-height: 1.65; font-size: 0.95rem;">
            Generative LLMs excel at span extraction and linguistic rewrite proposals, but fail at deterministic compliance verification. 
            Brand Rule Lab enforces strict separation of concerns: LLMs propose candidate findings and rewrites, 
            pure-Python predicates execute auditable pass/fail compliance decisions, and authorized humans approve verified claims into an immutable ledger.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# AI Multi-Provider Infrastructure Matrix
st.markdown('<div class="eyebrow">AI PROVIDER INFRASTRUCTURE MATRIX</div>', unsafe_allow_html=True)
import os
llm_status = get_llm_status()
current_mode = llm_status.get("mode", "mock").lower()
active_p = llm_status.get("active_provider") or ("mock" if current_mode == "mock" else "gemini")

has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))
has_nvidia_key = bool(os.getenv("NVIDIA_API_KEY"))

gemini_model = os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or "gemini-3.1-flash-lite"
nvidia_model = os.getenv("NVIDIA_MODEL") or "mistralai/mistral-7b-instruct-v0.3"

# Derive dynamic statuses from real runtime configuration
if current_mode in ("live", "dual", "gemini") and active_p == "gemini":
    gemini_badge = '<span class="badge-pill badge-approved">ACTIVE</span>'
    gemini_sub = "Primary routing &bull; Bounded 3-retry cap"
elif has_gemini_key:
    gemini_badge = '<span class="badge-pill badge-ready">HOT STANDBY</span>'
    gemini_sub = "API key configured &bull; Standby"
else:
    gemini_badge = '<span class="badge-pill badge-escalated">UNCONFIGURED</span>'
    gemini_sub = "GEMINI_API_KEY not set in environment"

if current_mode in ("live", "dual", "nvidia") and active_p == "nvidia":
    nvidia_badge = '<span class="badge-pill badge-approved">ACTIVE</span>'
    nvidia_sub = "Primary routing &bull; Verified OpenAI schema"
elif has_nvidia_key:
    nvidia_badge = '<span class="badge-pill badge-ready">HOT STANDBY</span>'
    nvidia_sub = "API key verified &bull; Sequential failover target"
else:
    nvidia_badge = '<span class="badge-pill badge-escalated">UNCONFIGURED</span>'
    nvidia_sub = "NVIDIA_API_KEY not set in environment"

if current_mode == "mock" or active_p == "mock":
    mock_badge = '<span class="badge-pill badge-approved">ACTIVE</span>'
    mock_sub = "Zero network dependency &bull; Demo protection"
else:
    mock_badge = '<span class="badge-pill badge-ready">GUARANTEED</span>'
    mock_sub = "Zero network dependency &bull; Final resilience tier"

with st.container():
    p_col1, p_col2, p_col3 = st.columns(3)
    with p_col1:
        st.markdown(
            f"""
            <div class="brand-card" style="padding: 1.1rem; min-height: 185px; height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="eyebrow">PRIMARY PROVIDER</span>
                    {gemini_badge}
                </div>
                <h4 style="margin: 0.3rem 0; color: var(--text-primary);">Google Gemini</h4>
                <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                    REST API (v1beta) &bull; <code>{gemini_model}</code>
                </p>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--text-muted);">
                    {gemini_sub}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with p_col2:
        st.markdown(
            f"""
            <div class="brand-card" style="padding: 1.1rem; min-height: 185px; height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="eyebrow">SECONDARY PROVIDER</span>
                    {nvidia_badge}
                </div>
                <h4 style="margin: 0.3rem 0; color: var(--text-primary);">NVIDIA NIM</h4>
                <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                    OpenAI Compatible API &bull; <code>{nvidia_model}</code>
                </p>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--text-muted);">
                    {nvidia_sub}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with p_col3:
        st.markdown(
            f"""
            <div class="brand-card" style="padding: 1.1rem; min-height: 185px; height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="eyebrow">FALLBACK PROVIDER</span>
                    {mock_badge}
                </div>
                <h4 style="margin: 0.3rem 0; color: var(--text-primary);">Deterministic Mock</h4>
                <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                    In-Memory Python &bull; <code>100% Offline Reproducible</code>
                </p>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--accent-text);">
                    {mock_sub}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("---")

# Quick Navigation Grid
st.markdown('<div class="eyebrow">GOVERNANCE STAGES & WORKSPACES</div>', unsafe_allow_html=True)
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center; min-height: 200px; height: 100%;">
            <div class="eyebrow">STAGE 1</div>
            <h4 style="color: var(--text-primary); margin-top: 0.2rem;">✍️ Creator</h4>
            <p style="font-size: 0.85rem; color: var(--text-secondary);">Upload drafts (PDF, DOCX, TXT, Images), inspect findings, and accept compliant rewrites.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Creator Workspace", use_container_width=True):
        st.switch_page("pages/1_Creator.py")

with col2:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center; min-height: 200px; height: 100%;">
            <div class="eyebrow">STAGE 2</div>
            <h4 style="color: var(--text-primary); margin-top: 0.2rem;">🔍 Reviewer</h4>
            <p style="font-size: 0.85rem; color: var(--text-secondary);">Approve compliant assets, inspect lineage (<code>SC-xxxx → Fact vX</code>), or log explicit overrides.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Reviewer Queue", use_container_width=True):
        st.switch_page("pages/2_Reviewer.py")

with col3:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center; min-height: 200px; height: 100%;">
            <div class="eyebrow">STAGE 3</div>
            <h4 style="color: var(--text-primary); margin-top: 0.2rem;">🧪 Fact Owner</h4>
            <p style="font-size: 0.85rem; color: var(--text-secondary);">Publish approved facts with 0 LLM calls and 1 SQL update. Propagate drift cascades live.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Fact Owner Ledger", use_container_width=True):
        st.switch_page("pages/3_Fact_Owner.py")

with col4:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center; min-height: 200px; height: 100%;">
            <div class="eyebrow">VERIFICATION</div>
            <h4 style="color: var(--text-primary); margin-top: 0.2rem;">📋 Rule Tests</h4>
            <p style="font-size: 0.85rem; color: var(--text-secondary);">Execute positive and negative test cases live across all rules for hackathon judges.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Run Rule Test Cases", use_container_width=True):
        st.switch_page("pages/4_Rule_Tests.py")

st.markdown("---")

# Quick System Metrics
st.markdown('<div class="eyebrow">SYSTEM HEALTH & REPOSITORY METRICS</div>', unsafe_allow_html=True)
m1, m2, m3, m4 = st.columns(4)
try:
    p_cnt = execute_query("SELECT COUNT(*) as c FROM products;")[0]["c"]
    f_cnt = execute_query("SELECT COUNT(*) as c FROM fact_versions;")[0]["c"]
    c_cnt = execute_query("SELECT COUNT(*) as c FROM approved_claims;")[0]["c"]
    r_cnt = execute_query("SELECT COUNT(*) as c FROM rules;")[0]["c"]
    m1.metric("Registered Products", p_cnt)
    m2.metric("Approved Fact Versions", f_cnt)
    m3.metric("Ledger Approved Claims", c_cnt)
    m4.metric("Active Deterministic Rules", r_cnt)
except Exception:
    pass

# Recent Audit Events Stream
try:
    recent_events = execute_query("SELECT * FROM review_events ORDER BY timestamp DESC LIMIT 4;")
    if recent_events:
        st.markdown("---")
        st.markdown('<div class="eyebrow">RECENT AUDIT TRAIL ACTIVITY</div>', unsafe_allow_html=True)
        for r_evt in recent_events:
            evt_obj = ReviewEvent(
                event_id=r_evt["event_id"],
                asset_id=r_evt["asset_id"],
                actor=r_evt["actor"],
                role=Role(r_evt["role"]) if r_evt["role"] in [r.value for r in Role] else Role.CREATOR,
                action=r_evt["action"],
                finding_id=r_evt.get("finding_id"),
                override_reason=r_evt.get("override_reason"),
                comment=r_evt.get("comment"),
                provenance=r_evt.get("provenance", "USER_ACTION"),
                known_before_timestamp=r_evt.get("known_before_timestamp"),
                timestamp=r_evt["timestamp"],
            )
            st.markdown(render_audit_event_item(evt_obj), unsafe_allow_html=True)
except Exception:
    pass
