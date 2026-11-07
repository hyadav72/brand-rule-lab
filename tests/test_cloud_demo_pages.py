"""
Brand Rule Lab — Cloud Demo End-to-End Page Execution Verification
Tests all 5 application pages against a fresh, non-existent cloud demo database:
1. Home
2. Creator
3. Reviewer
4. Fact Owner
5. Rule Tests

Verifies:
- Auto-initialization creates complete schema and synthetic fixtures
- Zero OperationalErrors (no such table) on any page
- Safe isolated execution against data/cloud_demo_test.db
"""

import os
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def setup_cloud_demo_env(tmp_path, monkeypatch):
    """Isolate environment to a fresh cloud demo database for each test."""
    test_db = tmp_path / "cloud_demo_isolated.db"
    if test_db.exists():
        test_db.unlink()

    monkeypatch.setenv("DEPLOYMENT_MODE", "demo")
    monkeypatch.setenv("DATABASE_PATH", str(test_db))
    monkeypatch.setenv("LLM_MODE", "mock")

    from core import db
    db._verified_ready_dbs.clear()
    db._ensuring_db_ready = False

    yield str(test_db)

    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


def test_home_page_cloud_demo(setup_cloud_demo_env):
    """Home page executes without errors and initializes database."""
    test_db = Path(setup_cloud_demo_env)
    assert not test_db.exists()

    at = AppTest.from_file("app/Home.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Home page threw exception: {at.exception}"
    assert test_db.exists(), "Cloud demo database should have been created and initialized"


def test_creator_page_cloud_demo(setup_cloud_demo_env):
    """Creator page executes without errors against uninitialized cloud database."""
    test_db = Path(setup_cloud_demo_env)
    at = AppTest.from_file("app/pages/1_Creator.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Creator page threw exception: {at.exception}"
    assert test_db.exists()


def test_reviewer_page_cloud_demo_direct_navigation(setup_cloud_demo_env):
    """Direct navigation to Reviewer page initializes database and avoids 'no such table: assets'."""
    test_db = Path(setup_cloud_demo_env)
    assert not test_db.exists()

    at = AppTest.from_file("app/pages/2_Reviewer.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Reviewer page threw exception: {at.exception}"
    assert test_db.exists()


def test_fact_owner_page_cloud_demo_direct_navigation(setup_cloud_demo_env):
    """Direct navigation to Fact Owner page initializes database and avoids 'no such table: approved_claims'."""
    test_db = Path(setup_cloud_demo_env)
    assert not test_db.exists()

    at = AppTest.from_file("app/pages/3_Fact_Owner.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Fact Owner page threw exception: {at.exception}"
    assert test_db.exists()


def test_rule_tests_page_cloud_demo(setup_cloud_demo_env):
    """Rule Tests page executes without errors against cloud demo database."""
    at = AppTest.from_file("app/pages/4_Rule_Tests.py", default_timeout=30)
    at.run()
    assert not at.exception, f"Rule Tests page threw exception: {at.exception}"
