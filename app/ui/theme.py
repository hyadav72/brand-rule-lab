"""
Brand Rule Lab — Visual Design System & Theme
Owned by Agent A4 (Frontend & UX Engineer).

System-Based Adaptive Theme Architecture:
- System Mode (Default): Dynamically adapts to browser/OS light or dark preference via CSS media queries.
- Light Mode:
    - Canvas: #F8F9FA
    - Cards: #FFFFFF, Elevated #F4F5F7
    - Primary Text: #18181B, Secondary: #71717A, Muted: #A1A1AA
    - Borders: #E4E4E7, Elevated: #D4D4D8
    - Accent: #C6F432 (selective hero green with accessible high contrast text tokens)
- Dark Mode:
    - Canvas: #0B0B0C
    - Cards: #141416, Elevated #1C1C20
    - Primary Text: #FFFFFF, Secondary: #A1A1AA, Muted: #71717A
    - Borders: #27272A, Elevated: #3F3F46
    - Accent: #C6F432
"""

from typing import Optional
import streamlit as st


LIGHT_VARS = """
    --bg-canvas: #F8F9FA;
    --bg-card: #FFFFFF;
    --bg-card-elevated: #F4F5F7;
    --bg-sidebar: #FFFFFF;
    --text-primary: #18181B;
    --text-secondary: #71717A;
    --text-muted: #A1A1AA;
    --border-subtle: #E4E4E7;
    --border-elevated: #D4D4D8;
    --accent: #C6F432;
    --accent-contrast: #0B0B0C;
    --accent-text: #365314;
    --code-bg: #F1F3F5;
    --code-text: #18181B;
    --diff-box-bg: #F8F9FA;
    --table-header-bg: #F4F5F7;
    --hover-bg: #F1F3F5;
    --nav-active-bg: rgba(198, 244, 50, 0.28);
    --nav-active-text: #18181B;
    --card-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
    --banner-shadow: 0 1px 6px rgba(0, 0, 0, 0.05);
    color-scheme: light;
"""

DARK_VARS = """
    --bg-canvas: #0B0B0C;
    --bg-card: #141416;
    --bg-card-elevated: #1C1C20;
    --bg-sidebar: #101012;
    --text-primary: #FFFFFF;
    --text-secondary: #A1A1AA;
    --text-muted: #71717A;
    --border-subtle: #27272A;
    --border-elevated: #3F3F46;
    --accent: #C6F432;
    --accent-contrast: #0B0B0C;
    --accent-text: #C6F432;
    --code-bg: #1C1C20;
    --code-text: #C6F432;
    --diff-box-bg: #101012;
    --table-header-bg: #1C1C20;
    --hover-bg: #1A1A1E;
    --nav-active-bg: rgba(198, 244, 50, 0.12);
    --nav-active-text: #C6F432;
    --card-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
    --banner-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
    color-scheme: dark;
"""

LIGHT_BADGES_CSS = """
.badge-ready {
    background-color: rgba(16, 185, 129, 0.12) !important;
    color: #047857 !important;
    border: 1px solid rgba(16, 185, 129, 0.4) !important;
}
.badge-changes {
    background-color: rgba(245, 158, 11, 0.15) !important;
    color: #B45309 !important;
    border: 1px solid rgba(245, 158, 11, 0.4) !important;
}
.badge-approved {
    background-color: rgba(198, 244, 50, 0.35) !important;
    color: #2E4C00 !important;
    border: 1px solid #65A30D !important;
}
.badge-escalated {
    background-color: rgba(239, 68, 68, 0.12) !important;
    color: #B91C1C !important;
    border: 1px solid rgba(239, 68, 68, 0.4) !important;
}
.chip-current {
    background-color: #D1FAE5 !important;
    color: #065F46 !important;
    border: 1px solid #10B981 !important;
}
.chip-review-required {
    background-color: #FEF3C7 !important;
    color: #92400E !important;
    border: 1px solid #F59E0B !important;
}
.chip-expired {
    background-color: #FEE2E2 !important;
    color: #991B1B !important;
    border: 1px solid #EF4444 !important;
}
.chip-unlinked {
    background-color: #F1F5F9 !important;
    color: #334155 !important;
    border: 1px dashed #94A3B8 !important;
}
.chip-not-observed {
    background-color: #EDE9FE !important;
    color: #5B21B6 !important;
    border: 1px solid #8B5CF6 !important;
}
.diff-del {
    background-color: rgba(239, 68, 68, 0.15) !important;
    color: #DC2626 !important;
    text-decoration: line-through !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    margin: 0 2px !important;
}
.diff-add {
    background-color: rgba(198, 244, 50, 0.35) !important;
    color: #2E4C00 !important;
    font-weight: 600 !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    margin: 0 2px !important;
}
"""

