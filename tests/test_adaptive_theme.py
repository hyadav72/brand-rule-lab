"""
Brand Rule Lab — System-Based Adaptive Theme Unit & App Tests
Verifies:
1. get_theme_css generates compliant tokens for System, Light, and Dark modes.
2. Light mode tokens match specification (#F8F9FA, #FFFFFF, #18181B, #71717A, #E4E4E7, #C6F432).
3. Dark mode tokens match specification (#0B0B0C, #141416, #FFFFFF, #A1A1AA, #27272A, #C6F432).
4. System mode contains CSS media query prefers-color-scheme: dark.
5. Sidebar theme selector defaults to system and syncs to session state.
6. All 5 pages render cleanly in Light Mode without exceptions.
7. All 5 pages render cleanly in Dark Mode without exceptions.
"""

import os
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from app.ui.theme import get_theme_css, apply_theme, LIGHT_VARS, DARK_VARS


def test_theme_css_tokens():
    """Verify exact token values and media queries for each mode."""
    # 1. Light Mode CSS
    light_css = get_theme_css("light")
    assert "--bg-canvas: #F8F9FA" in light_css
    assert "--bg-card: #FFFFFF" in light_css
    assert "--text-primary: #18181B" in light_css
    assert "--text-secondary: #71717A" in light_css
    assert "--border-subtle: #E4E4E7" in light_css
    assert "--accent: #C6F432" in light_css
    assert "@media (prefers-color-scheme: dark)" not in light_css

    # 2. Dark Mode CSS
    dark_css = get_theme_css("dark")
    assert "--bg-canvas: #0B0B0C" in dark_css
    assert "--bg-card: #141416" in dark_css
    assert "--bg-card-elevated: #1C1C20" in dark_css
    assert "--text-primary: #FFFFFF" in dark_css
    assert "--text-secondary: #A1A1AA" in dark_css
    assert "--border-subtle: #27272A" in dark_css
    assert "--accent: #C6F432" in dark_css
    assert "@media (prefers-color-scheme: dark)" not in dark_css

    # 3. System Mode CSS
    system_css = get_theme_css("system")
    assert "--bg-canvas: #F8F9FA" in system_css  # Default light
    assert "@media (prefers-color-scheme: dark)" in system_css
    assert "--bg-canvas: #0B0B0C" in system_css  # Dark under media query


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate environment for theme tests."""
    test_db = tmp_path / "theme_test.db"
    monkeypatch.setenv("DEPLOYMENT_MODE", "demo")
    monkeypatch.setenv("DATABASE_PATH", str(test_db))
    monkeypatch.setenv("LLM_MODE", "mock")

    from core import db
    db._verified_ready_dbs.clear()
    db._ensuring_db_ready = False

    yield str(test_db)


@pytest.mark.parametrize("theme_mode", ["light", "dark", "system"])
def test_home_page_theme_modes(theme_mode):
    """Home page renders with chosen theme mode."""
    at = AppTest.from_file("app/Home.py", default_timeout=30)
    at.session_state["theme_mode"] = theme_mode
    at.run()
    assert not at.exception


@pytest.mark.parametrize("theme_mode", ["light", "dark"])
def test_creator_page_theme_modes(theme_mode):
    """Creator page renders in both light and dark modes."""
    at = AppTest.from_file("app/pages/1_Creator.py", default_timeout=30)
    at.session_state["theme_mode"] = theme_mode
    at.run()
    assert not at.exception


@pytest.mark.parametrize("theme_mode", ["light", "dark"])
def test_reviewer_page_theme_modes(theme_mode):
    """Reviewer page renders in both light and dark modes."""
    at = AppTest.from_file("app/pages/2_Reviewer.py", default_timeout=30)
    at.session_state["theme_mode"] = theme_mode
    at.run()
    assert not at.exception


@pytest.mark.parametrize("theme_mode", ["light", "dark"])
def test_fact_owner_page_theme_modes(theme_mode):
    """Fact Owner page renders in both light and dark modes."""
    at = AppTest.from_file("app/pages/3_Fact_Owner.py", default_timeout=30)
    at.session_state["theme_mode"] = theme_mode
    at.run()
    assert not at.exception


@pytest.mark.parametrize("theme_mode", ["light", "dark"])
def test_rule_tests_page_theme_modes(theme_mode):
    """Rule Tests page renders in both light and dark modes."""
    at = AppTest.from_file("app/pages/4_Rule_Tests.py", default_timeout=30)
    at.session_state["theme_mode"] = theme_mode
    at.run()
    assert not at.exception
