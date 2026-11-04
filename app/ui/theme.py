"""
Brand Rule Lab — Visual Design System & Theme
Owned by Agent A4 (Frontend & UX Engineer).

Implements the official design tokens:
- Background: Warm paper #F4F2EC
- Headers & Ink: #13171A
- Primary Accent: Teal #0B6E6A, Light Teal #5CC4B8
- Warning / Escalation: Burnt Orange #B4521A
- Cards: #FFFFFF with 1px #D9D6CC border
- Typography: Serif headers, Sans-serif body, Monospace technical IDs
"""

import streamlit as st

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Lato:wght@400;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,600;0,8..60,700;1,8..60,400&display=swap');

html, body, [class*="css"] {
    font-family: 'Lato', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #13171A;
    background-color: #F4F2EC;
}

h1, h2, h3, h4 {
    font-family: 'Source Serif 4', Georgia, serif;
    font-weight: 700;
    color: #13171A;
    letter-spacing: -0.01em;
}

code, pre, .mono-id {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.88rem;
    background-color: #E8E5DD;
    padding: 2px 6px;
    border-radius: 4px;
    color: #13171A;
}

.eyebrow {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #0B6E6A;
    margin-bottom: 4px;
}

.brand-card {
    background-color: #FFFFFF;
    border: 1px solid #D9D6CC;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(19, 23, 26, 0.04);
}

.banner-synthetic {
    background-color: #EFECE3;
    border-left: 4px solid #0B6E6A;
    padding: 0.65rem 1rem;
    font-size: 0.85rem;
    color: #13171A;
    border-radius: 0 4px 4px 0;
    margin-bottom: 1.25rem;
    display: flex;
    align-items: center;
    gap: 8px;
}

.badge-pill {
    display: inline-block;
    padding: 3px 10px;
    font-size: 0.75rem;
    font-weight: 700;
    border-radius: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.badge-ready { background-color: #E0F2F1; color: #0B6E6A; border: 1px solid #0B6E6A; }
.badge-changes { background-color: #FBE9E7; color: #B4521A; border: 1px solid #B4521A; }
.badge-approved { background-color: #E8F5E9; color: #107C41; border: 1px solid #107C41; }
.badge-escalated { background-color: #ECEFF1; color: #13171A; border: 1px solid #13171A; }

.chip-state {
    display: inline-block;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    border-radius: 4px;
}

.chip-current { background-color: #E8F5E9; color: #107C41; }
.chip-review-required { background-color: #FFF3E0; color: #B4521A; border: 1px solid #B4521A; }
.chip-expired { background-color: #FFEBEE; color: #C62828; }
.chip-unlinked { background-color: #ECEFF1; color: #455A64; border: 1px dashed #78909C; }
.chip-not-observed { background-color: #EDE7F6; color: #512DA8; }

.diff-box {
    background-color: #FAF9F5;
    border: 1px solid #D9D6CC;
    border-radius: 6px;
    padding: 0.75rem;
    font-family: 'Lato', sans-serif;
    font-size: 0.95rem;
}
.diff-del {
    background-color: #FFCDD2;
    color: #B71C1C;
    text-decoration: line-through;
    padding: 2px 4px;
    border-radius: 3px;
}
.diff-add {
    background-color: #C8E6C9;
    color: #1B5E20;
    font-weight: 600;
    padding: 2px 4px;
    border-radius: 3px;
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
            <span>🛡️</span>
            <div>
                <strong>DEMO ENVIRONMENT:</strong> Synthetic demo data only. 
                The claim ledger tracks only claims officially approved inside Brand Rule Lab. 
                Unregistered live copy is designated as <code>NOT_OBSERVED</code>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