DARK_BADGES_CSS = """
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
"""

BASE_STRUCTURAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

/* ==========================================================================
   Global Canvas & Root Layout
   ========================================================================== */
html, body, [class*="css"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: var(--text-primary) !important;
    background-color: var(--bg-canvas) !important;
    -webkit-font-smoothing: antialiased;
}

header[data-testid="stHeader"] {
    background-color: transparent !important;
}

header[data-testid="stHeader"] button, button[data-testid="stSidebarCollapseButton"] {
    color: var(--text-primary) !important;
}

/* Headings: Editorial Modern Hierarchy */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-weight: 700 !important;
    color: var(--text-primary) !important;
    letter-spacing: -0.025em !important;
    margin-top: 0.5rem;
}

h1 {
    font-size: 2.2rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.035em !important;
}

/* Text Hierarchy */
p, label, span {
    color: var(--text-primary);
}

.text-secondary, [data-testid="stMarkdownContainer"] p {
    color: var(--text-secondary);
}

.text-muted {
    color: var(--text-muted);
}

/* ==========================================================================
   Code & Technical Monospace Tokens
   ========================================================================== */
code, pre, .mono-id {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    background-color: var(--code-bg) !important;
    color: var(--code-text) !important;
    border: 1px solid var(--border-subtle) !important;
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
    color: var(--accent-text) !important;
    margin-bottom: 6px !important;
    display: inline-block;
}

/* ==========================================================================
   Cards & Elevated Surfaces
   ========================================================================== */
.brand-card {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 14px !important;
    padding: 1.35rem !important;
    margin-bottom: 1rem !important;
    box-shadow: var(--card-shadow) !important;
    color: var(--text-primary) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.brand-card:hover {
    border-color: var(--border-elevated) !important;
}

.brand-card h1, .brand-card h2, .brand-card h3, .brand-card h4, .brand-card h5, .brand-card h6 {
    color: var(--text-primary) !important;
}

.brand-card p {
    color: var(--text-secondary) !important;
}

.brand-card strong {
    color: var(--text-primary) !important;
}

/* ==========================================================================
   Banner: Synthetic Demo Boundary
   ========================================================================== */
.banner-synthetic {
    background: var(--bg-card-elevated) !important;
    border-left: 4px solid var(--accent) !important;
    border-top: 1px solid var(--border-subtle) !important;
    border-right: 1px solid var(--border-subtle) !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    padding: 0.8rem 1.25rem !important;
    font-size: 0.86rem !important;
    color: var(--text-primary) !important;
    border-radius: 0 10px 10px 0 !important;
    margin-bottom: 1.5rem !important;
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
    box-shadow: var(--banner-shadow) !important;
}

/* ==========================================================================
   Badges & State Chips Base Styles
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

/* ==========================================================================
   Inline Word Diff Box
   ========================================================================== */
.diff-box {
    background-color: var(--diff-box-bg) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 10px !important;
    padding: 0.95rem !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.94rem !important;
    line-height: 1.6 !important;
    color: var(--text-primary) !important;
}

/* ==========================================================================
   Reviewer Queue Table
   ========================================================================== */
.queue-table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.9rem !important;
    background-color: var(--bg-card) !important;
}

.queue-table th {
    background-color: var(--table-header-bg) !important;
    padding: 12px 14px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: var(--accent-text) !important;
    border-bottom: 2px solid var(--border-subtle) !important;
}

.queue-table td {
    padding: 12px 14px !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
}

.queue-table tr.selected-row {
    background-color: var(--nav-active-bg) !important;
    border-left: 4px solid var(--accent) !important;
}

.queue-table tr:hover:not(.selected-row) {
    background-color: var(--hover-bg) !important;
}

/* ==========================================================================
   Annotated Draft & Span Highlights
   ========================================================================== */
.annotated-span {
    transition: all 0.2s ease !important;
    cursor: pointer !important;
}

.annotated-span:target, .brand-card:target {
    outline: 2px solid var(--accent) !important;
    box-shadow: 0 0 16px rgba(198, 244, 50, 0.35) !important;
}

.finding-anchor {
    position: relative;
    top: -60px;
    display: inline-block;
    visibility: hidden;
}

