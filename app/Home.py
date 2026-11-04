"""
Brand Rule Lab — Main Application Entry & Role Picker
Owned by Agent A4 (Frontend & UX Engineer).
"""

import streamlit as st
from app.ui.theme import apply_theme, render_banner
from core.db import execute_query, init_db
from core.models import Role
from core.seed import seed_database

# Configure Streamlit page layout
st.set_page_config(
    page_title="Brand Rule Lab",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
render_banner()

# Initialize session state for role and active asset
if "role" not in st.session_state:
    st.session_state["role"] = Role.CREATOR.value

# Ensure database is seeded on initial run
if "db_initialized" not in st.session_state:
    try:
        seed_database()
        st.session_state["db_initialized"] = True
    except Exception as e:
        st.error(f"Database initialization notice: {e}")

# Sidebar Role Switcher
with st.sidebar:
    st.markdown('<div class="eyebrow">ACTIVE PERSONA</div>', unsafe_allow_html=True)
    selected_role = st.selectbox(
        "Switch System Role",
        options=[Role.CREATOR.value, Role.REVIEWER.value, Role.FACT_OWNER.value],
        index=[Role.CREATOR.value, Role.REVIEWER.value, Role.FACT_OWNER.value].index(st.session_state["role"]),
        format_func=lambda x: {
            "creator": "✍️ Creator (Drafts & Edits)",
            "reviewer": "🔍 Reviewer (Approval Queue)",
            "fact_owner": "🧪 Fact Owner (Lineage & Drift)",
        }.get(x, x),
    )
    st.session_state["role"] = selected_role

    st.markdown("---")
    st.markdown('<div class="eyebrow">SYSTEM ENVIRONMENT</div>', unsafe_allow_html=True)
    st.markdown(
        """
        - **Engine:** Python 3.11.9
        - **LLM Mode:** `mock` (Deterministic Demo)
        - **Rules Active:** 7 Pure-Python Predicates
        - **Ledger:** SQLite (PRAGMA foreign_keys)
        """
    )

# Main Landing Header
st.title("Brand Rule Lab")
st.markdown(
    """
    #### Pre-Publication Brand Compliance Review Platform with Claim-to-Fact Ledger
    *INKLOOM AI Hackathon MVP*
    """
)

# Core Architecture Card
st.markdown(
    """
    <div class="brand-card">
        <div class="eyebrow">CORE ARCHITECTURAL PHILOSOPHY</div>
        <h3 style="margin-top: 0.2rem; color: #0B6E6A;">AI proposes. Python decides. Humans approve.</h3>
        <p style="margin-bottom: 0;">
            Most generative tools hallucinate compliance or permit prompt-injection jailbreaks. 
            Brand Rule Lab enforces deterministic governance: LLMs extract spans and propose rewrites, 
            pure Python predicates decide pass/fail verdicts, and authorized humans approve claims into an immutable ledger.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Quick Navigation Grid
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center;">
            <div class="eyebrow">STAGE 1</div>
            <h4>✍️ Creator Dashboard</h4>
            <p style="font-size: 0.85rem; color: #555;">Upload drafts (PDF, DOCX, TXT, Image), inspect findings, and accept compliant rewrites.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Creator Workspace", use_container_width=True):
        st.switch_page("pages/1_Creator.py")

with col2:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center;">
            <div class="eyebrow">STAGE 2</div>
            <h4>🔍 Reviewer Queue</h4>
            <p style="font-size: 0.85rem; color: #555;">Approve compliant assets, inspect lineage (<code>SC-xxxx → Fact vX</code>), or log explicit overrides.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Reviewer Queue", use_container_width=True):
        st.switch_page("pages/2_Reviewer.py")

with col3:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center;">
            <div class="eyebrow">STAGE 3</div>
            <h4>🧪 Fact Owner Ledger</h4>
            <p style="font-size: 0.85rem; color: #555;">Update approved facts with 0 LLM calls and 1 SQL update. Watch drift propagate live.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Go to Fact Owner Ledger", use_container_width=True):
        st.switch_page("pages/3_Fact_Owner.py")

with col4:
    st.markdown(
        """
        <div class="brand-card" style="text-align: center;">
            <div class="eyebrow">VERIFICATION</div>
            <h4>📋 Rule Tests Runner</h4>
            <p style="font-size: 0.85rem; color: #555;">Run positive and negative test cases live across all rules for hackathon judges.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Run Rule Test Cases", use_container_width=True):
        st.switch_page("pages/4_Rule_Tests.py")

st.markdown("---")

# Quick System Metrics
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
