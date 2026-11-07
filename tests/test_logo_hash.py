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


def test_compressed_logo_jpeg_artifacts(logo_assets):
    """
    Logo subjected to lossy JPEG compression (quality=30) must remain perceptually recognizable
    (distance <= 10) and pass compliance.
    """
    ref_img = Image.open(logo_assets["ref"])
    buf = io.BytesIO()
    ref_img.save(buf, format="JPEG", quality=30)
    compressed_bytes = buf.getvalue()
    ref_bytes = logo_assets["ref"].read_bytes()

    has_viol, dist, msg = predicate_logo_hash(compressed_bytes, ref_bytes, max_hamming_distance=10)
    assert not has_viol, f"Compressed logo flagged as violation: {msg}"
    assert dist is not None
    assert dist <= 10, f"JPEG compression produced distance {dist} > 10"


def test_unrelated_full_creative_or_photo_fails(logo_assets):
    """
    An unrelated image or full creative photo passed as candidate logo fails perceptual match.
    Demonstrates architectural limitation: dHash expects pre-cropped/isolated logo assets,
    not full uncropped advertising creatives.
    """
    # Create an unrelated lifestyle photo scene (800x600 gradient with text)
    unrelated = Image.new("RGB", (800, 600), color=(200, 150, 100))
    d = ImageDraw.Draw(unrelated)
    d.rectangle([50, 50, 750, 550], fill=(50, 80, 120))
    d.text((100, 100), "Lifestyle photo scene with model", fill=(255, 255, 255))
    buf = io.BytesIO()
    unrelated.save(buf, format="PNG")
    unrelated_bytes = buf.getvalue()

    ref_bytes = logo_assets["ref"].read_bytes()
    has_viol, dist, msg = predicate_logo_hash(unrelated_bytes, ref_bytes, max_hamming_distance=10)

    assert has_viol, "Unrelated image should have failed logo match"
    assert dist is not None
    assert dist > 10, f"Unrelated image produced distance {dist} <= 10"


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
        "product": "prod_monsoon",
        "market": "US",
        "channel": "banner",
        "candidate_logo": ref_bytes,
        "reference_logo": ref_bytes,
    }
    findings_clean = engine.run_rules(doc, [], context_clean)
    l01_findings = [f for f in findings_clean if f.rule_id == "L-01"]
    assert len(l01_findings) == 0

    # 2. Positive case: spoofed/unapproved logo on Monsoon banner -> triggers L-01 block
    context_viol = {
        "asset_id": "AST-BANNER-02",
        "product": "prod_monsoon",
        "market": "US",
        "channel": "banner",
        "candidate_logo": diff_bytes,
        "reference_logo": ref_bytes,
    }
    findings_viol = engine.run_rules(doc, [], context_viol)
    l01_findings = [f for f in findings_viol if f.rule_id == "L-01"]
    assert len(l01_findings) == 1
    assert l01_findings[0].severity.value == "block"
    assert "exceeds threshold" in l01_findings[0].message.lower()

    # 3. Scope restriction cases: Out-of-scope assets must NOT be checked by L-01
    # 3a. prod_glow banner -> out-of-scope
    ctx_glow = dict(context_viol, product="prod_glow")
    assert len([f for f in engine.run_rules(doc, [], ctx_glow) if f.rule_id == "L-01"]) == 0

    # 3b. prod_barrier banner -> out-of-scope
    ctx_barrier = dict(context_viol, product="prod_barrier", market="UK")
    assert len([f for f in engine.run_rules(doc, [], ctx_barrier) if f.rule_id == "L-01"]) == 0

    # 3c. Monsoon paid_social (other channel) -> out-of-scope
    ctx_paid_social = dict(context_viol, channel="paid_social")
    assert len([f for f in engine.run_rules(doc, [], ctx_paid_social) if f.rule_id == "L-01"]) == 0


def test_l01_json_declarative_test_cases_semantics():
    """
    Verify L-01.json declarative test specifications and test runner:
    1. Positive test cases: expected_match == False (different logo fails perceptual threshold)
       and triggers a BLOCK finding.
    2. Negative test cases: expected_match == True (exact, resized, altered logos match within threshold)
       and produce 0 findings (clean pass).
    3. RuleEngine.run_rule_test_cases('L-01') passes 100%.
    """
    import json
    from core.models import Severity

    rule_path = Path(__file__).parent.parent / "data" / "rules" / "L-01.json"
    with open(rule_path, "r", encoding="utf-8") as f:
        rule_def = json.load(f)

    # 1. Verify positive test cases have expected_match == False
    for pt in rule_def["positive_test_cases"]:
        assert pt["expected_match"] is False, f"Positive test case {pt['description']} must have expected_match=False"
        cand = pt["candidate"]
        ref = pt["reference"]
        has_v, dist, msg = predicate_logo_hash(cand, ref, max_hamming_distance=10)
        assert has_v is True, f"Candidate {cand} should trigger violation"
        assert dist > 10

    # 2. Verify negative test cases have expected_match == True
    for nt in rule_def["negative_test_cases"]:
        assert nt["expected_match"] is True, f"Negative test case {nt['description']} must have expected_match=True"
        cand = nt["candidate"]
        ref = nt["reference"]
        has_v, dist, msg = predicate_logo_hash(cand, ref, max_hamming_distance=10)
        assert has_v is False, f"Candidate {cand} should NOT trigger violation: {msg}"
        assert dist <= 10

    # 3. Verify RuleEngine declarative test runner passes 100%
    engine = RuleEngine()
    results = engine.run_rule_test_cases("L-01")
    assert len(results) == 4
    for r in results:
        assert r["passed"] is True, f"Test failed in engine: {r}"

