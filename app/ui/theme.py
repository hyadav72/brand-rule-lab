"""
Brand Rule Lab — Visual Design System & Theme
Owned by Agent A4 (Frontend & UX Engineer).

Implements the official Midnight Black & Lime Green Editorial SaaS tokens:
- Canvas: Midnight Black #0B0B0C
- Elevated Surface: Obsidian #141416, Elevated Wells #1C1C20
- High Contrast Text: Pure White #FFFFFF, Zinc #E4E4E7, Muted Slate #A1A1AA
- Hero Accent: Lime Green #C6F432
- Subtle Restraint Borders: #27272A, #3F3F46
- Semantic State Chips: Emerald, Amber, Crimson, Slate, Violet (WCAG AA Compliant)
- Typography: Bold Modern Sans Headings, Inter body, JetBrains Mono IDs
"""

import streamlit as st

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

/* ==========================================================================
   Global Root & Background Styling
   ========================================================================== */
html, body, [class*="css"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #E4E4E7 !important;
    background-color: #0B0B0C !important;
    -webkit-font-smoothing: antialiased;
}

/* Base Headings: Editorial Plus Jakarta Sans */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    letter-spacing: -0.025em !important;
    margin-top: 0.5rem;
}

h1 {
    font-size: 2.2rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.035em !important;
}

/* Paragraphs & Text */
p, label, span {
    color: #E4E4E7;
}

/* ==========================================================================
   Code & Technical Monospace Tokens
   ========================================================================== */
code, pre, .mono-id {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    background-color: #1C1C20 !important;
    color: #C6F432 !important;
    border: 1px solid #27272A !important;
    padding: 2px 7px !important;
    border-radius: 6px !important;
}

pre {
    padding: 1rem !important;
    border-radius: 10px !important;
}

/* ==========================================================================
   Eyebrows & Micro-Typography
   ========================================================================== */
.eyebrow {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.14em !important;
    color: #C6F432 !important;
    margin-bottom: 6px !important;
    display: inline-block;
}

/* ==========================================================================
   Cards & Surfaces (Dark Elevation Architecture)
   ========================================================================== */
.brand-card {
    background-color: #141416 !important;
    border: 1px solid #27272A !important;
    border-radius: 14px !important;
    padding: 1.35rem !important;
    margin-bottom: 1rem !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.brand-card:hover {
    border-color: #3F3F46 !important;
}

/* Banner: Synthetic Demo Boundary */
.banner-synthetic {
    background: linear-gradient(90deg, #18181C 0%, #141416 100%) !important;
    border-left: 4px solid #C6F432 !important;
    border-top: 1px solid #27272A !important;
    border-right: 1px solid #27272A !important;
    border-bottom: 1px solid #27272A !important;
    padding: 0.8rem 1.25rem !important;
    font-size: 0.86rem !important;
    color: #D4D4D8 !important;
    border-radius: 0 10px 10px 0 !important;
    margin-bottom: 1.5rem !important;
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3) !important;
}

/* ==========================================================================
   Status Badges & Lineage Chips (High Contrast Semantic Palette)
   ========================================================================== */
.badge-pill {
    display: inline-block !important;
    padding: 4px 12px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    border-radius: 20px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

.badge-ready {
    background-color: rgba(52, 211, 153, 0.12) !important;
    color: #34D399 !important;
    border: 1px solid rgba(52, 211, 153, 0.4) !important;
}

.badge-changes {
    background-color: rgba(245, 158, 11, 0.12) !important;
    color: #F59E0B !important;
    border: 1px solid rgba(245, 158, 11, 0.4) !important;
}

.badge-approved {
    background-color: rgba(198, 244, 50, 0.15) !important;
    color: #C6F432 !important;
    border: 1px solid #C6F432 !important;
}

.badge-escalated {
    background-color: rgba(239, 68, 68, 0.15) !important;
    color: #EF4444 !important;
    border: 1px solid rgba(239, 68, 68, 0.5) !important;
}

/* Canonical State Chips */
.chip-state {
    display: inline-block !important;
    padding: 3px 9px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    border-radius: 6px !important;
    letter-spacing: 0.05em !important;
    text-decoration: none !important;
}

.chip-current {
    background-color: #132E1B !important;
    color: #34D399 !important;
    border: 1px solid #34D399 !important;
}

.chip-review-required {
    background-color: #3B220B !important;
    color: #F59E0B !important;
    border: 1px solid #F59E0B !important;
}

.chip-expired {
    background-color: #3B0B0B !important;
    color: #EF4444 !important;
    border: 1px solid #EF4444 !important;
}

.chip-unlinked {
    background-color: #18202F !important;
    color: #94A3B8 !important;
    border: 1px dashed #64748B !important;
}

.chip-not-observed {
    background-color: #24143D !important;
    color: #C4B5FD !important;
    border: 1px solid #A78BFA !important;
}

/* ==========================================================================
   Inline Word Diff Box (Obsidian & Lime Green)
   ========================================================================== */
.diff-box {
    background-color: #101012 !important;
    border: 1px solid #27272A !important;
    border-radius: 10px !important;
    padding: 0.95rem !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.94rem !important;
    line-height: 1.6 !important;
    color: #D4D4D8 !important;
}

.diff-del {
    background-color: rgba(239, 68, 68, 0.22) !important;
    color: #FCA5A5 !important;
    text-decoration: line-through !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    margin: 0 2px !important;
}

.diff-add {
    background-color: rgba(198, 244, 50, 0.18) !important;
    color: #C6F432 !important;
    font-weight: 600 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    margin: 0 2px !important;
}

/* ==========================================================================
   Reviewer Queue Table
   ========================================================================== */
.queue-table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.9rem !important;
    background-color: #141416 !important;
}

.queue-table th {
    background-color: #1C1C20 !important;
    padding: 12px 14px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: #C6F432 !important;
    border-bottom: 2px solid #27272A !important;
}

.queue-table td {
    padding: 12px 14px !important;
    border-bottom: 1px solid #222226 !important;
    color: #E4E4E7 !important;
}

.queue-table tr.selected-row {
    background-color: rgba(198, 244, 50, 0.08) !important;
    border-left: 4px solid #C6F432 !important;
}

.queue-table tr:hover:not(.selected-row) {
    background-color: #1A1A1E !important;
}

/* ==========================================================================
   Annotated Draft & Span Highlights
   ========================================================================== */
.annotated-span {
    transition: all 0.2s ease !important;
    cursor: pointer !important;
}

.annotated-span:target, .brand-card:target {
    outline: 2px solid #C6F432 !important;
    box-shadow: 0 0 16px rgba(198, 244, 50, 0.35) !important;
}

.finding-anchor {
    position: relative;
    top: -60px;
    display: inline-block;
    visibility: hidden;
}

/* ==========================================================================
   Streamlit Component Deep Dark Overrides
   ========================================================================== */
/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #101012 !important;
    border-right: 1px solid #27272A !important;
}

