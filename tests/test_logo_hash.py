"""
Brand Rule Lab — Logo Perceptual Hash (L-01) Verification Tests
Owned by Agent A2 (Rules & Accessibility Engineer).

Tests Pillow-based perceptual difference hashing (dHash) and Hamming distance threshold (<=10/64 bits).
Verifies:
1. Exact logo match (Hamming distance == 0)
2. Resized logo match (Hamming distance <= 2 <= threshold 10)
3. Slightly altered logo match (Hamming distance <= threshold 10)
4. Completely different logo violation (Hamming distance > threshold 10)
5. Missing reference logo boundary handling (coverage boundary notice, no crash)
"""

from pathlib import Path
from PIL import Image, ImageDraw
import io
import pytest

from core.rules.predicates import (
    compute_dhash,
    compute_hamming_distance,
    predicate_logo_hash,
)
from core.rules.engine import RuleEngine
from core.models import ExtractedDoc


DEMO_ASSETS_DIR = Path(__file__).parent.parent / "data" / "demo_assets"


@pytest.fixture(scope="module")
def logo_assets():
    """Ensure test logo assets exist and return their paths."""
    ref_path = DEMO_ASSETS_DIR / "monsoon_logo_ref.png"
    resized_path = DEMO_ASSETS_DIR / "monsoon_logo_resized.png"
    altered_path = DEMO_ASSETS_DIR / "monsoon_logo_altered.png"
    diff_path = DEMO_ASSETS_DIR / "monsoon_logo_different.png"

    # If any is missing, generate them dynamically
    if not (ref_path.exists() and resized_path.exists() and altered_path.exists() and diff_path.exists()):
        DEMO_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        ref = Image.new("RGB", (240, 80), color=(15, 23, 42))
        d_ref = ImageDraw.Draw(ref)
        d_ref.polygon([(40, 20), (55, 50), (25, 50)], fill=(45, 212, 191))
        d_ref.ellipse([25, 40, 55, 65], fill=(45, 212, 191))
        d_ref.text((75, 30), "MONSOON", fill=(255, 255, 255))
        d_ref.text((75, 45), "CLEAR SKIN", fill=(148, 163, 184))
        ref.save(ref_path)

        resized = ref.resize((480, 160), Image.Resampling.LANCZOS)
        resized.save(resized_path)

        altered = ref.copy()
        d_alt = ImageDraw.Draw(altered)
        d_alt.text((75, 45), "CLEAR SKIN", fill=(160, 175, 195))
        altered.save(altered_path)

        diff = Image.new("RGB", (240, 80), color=(255, 120, 0))
        d_diff = ImageDraw.Draw(diff)
        d_diff.rectangle([20, 15, 65, 65], fill=(128, 0, 128))
        d_diff.text((75, 35), "DIFFERENT CO", fill=(0, 0, 0))
        diff.save(diff_path)

    return {
        "ref": ref_path,
        "resized": resized_path,
        "altered": altered_path,
        "different": diff_path,
    }


def test_exact_logo_match(logo_assets):
    """Exact identical logo must have Hamming distance == 0 and pass compliance."""
    ref_bytes = logo_assets["ref"].read_bytes()
    has_viol, dist, msg = predicate_logo_hash(ref_bytes, ref_bytes, max_hamming_distance=10)

    assert not has_viol, f"Exact match flagged as violation: {msg}"
    assert dist == 0
    assert "matches approved reference" in msg.lower()


def test_resized_logo_match(logo_assets):
    """Resized logo (2x scale) must perceptually match (distance <= 10) and pass compliance."""
    resized_bytes = logo_assets["resized"].read_bytes()
    ref_bytes = logo_assets["ref"].read_bytes()

    has_viol, dist, msg = predicate_logo_hash(resized_bytes, ref_bytes, max_hamming_distance=10)

    assert not has_viol, f"Resized logo flagged as violation: {msg}"
    assert dist is not None
    assert dist <= 2
    assert "matches approved reference" in msg.lower()


def test_slightly_altered_logo_within_threshold(logo_assets):
    """Slightly altered logo (minor pixel change) must remain within threshold (distance <= 10)."""
    altered_bytes = logo_assets["altered"].read_bytes()
    ref_bytes = logo_assets["ref"].read_bytes()

    has_viol, dist, msg = predicate_logo_hash(altered_bytes, ref_bytes, max_hamming_distance=10)

    assert not has_viol, f"Slightly altered logo flagged as violation: {msg}"
    assert dist is not None
    assert dist <= 10
    assert "matches approved reference" in msg.lower()


def test_completely_different_logo_triggers_violation(logo_assets):
    """Completely different logo must produce Hamming distance > 10 and trigger violation."""
    diff_bytes = logo_assets["different"].read_bytes()
    ref_bytes = logo_assets["ref"].read_bytes()

    has_viol, dist, msg = predicate_logo_hash(diff_bytes, ref_bytes, max_hamming_distance=10)

    assert has_viol, "Completely different logo was not detected as violation"
    assert dist is not None
    assert dist > 10
    assert "exceeds threshold" in msg.lower()


def test_missing_reference_logo_graceful_boundary(logo_assets):
    """When a product has no registered reference logo, the check is skipped as a coverage boundary."""
    cand_bytes = logo_assets["ref"].read_bytes()

    # Case 1: reference_logo is None
    has_viol, dist, msg = predicate_logo_hash(cand_bytes, None, max_hamming_distance=10)
    assert not has_viol
    assert dist is None
    assert "coverage boundary" in msg.lower() or "skipped" in msg.lower()

    # Case 2: reference_logo is empty bytes
    has_viol, dist, msg = predicate_logo_hash(cand_bytes, b"", max_hamming_distance=10)
    assert not has_viol
    assert dist is None


def test_l01_rule_engine_integration(logo_assets):
    """Verify RuleEngine evaluates L-01 in run_rules when candidate and reference logo are in context."""
    engine = RuleEngine()
    ref_bytes = logo_assets["ref"].read_bytes()
    diff_bytes = logo_assets["different"].read_bytes()

    doc = ExtractedDoc(text="Monsoon Clear Skin Campaign Banner", pages=["Monsoon Clear Skin Campaign Banner"])

    # 1. Negative case: approved reference logo -> 0 findings
    context_clean = {
        "asset_id": "AST-BANNER-01",
        "candidate_logo": ref_bytes,
        "reference_logo": ref_bytes,
    }
    findings_clean = engine.run_rules(doc, [], context_clean)
    l01_findings = [f for f in findings_clean if f.rule_id == "L-01"]
    assert len(l01_findings) == 0

    # 2. Positive case: spoofed/unapproved logo -> triggers L-01 block
    context_viol = {
        "asset_id": "AST-BANNER-02",
        "candidate_logo": diff_bytes,
        "reference_logo": ref_bytes,
    }
    findings_viol = engine.run_rules(doc, [], context_viol)
    l01_findings = [f for f in findings_viol if f.rule_id == "L-01"]
    assert len(l01_findings) == 1
    assert l01_findings[0].severity.value == "block"
    assert "exceeds threshold" in l01_findings[0].message.lower()
