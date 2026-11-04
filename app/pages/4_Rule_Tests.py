"""
Brand Rule Lab — Rule Test Runner
Owned by Agent A4 (Frontend & UX Engineer) and A2 (Rules Engineer).

Live verification dashboard for hackathon judges to inspect declarative rule tests.
"""

from __future__ import annotations
import streamlit as st
from app.ui.theme import apply_theme, render_banner
from core.rules.engine import RuleEngine

apply_theme()
render_banner()

st.title("📋 Deterministic Rule Test Runner")
st.markdown('<div class="eyebrow">QUALITY GATES & AUDITABLE TEST PROOFS</div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="brand-card">
        <p style="margin-bottom:0;">
            Every compliance check in Brand Rule Lab is defined as an auditable JSON specification.
            <strong>Quality Gate:</strong> The engine strictly refuses to load any rule that lacks unit tests or is not signed by a compliance owner.
            Below is the live test verification demonstrating that all rules execute deterministically in pure Python.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

engine = RuleEngine()
st.write(f"Loaded **{len(engine.rules)} approved rules** from repository.")

col1, col2 = st.columns([1, 1])
with col1:
    selected_rule = st.selectbox("Inspect Specific Rule:", options=["ALL RULES"] + list(engine.rules.keys()))
with col2:
    filter_type = st.selectbox("Filter Test Type:", options=["ALL", "positive", "negative"])

rule_to_run = None if selected_rule == "ALL RULES" else selected_rule
all_results = engine.run_rule_test_cases(rule_to_run)

if filter_type != "ALL":
    filtered_results = [r for r in all_results if r["test_type"] == filter_type]
else:
    filtered_results = all_results

passed_count = sum(1 for r in filtered_results if r["passed"])
total_count = len(filtered_results)
pass_rate = (passed_count / total_count * 100) if total_count else 100.0

# Metric Cards
m1, m2, m3 = st.columns(3)
m1.metric("Total Test Cases Run", total_count)
m2.metric("Tests Passing", passed_count)
m3.metric("Verification Pass Rate", f"{pass_rate:.1f}%")

st.markdown("---")

# Render Test Results Table
st.markdown("#### Test Execution Breakdown")

for r in filtered_results:
    is_pass = r["passed"]
    badge = '<span class="badge-pill badge-approved">PASS</span>' if is_pass else '<span class="badge-pill badge-changes">FAIL</span>'
    type_badge = f'<span class="badge-pill badge-ready">{r["test_type"].upper()}</span>'

    st.markdown(
        f"""
        <div class="brand-card" style="padding: 0.8rem 1.2rem; margin-bottom: 0.5rem; border-left: 4px solid {'#107C41' if is_pass else '#B4521A'};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <strong>Rule: <code>{r['rule_id']}</code></strong> &bull; {type_badge}
                </div>
                <div>{badge}</div>
            </div>
            <div style="font-size:0.9rem; margin-top:0.3rem;">
                <strong>Input:</strong> <code>"{r['input']}"</code>
            </div>
            <div style="font-size:0.8rem; color:#555; margin-top:0.2rem;">
                Expected: <em>{r['expected']}</em> &bull; Actual: <em>{r['actual']}</em>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