section[data-testid="stSidebar"] hr {
    border-color: #27272A !important;
}

/* Buttons */
.stButton > button {
    background-color: #1C1C20 !important;
    color: #FFFFFF !important;
    border: 1px solid #3F3F46 !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    padding: 0.55rem 1.25rem !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.stButton > button:hover {
    border-color: #C6F432 !important;
    color: #C6F432 !important;
    box-shadow: 0 0 14px rgba(198, 244, 50, 0.18) !important;
    transform: translateY(-1px);
}

.stButton > button:active {
    transform: translateY(0);
}

/* Primary High-Impact Button */
.stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"] {
    background-color: #C6F432 !important;
    color: #0B0B0C !important;
    border: 1px solid #C6F432 !important;
    font-weight: 700 !important;
    box-shadow: 0 0 16px rgba(198, 244, 50, 0.25) !important;
}

.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="baseButton-primary"]:hover {
    background-color: #D9F968 !important;
    color: #0B0B0C !important;
    box-shadow: 0 0 24px rgba(198, 244, 50, 0.45) !important;
}

/* Form Inputs, Selectboxes & TextAreas */
div[data-baseweb="select"] > div, input, textarea {
    background-color: #141416 !important;
    color: #FFFFFF !important;
    border-color: #27272A !important;
    border-radius: 8px !important;
}

div[data-baseweb="select"] * {
    color: #FFFFFF !important;
}

/* Metric Cards */
div[data-testid="stMetric"] {
    background-color: #141416 !important;
    border: 1px solid #27272A !important;
    border-radius: 14px !important;
    padding: 1.1rem 1.25rem !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35) !important;
}

div[data-testid="stMetricLabel"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: #A1A1AA !important;
}

div[data-testid="stMetricValue"] {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 800 !important;
    color: #FFFFFF !important;
}

/* Tabs */
div[data-baseweb="tab-list"] {
    background-color: transparent !important;
    border-bottom: 1px solid #27272A !important;
    gap: 8px !important;
}

div[data-baseweb="tab"] {
    background-color: transparent !important;
    color: #A1A1AA !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 8px 16px !important;
}

