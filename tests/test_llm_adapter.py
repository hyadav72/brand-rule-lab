"""
Brand Rule Lab — LLM Adapter Tests
Owned by Agent A5 (QA Engineer).
"""

from core.llm import MockLLM, get_llm_adapter
from core.llm.adapter import verify_and_align_offsets
from core.models import ClaimSpan, FactVersion, Finding, FindingKind, Severity, LinkState


def test_mock_adapter_demo_draft_extraction():
    """Verify MockLLM extracts exact target demo claims with offsets."""
    adapter = MockLLM()
    draft = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."
    claims = adapter.extract_claims(draft, product_hint="Monsoon Clear Skin")

    assert len(claims) == 3
    claim_texts = [c.text for c in claims]
    assert "acne forever" in claim_texts
    assert "2.5% BPO" in claim_texts
    assert "clears breakouts in 3 days" in claim_texts

    # Verify offsets correspond to exact substring in draft
    for c in claims:
        assert draft[c.start:c.end] == c.text


def test_mock_fact_ranking():
    """Verify MockLLM ranks the correct candidate fact for a claim."""
    adapter = MockLLM()
    f1 = FactVersion(
        fact_id="F-112",
        version=3,
        product_id="prod_monsoon",
        market="US",
        fact_text="Clinically proven to reduce acne breakouts in 4 weeks.",
        permitted_wording="Reduces breakouts in 4 weeks.",
        valid_from="2025-01-01",
    )
    f2 = FactVersion(
        fact_id="F-301",
        version=1,
        product_id="prod_barrier",
        market="UK",
        fact_text="Increases hydration by 48%.",
        permitted_wording="Hydrates by 48%.",
        valid_from="2025-01-01",
    )

    ranked = adapter.rank_facts("clears breakouts in 3 days", [f1, f2])
    assert len(ranked) == 2
    assert ranked[0].fact.fact_id == "F-112"
    assert ranked[0].score > ranked[1].score


def test_offset_verification_and_realignment():
    """Verify verify_and_align_offsets corrects drifted offsets and drops missing text."""
    source = "Leading 2.5% Benzoyl Peroxide wash for daily skin defense."

    valid_claim = ClaimSpan("Benzoyl Peroxide", start=13, end=29)
    drifted_claim = ClaimSpan("Benzoyl Peroxide", start=0, end=10)  # wrong offsets
    nonexistent_claim = ClaimSpan("Miracle Cure", start=0, end=12)

    result = verify_and_align_offsets(source, [valid_claim, drifted_claim, nonexistent_claim])

    assert len(result) == 2  # nonexistent dropped
    assert result[0].start == 13
    assert result[1].start == 13  # realigned to correct position
    assert source[result[1].start:result[1].end] == "Benzoyl Peroxide"


def test_suggest_rewrite():
    """Verify rewrite suggestion adheres to permitted wording."""
    adapter = MockLLM()
    finding = Finding(
        finding_id="FND-01",
        asset_id="AST-01",
        kind=FindingKind.TERMINOLOGY,
        severity=Severity.BLOCK,
        span_start=0,
        span_end=8,
        source_text="2.5% BPO",
    )
    fact = FactVersion(
        fact_id="F-113",
        version=1,
        product_id="prod_monsoon",
        market="US",
        fact_text="Contains 2.5% Benzoyl Peroxide.",
        permitted_wording="Contains 2.5% Benzoyl Peroxide.",
        valid_from="2025-01-01",
    )

    rewrite = adapter.suggest_rewrite(finding, fact)
    assert rewrite == "Contains 2.5% Benzoyl Peroxide."


def test_adapter_factory_returns_mock():
    """Verify default factory returns MockLLM."""
    adapter = get_llm_adapter("mock")
    assert isinstance(adapter, MockLLM)
