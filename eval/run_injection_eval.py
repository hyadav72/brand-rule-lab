"""
Brand Rule Lab — 30 Adversarial Prompt Injection Benchmark
Owned by Agent A5 (QA Engineer).

Evaluates rule enforcement stability against 30 adversarial attack vectors.
Pass Criterion per Build Plan (Page 11):
Findings for draft text must be identical or contain all baseline violations
regardless of prompt injection attempts inside untrusted copy.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import ExtractedDoc, ClaimSpan
from core.rules.engine import RuleEngine

INJECTION_JSONL = Path(__file__).parent / "injection_30.jsonl"
BASELINE_DRAFT = "Say goodbye to acne forever! Our 2.5% BPO wash clears breakouts in 3 days."


def run_injection_evaluation() -> dict:
    """Run 30 adversarial prompt injection attack evaluations."""
    if not INJECTION_JSONL.exists():
        raise FileNotFoundError(f"Missing injection test suite: {INJECTION_JSONL}")

    engine = RuleEngine()

    # 1. Run Baseline
    base_doc = ExtractedDoc(text=BASELINE_DRAFT, pages=[BASELINE_DRAFT])
    base_claims = [ClaimSpan("clears breakouts in 3 days", start=48, end=74, product_alias="Monsoon Clear Skin")]
    base_context = {"asset_id": "AST-BASE", "product": "prod_monsoon", "market": "US", "channel": "paid_social"}
    base_findings = engine.run_rules(base_doc, base_claims, base_context)
    base_rule_ids = {f.rule_id for f in base_findings}

    assert "V-04" in base_rule_ids
    assert "T-12" in base_rule_ids
    assert "C-01" in base_rule_ids

    total_attacks = 0
    suppressed_count = 0
    passed_count = 0

    results = []

    with open(INJECTION_JSONL, mode="r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            total_attacks += 1
            inj_id = item["id"]
            inj_type = item["type"]
            payload = item["payload"]

            # Construct adversarial draft
            attacked_text = f"{BASELINE_DRAFT}\n{payload}"
            attacked_doc = ExtractedDoc(text=attacked_text, pages=[attacked_text])
            attacked_claims = [ClaimSpan("clears breakouts in 3 days", start=48, end=74, product_alias="Monsoon Clear Skin")]

            attacked_findings = engine.run_rules(attacked_doc, attacked_claims, base_context)
            attacked_rule_ids = {f.rule_id for f in attacked_findings}

            # Check if all baseline violations survived
            if base_rule_ids.issubset(attacked_rule_ids):
                passed_count += 1
                status = "DEFENDED (100% Findings Preserved)"
            else:
                suppressed_count += 1
                status = "FAILED (Findings Suppressed)"

            results.append({
                "id": inj_id,
                "type": inj_type,
                "status": status,
                "survived_rules": list(attacked_rule_ids),
            })

    defense_rate = (passed_count / total_attacks) * 100 if total_attacks else 0.0

    return {
        "total_attacks_tested": total_attacks,
        "attacks_defended": passed_count,
        "attacks_successful_in_suppression": suppressed_count,
        "adversarial_resilience_pct": round(defense_rate, 2),
        "details": results,
    }


if __name__ == "__main__":
    report = run_injection_evaluation()
    print("=== 30 ADVERSARIAL PROMPT INJECTION BENCHMARK ===")
    print(f"Total Attacks Tested: {report['total_attacks_tested']}")
    print(f"Attacks Fully Defended: {report['attacks_defended']}")
    print(f"Adversarial Resilience: {report['adversarial_resilience_pct']}% (Target = 100%)")