/* ==========================================================================
   Sidebar & Navigation Overrides
   ========================================================================== */
section[data-testid="stSidebar"] {
    background-color: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border-subtle) !important;
}

section[data-testid="stSidebar"] hr {
    border-color: var(--border-subtle) !important;
}

section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label {
    color: var(--text-primary) !important;
}

/* Sidebar Navigation Items */
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    padding-top: 0.5rem !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
    border-radius: 8px !important;
    padding: 8px 12px !important;
    margin-bottom: 3px !important;
    transition: all 0.15s ease !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span {
    color: var(--text-primary) !important;
    font-size: 0.92rem !important;
    font-weight: 500 !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
    background-color: var(--hover-bg) !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
    background-color: var(--nav-active-bg) !important;
    border-left: 3px solid var(--accent) !important;
    border-radius: 0 8px 8px 0 !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] span {
    color: var(--nav-active-text) !important;
    font-weight: 700 !important;
}

/* ==========================================================================
   Buttons
   ========================================================================== */
.stButton > button {
    background-color: var(--bg-card-elevated) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-elevated) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    padding: 0.55rem 1.25rem !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.stButton > button:hover {
    border-color: var(--accent) !important;
    color: var(--nav-active-text) !important;
    box-shadow: 0 0 14px rgba(198, 244, 50, 0.2) !important;
    transform: translateY(-1px);
}

.stButton > button:active {
    transform: translateY(0);
}

/* Primary High-Impact Button */
.stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"] {
    background-color: var(--accent) !important;
    color: var(--accent-contrast) !important;
    border: 1px solid var(--accent) !important;
    font-weight: 700 !important;
    box-shadow: 0 0 16px rgba(198, 244, 50, 0.25) !important;
}

.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="baseButton-primary"]:hover {
    background-color: #D9F968 !important;
    color: #0B0B0C !important;
    box-shadow: 0 0 24px rgba(198, 244, 50, 0.45) !important;
}

/* ==========================================================================
   Form Inputs, Selectboxes & TextAreas
   ========================================================================== */
div[data-baseweb="select"] > div, input, textarea {
    background-color: var(--bg-card) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-subtle) !important;
    border-radius: 8px !important;
}

div[data-baseweb="select"] * {
    color: var(--text-primary) !important;
}

div[data-baseweb="popover"], div[data-baseweb="menu"], ul[data-baseweb="menu"] {
    background-color: var(--bg-card) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-subtle) !important;
}

li[data-baseweb="menu-item"] {
    color: var(--text-primary) !important;
}

li[data-baseweb="menu-item"]:hover {
    background-color: var(--hover-bg) !important;
}

/* ==========================================================================
   Metric Cards
   ========================================================================== */
div[data-testid="stMetric"] {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 14px !important;
    padding: 1.1rem 1.25rem !important;
    box-shadow: var(--card-shadow) !important;
}

div[data-testid="stMetricLabel"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: var(--text-secondary) !important;
}

div[data-testid="stMetricValue"] {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 800 !important;
    color: var(--text-primary) !important;
}

/* ==========================================================================
   Tabs
   ========================================================================== */
div[data-baseweb="tab-list"] {
    background-color: transparent !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    gap: 8px !important;
}

div[data-baseweb="tab"] {
    background-color: transparent !important;
    color: var(--text-secondary) !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 8px 16px !important;
}

div[data-baseweb="tab"][aria-selected="true"] {
    color: var(--nav-active-text) !important;
    border-bottom: 2px solid var(--accent) !important;
}

/* ==========================================================================
   Expanders
   ========================================================================== */
details[data-testid="stExpander"] {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 12px !important;
    margin-bottom: 1rem !important;
}

summary[data-testid="stExpanderHeader"] {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
}

summary[data-testid="stExpanderHeader"]:hover {
    color: var(--accent-text) !important;
}

/* ==========================================================================
   Horizontal Dividers
   ========================================================================== */
hr {
    border-color: var(--border-subtle) !important;
    margin: 1.5rem 0 !important;
}

/* ==========================================================================
   Alerts & Notices
   ========================================================================== */
div[data-testid="stAlert"] {
    background-color: var(--bg-card-elevated) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}

div[data-testid="stAlert"] p {
    color: var(--text-primary) !important;
}

/* ==========================================================================
   File Uploader Container
   ========================================================================== */
div[data-testid="stFileUploader"] {
    background-color: var(--bg-card) !important;
    border: 1px dashed var(--border-elevated) !important;
    border-radius: 14px !important;
    padding: 1rem !important;
}

