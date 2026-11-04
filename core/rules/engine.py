"""
Brand Rule Lab — Deterministic Rule Engine
Owned by Agent A2 (Rules & Accessibility Engineer).

Loads declarative JSON rule specs, enforces quality gates, and evaluates rules.
Non-Negotiable Rule 1 & 2:
- LLMs NEVER produce pass/fail verdicts.
- Engine refuses to load rules without test cases or without owner approval.
- Every finding cites a rule_id or fact_id + version.
"""

from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from core.models import (
    ClaimSpan,
    CreatorActionState,
    ExtractedDoc,
    Finding,
    FindingKind,
    LinkState,
    RuleSpec,
    Severity,
)
from core.rules.predicates import (
    predicate_date_window,
    predicate_numeric_timeframe,
    predicate_regex,
    predicate_required_text,
    predicate_term_list,
)
from core.a11y.alt_text import validate_alt_text
from core.a11y.contrast import evaluate_wcag_aa

logger = logging.getLogger(__name__)
DEFAULT_RULES_DIR = Path(__file__).parent.parent.parent / "data" / "rules"


class RuleEngine:
    """Deterministic rule evaluation engine."""

    def __init__(self, rules_dir: Optional[Path] = None):
        self.rules_dir = rules_dir or DEFAULT_RULES_DIR
        self.rules: Dict[str, RuleSpec] = {}
        self.load_rules()

    def load_rules(self) -> int:
        """
        Load and validate declarative rule specs from data/rules/*.json.
        Refuses to load any rule without test cases or without owner approval.
        """
        self.rules.clear()
        if not self.rules_dir.exists():
            return 0

        loaded_count = 0
        for rule_file in self.rules_dir.glob("*.json"):
            try:
                data = json.loads(rule_file.read_text(encoding="utf-8"))
                rule_id = data.get("rule_id")

                # Quality Gate 1: owner_approved must be True
                if not data.get("owner_approved", False):
                    logger.warning(f"Refusing rule {rule_id}: not owner_approved.")
                    continue

                # Quality Gate 2: must possess positive and negative test cases
                pos_tests = data.get("positive_test_cases", [])
                neg_tests = data.get("negative_test_cases", [])
                if not pos_tests or not neg_tests:
                    logger.warning(f"Refusing rule {rule_id}: missing positive/negative test cases.")
                    continue

                spec = RuleSpec(
                    rule_id=rule_id,
                    predicate_type=data["predicate_type"],
                    scope=data.get("scope", {}),
                    parameters=data.get("parameters", {}),
                    positive_test_cases=pos_tests,
                    negative_test_cases=neg_tests,
                    owner_approved=True,
                    version=data.get("version", 1),
                )
                self.rules[rule_id] = spec
                loaded_count += 1
            except Exception as e:
                logger.error(f"Error parsing rule file {rule_file}: {e}")

        return loaded_count

    def _matches_scope(self, rule: RuleSpec, context: Dict[str, Any]) -> bool:
        """Check if rule applies to given product, market, channel context."""
        scope = rule.scope
        for key in ["product", "market", "channel"]:
            rule_val = scope.get(key, "*")
            ctx_val = context.get(key)
            if rule_val != "*" and ctx_val and rule_val != ctx_val:
                return False
        return True

    def run_rules(
        self,
        doc: ExtractedDoc,
        claims: List[ClaimSpan],
        context: Dict[str, Any],
    ) -> List[Finding]:
        """
        Execute deterministic Python rules on document text and claim spans.
        Returns deterministic list of findings ordered by start span.
        """
        findings: List[Finding] = []
        text = doc.text
        asset_id = context.get("asset_id", "AST-DRAFT")

        # 1. Evaluate Tone Rule V-04 (Absolute Claims)
        if "V-04" in self.rules and self._matches_scope(self.rules["V-04"], context):
            rule = self.rules["V-04"]
            terms = rule.parameters.get("disallowed_terms", [])
            for term in terms:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    findings.append(Finding(
                        finding_id=f"FND-V04-{start}",
                        asset_id=asset_id,
                        kind=FindingKind.TONE,
                        severity=Severity.BLOCK,
                        span_start=start,
                        span_end=end,
                        source_text=matched,
                        rule_id="V-04",
                        link_state=LinkState.UNLINKED,
                        message=f"Absolute claim '{matched}' violates brand tone guidelines. Use qualified or clinical language.",
                        next_step="Replace with qualified wording (e.g., 'clinically tested' or 'long-term').",
                        suggested_rewrite="clinically tested",
                    ))

        # 2. Evaluate Terminology Rule T-12 (BPO Disallowed)
        if "T-12" in self.rules and self._matches_scope(self.rules["T-12"], context):
            rule = self.rules["T-12"]
            pattern = rule.parameters.get("pattern", r"\bBPO\b")
            for match in predicate_regex(text, pattern):
                start, end, matched = match
                findings.append(Finding(
                    finding_id=f"FND-T12-{start}",
                    asset_id=asset_id,
                    kind=FindingKind.TERMINOLOGY,
                    severity=Severity.BLOCK,
                    span_start=start,
                    span_end=end,
                    source_text=matched,
                    rule_id="T-12",
                    link_state=LinkState.UNLINKED,
                    message="Abbreviation 'BPO' is prohibited in consumer copy under FDA/ASCI labeling guidelines.",
                    next_step="Expand to full approved chemical name 'Benzoyl Peroxide'.",
                    suggested_rewrite="Benzoyl Peroxide",
                ))

        # 3. Evaluate Misleading Natural Claims T-05
        if "T-05" in self.rules and self._matches_scope(self.rules["T-05"], context):
            rule = self.rules["T-05"]
            disallowed = rule.parameters.get("disallowed_terms", [])
            for term in disallowed:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    findings.append(Finding(
                        finding_id=f"FND-T05-{start}",
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=start,
                        span_end=end,
                        source_text=matched,
                        rule_id="T-05",
                        link_state=LinkState.UNLINKED,
                        message=f"Misleading claim '{matched}' violates truth-in-advertising guidelines.",
                        next_step="Remove absolute chemical-free/natural claims or link to certified organic fact.",
                        suggested_rewrite="formulated with gentle ingredients",
                    ))

        # 4. Evaluate Numerical Claim vs Approved Fact F-112 (C-01)
        # Finds phrases like "clears breakouts in 3 days"
        for claim in claims:
            if "breakout" in claim.text.lower() or "acne" in claim.text.lower():
                has_viol, days, msg = predicate_numeric_timeframe(
                    claim.text, approved_timeframe_days_min=28
                )
                if has_viol:
                    findings.append(Finding(
                        finding_id=f"FND-C01-{claim.start}",
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=claim.start,
                        span_end=claim.end,
                        source_text=claim.text,
                        rule_id="C-01",
                        fact_id="F-112",
                        fact_version_id=3,
                        link_state=LinkState.LINKED,
                        message=f"Claim mismatch: {msg} Approved fact F-112 v3 supports a 4-week clinical trial statement.",
                        next_step="Align claim with approved wording: 'reduces breakouts in 4 weeks with twice-daily use'.",
                        suggested_rewrite="reduces breakouts in 4 weeks with twice-daily use",
                    ))

        # 5. Evaluate Offer Date Window D-02
        if "D-02" in self.rules and self._matches_scope(self.rules["D-02"], context):
            rule = self.rules["D-02"]
            approved_end = rule.parameters.get("approved_end_date", "2026-11-12")
            planned_pub = context.get("planned_publish_date")
            has_viol, msg = predicate_date_window(text, approved_end, planned_pub)
            if has_viol:
                # Highlight date mention or full sentence
                date_match = re.search(r"(?:Sale\s+ends|until|through)\s+[\w\s\d]+", text, flags=re.IGNORECASE)
                start = date_match.start() if date_match else 0
                end = date_match.end() if date_match else min(30, len(text))
                matched_span = text[start:end]

                findings.append(Finding(
                    finding_id=f"FND-D02-{start}",
                    asset_id=asset_id,
                    kind=FindingKind.OFFER_DATE,
                    severity=Severity.BLOCK,
                    span_start=start,
                    span_end=end,
                    source_text=matched_span,
                    rule_id="D-02",
                    fact_id="F-OFFER-02",
                    fact_version_id=1,
                    link_state=LinkState.LINKED,
                    message=msg,
                    next_step=f"Adjust promotional offer date to end on or before approved deadline {approved_end}.",
                    suggested_rewrite=f"Flash sale ends {approved_end}",
                ))

        # 6. Evaluate Accessibility: Alt-Text Check on Ingested Images
        if doc.images:
            for idx, img_bytes in enumerate(doc.images):
                img_alt = context.get(f"image_{idx}_alt", "")
                is_valid, reason = validate_alt_text(img_alt)
                if not is_valid:
                    findings.append(Finding(
                        finding_id=f"FND-A03-{idx}",
                        asset_id=asset_id,
                        kind=FindingKind.ACCESSIBILITY,
                        severity=Severity.WARN,
                        span_start=0,
                        span_end=min(len(text), 20),
                        source_text=f"[Image #{idx + 1}]",
                        rule_id="A-03",
                        link_state=LinkState.UNLINKED,
                        message=reason,
                        next_step="Add descriptive alt-text describing the image contents for screen readers.",
                        suggested_rewrite="Product bottle on neutral studio background",
                    ))

        # Deduplicate and sort deterministically by span_start
        seen_keys = set()
        unique_findings = []
        for f in findings:
            key = (f.rule_id, f.span_start, f.span_end)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_findings.append(f)

        unique_findings.sort(key=lambda x: (x.span_start, x.finding_id))
        return unique_findings

    def check_rewrite(self, rewrite_text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Finding]]:
        """
        Re-check proposed or edited rewrite against all deterministic rules (slide 11).
        Returns (is_clean: bool, violations: List[Finding]).
        A rewrite that triggers any block or warn finding is NOT clean.
        """
        ctx = context or {}
        temp_doc = ExtractedDoc(text=rewrite_text, pages=[rewrite_text])
        from core.extract.claims import extract_claims
        claims = extract_claims(rewrite_text, product_hint=ctx.get("product"))
        findings = self.run_rules(temp_doc, claims, ctx)
        blocking_findings = [f for f in findings if f.severity in (Severity.BLOCK, Severity.WARN)]
        return len(blocking_findings) == 0, blocking_findings

    def run_rule_test_cases(self, rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Execute test cases for loaded rules and return verification summary.
        Used by pytest and the hackathon judge Rule Tests page.
        """
        results = []
        target_rules = [self.rules[rule_id]] if rule_id and rule_id in self.rules else self.rules.values()

        for rule in target_rules:
            # Run Positive Tests
            for test in rule.positive_test_cases:
                inp = test.get("input", "")
                passed = False
                if rule.predicate_type == "term_list":
                    terms = rule.parameters.get("disallowed_terms", [])
                    matches = predicate_term_list(inp, terms)
                    passed = len(matches) > 0
                elif rule.predicate_type == "regex":
                    pat = rule.parameters.get("pattern", "")
                    matches = predicate_regex(inp, pat)
                    passed = len(matches) > 0
                elif rule.predicate_type == "numeric_range":
                    has_v, _, _ = predicate_numeric_timeframe(inp)
                    passed = has_v
                elif rule.predicate_type == "date_window":
                    app_end = rule.parameters.get("approved_end_date", "2026-11-12")
                    pub = test.get("publish_date")
                    has_v, _ = predicate_date_window(inp, app_end, pub)
                    passed = has_v
                elif rule.predicate_type == "wcag_contrast":
                    fg = test.get("foreground", "#000000")
                    bg = test.get("background", "#FFFFFF")
                    passes_wcag, _ = evaluate_wcag_aa(fg, bg)
                    # For positive test case, expected_match: true means it DETECTED a violation (i.e. fails contrast)
                    passed = not passes_wcag
                elif rule.predicate_type == "alt_text":
                    alt = test.get("alt_text", "")
                    valid, _ = validate_alt_text(alt)
                    passed = not valid  # violation detected

                results.append({
                    "rule_id": rule.rule_id,
                    "test_type": "positive",
                    "input": str(inp or test),
                    "expected": "violation_detected",
                    "actual": "violation_detected" if passed else "no_violation",
                    "passed": passed,
                })

            # Run Negative Tests
            for test in rule.negative_test_cases:
                inp = test.get("input", "")
                passed = False
                if rule.predicate_type == "term_list":
                    terms = rule.parameters.get("disallowed_terms", [])
                    matches = predicate_term_list(inp, terms)
                    passed = len(matches) == 0
                elif rule.predicate_type == "regex":
                    pat = rule.parameters.get("pattern", "")
                    matches = predicate_regex(inp, pat)
                    passed = len(matches) == 0
                elif rule.predicate_type == "numeric_range":
                    has_v, _, _ = predicate_numeric_timeframe(inp)
                    passed = not has_v
                elif rule.predicate_type == "date_window":
                    app_end = rule.parameters.get("approved_end_date", "2026-11-12")
                    pub = test.get("publish_date")
                    has_v, _ = predicate_date_window(inp, app_end, pub)
                    passed = not has_v
                elif rule.predicate_type == "wcag_contrast":
                    fg = test.get("foreground", "#000000")
                    bg = test.get("background", "#FFFFFF")
                    passes_wcag, _ = evaluate_wcag_aa(fg, bg)
                    passed = passes_wcag  # Clean contrast passes WCAG
                elif rule.predicate_type == "alt_text":
                    alt = test.get("alt_text", "")
                    valid, _ = validate_alt_text(alt)
                    passed = valid  # Clean alt-text is valid

                results.append({
                    "rule_id": rule.rule_id,
                    "test_type": "negative",
                    "input": str(inp or test),
                    "expected": "clean_pass",
                    "actual": "clean_pass" if passed else "violation_detected",
                    "passed": passed,
                })

        return results