div[data-baseweb="tab"][aria-selected="true"] {
    color: #C6F432 !important;
    border-bottom: 2px solid #C6F432 !important;
}

/* Expanders */
details[data-testid="stExpander"] {
    background-color: #141416 !important;
    border: 1px solid #27272A !important;
    border-radius: 12px !important;
    margin-bottom: 1rem !important;
}

summary[data-testid="stExpanderHeader"] {
    color: #FFFFFF !important;
    font-weight: 600 !important;
}

summary[data-testid="stExpanderHeader"]:hover {
    color: #C6F432 !important;
}

/* Horizontal Dividers */
hr {
    border-color: #27272A !important;
    margin: 1.5rem 0 !important;
}

/* Alerts & Notices */
div[data-testid="stAlert"] {
    background-color: #141416 !important;
    border: 1px solid #27272A !important;
    border-radius: 10px !important;
    color: #E4E4E7 !important;
}

/* File Uploader Container */
div[data-testid="stFileUploader"] {
    background-color: #141416 !important;
    border: 1px dashed #3F3F46 !important;
    border-radius: 14px !important;
    padding: 1rem !important;
}

div[data-testid="stFileUploader"]:hover {
    border-color: #C6F432 !important;
}

/* ==========================================================================
   WCAG AA Keyboard Navigation Focus Ring
   ========================================================================== */
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, [tabindex]:focus-visible {
    outline: 2px solid #C6F432 !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(198, 244, 50, 0.3) !important;
}

.chip-state:focus-visible {
    outline: 2px solid #C6F432 !important;
    outline-offset: 1px !important;
}
</style>
"""


def apply_theme():
    """Inject custom design tokens and stylesheets into Streamlit."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_banner():
    """Render the persistent synthetic data and coverage boundary banner."""
    st.markdown(
        """
        <div class="banner-synthetic">
            <span style="font-size: 1.2rem;">🛡️</span>
            <div>
                <strong style="color: #C6F432;">DEMO ENVIRONMENT:</strong> Synthetic demo data only. 
                The claim ledger tracks only claims officially approved inside Brand Rule Lab. 
                Unregistered live copy is designated as <code>NOT_OBSERVED</code>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_role_switcher() -> str:
    """
    Render global role switcher in the sidebar across all application pages.
    Maintains and synchronizes active persona in st.session_state['role'].
    Returns the currently active role string.
    """
    from core.models import Role
    from core.llm import get_llm_status
    from core.db import get_db_path
    from pathlib import Path

    if "role" not in st.session_state:
        st.session_state["role"] = Role.CREATOR.value

    valid_roles = [Role.CREATOR.value, Role.REVIEWER.value, Role.FACT_OWNER.value]
    current_role = st.session_state.get("role", Role.CREATOR.value)
    if current_role not in valid_roles:
        current_role = Role.CREATOR.value
        st.session_state["role"] = current_role

    def _sync_role():
        if "global_role_selector" in st.session_state:
            st.session_state["role"] = st.session_state["global_role_selector"]

    with st.sidebar:
        st.markdown('<div class="eyebrow">ACTIVE PERSONA</div>', unsafe_allow_html=True)
        selected_role = st.selectbox(
            "Switch System Role",
            options=valid_roles,
            index=valid_roles.index(current_role),
            format_func=lambda x: {
                "creator": "✍️ Creator (Drafts & Edits)",
                "reviewer": "🔍 Reviewer (Approval Queue)",
                "fact_owner": "🧪 Fact Owner (Lineage & Drift)",
            }.get(x, x),
            key="global_role_selector",
            on_change=_sync_role,
        )
        st.session_state["role"] = selected_role
        st.caption("ℹ️ *Demo Persona Simulation: Simulates RBAC authorization boundaries for demo evaluation. Not production authentication.*")

        st.markdown("---")
        st.markdown('<div class="eyebrow">SYSTEM ENVIRONMENT</div>', unsafe_allow_html=True)
        status_info = get_llm_status()
        if status_info["mode"] == "live":
            if status_info["fallback_active"]:
                llm_text = f"live (fallback active: {status_info['fallback_reason']})"
            else:
                llm_text = f"live ({status_info['provider']}: {status_info['model']})"
        else:
            llm_text = "mock (Deterministic Demo)"

        active_db = Path(get_db_path()).as_posix()
        st.markdown(
            f"""
            - **Engine:** `Python 3.11.9`
            - **Database:** `{active_db}`
            - **LLM Mode:** `{llm_text}`
            - **Rules Active:** `12 Pure-Python Rules`
            - **Ledger:** `SQLite (PRAGMA foreign_keys)`
            """
        )

    return st.session_state["role"]