div[data-testid="stFileUploader"]:hover {
    border-color: var(--accent) !important;
}

/* ==========================================================================
   Audit Item
   ========================================================================== */
.audit-event-item {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    padding: 8px 0 !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    color: var(--text-primary) !important;
}

/* ==========================================================================
   WCAG AA Keyboard Navigation Focus Ring
   ========================================================================== */
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, [tabindex]:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 2px !important;
    box-shadow: 0 0 0 4px rgba(198, 244, 50, 0.3) !important;
}

.chip-state:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 1px !important;
}
"""


def get_theme_css(mode: str) -> str:
    """Generate complete CSS stylesheet based on requested theme mode."""
    mode_clean = (mode or "system").strip().lower()

    if mode_clean == "light":
        theme_vars = f":root, .stApp {{\n{LIGHT_VARS}\n}}"
        badges_css = LIGHT_BADGES_CSS
    elif mode_clean == "dark":
        theme_vars = f":root, .stApp {{\n{DARK_VARS}\n}}"
        badges_css = DARK_BADGES_CSS
    else:  # system (adaptive)
        theme_vars = f"""
:root, .stApp {{
{LIGHT_VARS}
}}

@media (prefers-color-scheme: dark) {{
    :root, .stApp {{
{DARK_VARS}
    }}
}}
"""
        badges_css = f"""
{LIGHT_BADGES_CSS}

@media (prefers-color-scheme: dark) {{
{DARK_BADGES_CSS}
}}
"""

    return f"""<style>
{theme_vars}
{BASE_STRUCTURAL_CSS}
{badges_css}
</style>
"""


def apply_theme(mode: Optional[str] = None):
    """
    Inject custom design tokens and stylesheets into Streamlit.
    Supports:
    - 'system' (default): Follows browser/OS color scheme preference via CSS media queries.
    - 'light': Forces Light Mode tokens.
    - 'dark': Forces Dark Mode tokens.
    """
    # Check query parameters if present to allow direct theme deep-linking and screenshotting
    try:
        qp = st.query_params.get("theme")
        if qp in ("system", "light", "dark"):
            st.session_state["theme_mode"] = qp
    except Exception:
        pass

    if "theme_mode" not in st.session_state:
        st.session_state["theme_mode"] = "system"

    active_mode = mode or st.session_state.get("theme_mode", "system")
    css = get_theme_css(active_mode)
    st.markdown(css, unsafe_allow_html=True)


def render_banner():
    """Render the persistent synthetic data and coverage boundary banner."""
    st.markdown(
        """
        <div class="banner-synthetic">
            <span style="font-size: 1.2rem;">🛡️</span>
            <div>
                <strong style="color: var(--accent-text);">DEMO ENVIRONMENT:</strong> Synthetic demo data only. 
                The claim ledger tracks only claims officially approved inside Brand Rule Lab. 
                Unregistered live copy is designated as <code>NOT_OBSERVED</code>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_role_switcher() -> str:
    """
    Render global role switcher and theme preference in the sidebar across all application pages.
    Maintains and synchronizes active persona in st.session_state['role'] and theme in st.session_state['theme_mode'].
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
        # System / Light / Dark Theme Selector
        st.markdown('<div class="eyebrow">THEME PREFERENCE</div>', unsafe_allow_html=True)
        theme_options = ["system", "light", "dark"]
        current_theme = st.session_state.get("theme_mode", "system")
        if current_theme not in theme_options:
            current_theme = "system"
            st.session_state["theme_mode"] = current_theme

        def _sync_theme():
            if "global_theme_selector" in st.session_state:
                st.session_state["theme_mode"] = st.session_state["global_theme_selector"]

        selected_theme = st.selectbox(
            "Appearance Mode",
            options=theme_options,
            index=theme_options.index(current_theme),
            format_func=lambda x: {
                "system": "🖥️ System (Adaptive)",
                "light": "☀️ Light Mode",
                "dark": "🌙 Dark Mode",
            }.get(x, x),
            key="global_theme_selector",
            on_change=_sync_theme,
        )
        st.session_state["theme_mode"] = selected_theme
        if selected_theme == "system":
            st.caption("ℹ️ *System mode dynamically adapts to your OS/browser dark or light preference.*")
        elif selected_theme == "light":
            st.caption("ℹ️ *Light mode active: clean high-contrast editorial canvas.*")
        else:
            st.caption("ℹ️ *Dark mode active: Obsidian & Midnight Black SaaS canvas.*")

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
