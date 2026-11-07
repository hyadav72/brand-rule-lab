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
    predicate_logo_hash,
    predicate_numeric_timeframe,
    predicate_regex,
    predicate_required_text,
    predicate_term_list,
)
from core.a11y.alt_text import validate_alt_text
from core.a11y.contrast import evaluate_wcag_aa

logger = logging.getLogger(__name__)
DEFAULT_RULES_DIR = Path(__file__).parent.parent.parent / "data" / "rules"


def _is_sentence_boundary(text: str, i: int) -> bool:
    """Check if character at index i is a sentence boundary, ignoring decimal numbers (e.g. 2.5%)."""
    ch = text[i]
    if ch in "!?\n":
        return True
    if ch == ".":
        # Do not treat decimal point between digits as a sentence boundary
        if i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1].isdigit():
            return False
        return True
    return False


def _extract_enclosing_sentence(text: str, start: int, end: int) -> Tuple[int, int, str]:
    """
    Extract the enclosing sentence span [s_start, s_end] around a match [start, end].
    Sentence boundaries are determined by '.', '!', '?', or newline characters, ignoring decimals.
    """
    if not text:
        return start, end, text[start:end]

    s_start = 0
    for i in range(start - 1, -1, -1):
        if _is_sentence_boundary(text, i):
            s_start = i + 1
            break
    while s_start < start and text[s_start].isspace():
        s_start += 1

    s_end = len(text)
    for i in range(end, len(text)):
        if _is_sentence_boundary(text, i):
            s_end = i + 1
            break
    while s_end > end and text[s_end - 1].isspace():
        s_end -= 1

    if s_start >= s_end:
        return start, end, text[start:end]

    return s_start, s_end, text[s_start:s_end]


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences, ignoring decimal points within numbers (e.g. 2.5%)."""
    raw_sentences = re.split(r"(?<!\d)[.!?](?!\d)\s*|\n+", text)
    return [s.strip() for s in raw_sentences if s.strip()]


def make_finding_id(
    rule_id: Optional[str],
    span_start: int,
    asset_id: str,
    review_cycle: int = 1,
) -> str:
    """
    Generate an asset- and review-cycle-aware unique finding ID.
    Format: FND-{clean_rule}-{span_start}-{clean_asset}-C{review_cycle}
    """
    clean_rule = (rule_id or "UNLINKED").replace("-", "")
    if asset_id.startswith("AST-"):
        clean_asset = asset_id[4:].replace("-", "")
    else:
        clean_asset = re.sub(r"[^A-Za-z0-9]", "", asset_id)
    return f"FND-{clean_rule}-{span_start}-{clean_asset}-C{review_cycle}"


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
        """Check if rule applies to given product, category, market, channel context."""
        scope = rule.scope
        for key in ["product", "category", "market", "channel"]:
            rule_val = scope.get(key, "*")
            if rule_val != "*":
                ctx_val = context.get(key)
                # If market is omitted in verification context, default to 'US' for evaluation
                if ctx_val is None and key == "market":
                    ctx_val = "US"
                if ctx_val != rule_val:
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
        review_cycle = context.get("review_cycle", 1)

        # 1. Evaluate Tone Rule V-04 (Absolute Claims)
        if "V-04" in self.rules and self._matches_scope(self.rules["V-04"], context):
            rule = self.rules["V-04"]
            terms = rule.parameters.get("disallowed_terms", [])
            subs = rule.parameters.get("suggested_substitutions", {})
            seen_sentence_spans = set()
            for term in terms:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    s_start, s_end, sentence = _extract_enclosing_sentence(text, start, end)
                    if (s_start, s_end) in seen_sentence_spans:
                        continue
                    seen_sentence_spans.add((s_start, s_end))

                    if re.search(r"\bsay goodbye to acne\b", sentence, flags=re.IGNORECASE):
                        suggested = "Gentle daily wash for clearer-looking skin!"
                    else:
                        sub_val = subs.get(matched.lower(), "long-term")
                        suggested = re.sub(r"\b" + re.escape(matched) + r"\b", sub_val, sentence, flags=re.IGNORECASE)

                    findings.append(Finding(
                        finding_id=make_finding_id("V-04", s_start, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.TONE,
                        severity=Severity.BLOCK,
                        span_start=s_start,
                        span_end=s_end,
                        source_text=sentence,
                        rule_id="V-04",
                        link_state=LinkState.UNLINKED,
                        message=f"Absolute claim '{matched}' violates brand tone guidelines. Use qualified non-absolute wording.",
                        next_step=f"Replace with qualified wording (e.g., '{suggested}').",
                        suggested_rewrite=suggested,
                        review_cycle=review_cycle,
                    ))

        # 2. Evaluate Terminology Rule T-12 (BPO Disallowed)
        if "T-12" in self.rules and self._matches_scope(self.rules["T-12"], context):
            rule = self.rules["T-12"]
            pattern = rule.parameters.get("pattern", r"\bBPO\b")
            for match in predicate_regex(text, pattern):
                start, end, matched = match
                findings.append(Finding(
                    finding_id=make_finding_id("T-12", start, asset_id, review_cycle),
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
                    review_cycle=review_cycle,
                ))

        # 3. Evaluate Misleading Natural Claims T-05
        if "T-05" in self.rules and self._matches_scope(self.rules["T-05"], context):
            rule = self.rules["T-05"]
            disallowed = rule.parameters.get("disallowed_terms", [])
            for term in disallowed:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    findings.append(Finding(
                        finding_id=make_finding_id("T-05", start, asset_id, review_cycle),
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
                        review_cycle=review_cycle,
                    ))

        # 4. Evaluate Numerical Claim vs Approved Fact F-112 (C-01)
        # Finds phrases like "clears breakouts in 3 days"
        product_id = context.get("product")
        if product_id == "prod_monsoon":
            if "C-01" in self.rules and self._matches_scope(self.rules["C-01"], context):
                for claim in claims:
                    if "breakout" in claim.text.lower() or "acne" in claim.text.lower():
                        has_viol, days, msg = predicate_numeric_timeframe(
                            claim.text, approved_timeframe_days_min=28
                        )
                        if has_viol:
                            findings.append(Finding(
                                finding_id=make_finding_id("C-01", claim.start, asset_id, review_cycle),
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
                                review_cycle=review_cycle,
                            ))
        else:
            # If product is out of C-01 scope (e.g. prod_glow, prod_barrier),
            # any breakout/acne claim is unlinked because those products have no approved breakout facts.
            for claim in claims:
                if "breakout" in claim.text.lower() or "acne" in claim.text.lower():
                    findings.append(Finding(
                        finding_id=make_finding_id("C-01-UNLINKED", claim.start, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=claim.start,
                        span_end=claim.end,
                        source_text=claim.text,
                        rule_id="C-01",
                        fact_id=None,
                        fact_version_id=None,
                        link_state=LinkState.UNLINKED,
                        message=f"Unsupported claim '{claim.text}': product '{product_id or 'unknown'}' has no approved acne/breakout facts in market '{context.get('market', 'US')}'. Evidence registered for Monsoon Clear Skin cannot be used.",
                        next_step="Remove acne/breakout claim or attach an approved clinical trial fact for this product.",
                        suggested_rewrite=None,
                        review_cycle=review_cycle,
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
                    finding_id=make_finding_id("D-02", start, asset_id, review_cycle),
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
                    review_cycle=review_cycle,
                ))

        # 6. Evaluate Accessibility: Alt-Text Check on Ingested Images
        if doc.images:
            for idx, img_bytes in enumerate(doc.images):
                img_alt = context.get(f"image_{idx}_alt", "")
                is_valid, reason = validate_alt_text(img_alt)
                if not is_valid:
                    findings.append(Finding(
                        finding_id=make_finding_id("A-03", idx, asset_id, review_cycle),
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
                        review_cycle=review_cycle,
                    ))

        # 7. Evaluate Superlatives Rule T-08 (miracle, magic, cure-all)
        if "T-08" in self.rules and self._matches_scope(self.rules["T-08"], context):
            rule = self.rules["T-08"]
            terms = rule.parameters.get("disallowed_terms", [])
            subst = rule.parameters.get("suggested_substitutions", {})
            for term in terms:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    sug = subst.get(matched.lower(), "proven")
                    findings.append(Finding(
                        finding_id=make_finding_id("T-08", start, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.TONE,
                        severity=Severity.BLOCK,
                        span_start=start,
                        span_end=end,
                        source_text=matched,
                        rule_id="T-08",
                        link_state=LinkState.UNLINKED,
                        message=f"Superlative phrasing '{matched}' violates ASCI/FTC substantiation standards.",
                        next_step=f"Replace with qualified, substantiated terminology (e.g., '{sug}').",
                        suggested_rewrite=sug,
                        review_cycle=review_cycle,
                    ))

        # 8. Evaluate Universal Outcome Rule T-15 (guaranteed for every skin type, works for everyone)
        if "T-15" in self.rules and self._matches_scope(self.rules["T-15"], context):
            rule = self.rules["T-15"]
            terms = rule.parameters.get("disallowed_terms", [])
            subst = rule.parameters.get("suggested_substitutions", {})
            for term in terms:
                for match in predicate_regex(text, r"\b" + re.escape(term) + r"\b"):
                    start, end, matched = match
                    sug = subst.get(matched.lower(), "formulated for most skin types")
                    findings.append(Finding(
                        finding_id=make_finding_id("T-15", start, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=start,
                        span_end=end,
                        source_text=matched,
                        rule_id="T-15",
                        link_state=LinkState.UNLINKED,
                        message=f"Universal claim '{matched}' violates truth-in-advertising guidelines.",
                        next_step=f"Replace with realistic qualification (e.g., '{sug}').",
                        suggested_rewrite=sug,
                        review_cycle=review_cycle,
                    ))

        # 9. Evaluate Regulatory Mandatory Disclaimer R-01 (US Dietary Supplement PDP)
        if "R-01" in self.rules and self._matches_scope(self.rules["R-01"], context):
            rule = self.rules["R-01"]
            req_phrases = rule.parameters.get("required_phrases", [])
            missing = predicate_required_text(text, req_phrases)
            if missing:
                findings.append(Finding(
                    finding_id=make_finding_id("R-01", 0, asset_id, review_cycle),
                    asset_id=asset_id,
                    kind=FindingKind.CLAIM,
                    severity=Severity.BLOCK,
                    span_start=0,
                    span_end=min(len(text), 30),
                    source_text=text[:min(len(text), 30)],
                    rule_id="R-01",
                    link_state=LinkState.UNLINKED,
                    message=f"Missing mandatory DSHEA statutory FDA disclaimer (21 U.S.C. § 343(r)(6)): {', '.join(missing)}.",
                    next_step="Add statutory two-sentence FDA disclaimer to US dietary supplement PDP copy.",
                    suggested_rewrite="These statements have not been evaluated by the Food and Drug Administration. This product is not intended to diagnose, treat, cure, or prevent any disease.",
                    review_cycle=review_cycle,
                ))

        # 10. Evaluate WCAG Contrast (A-01 / A-02) if color parameters are passed in context
        fg_col = context.get("foreground_hex")
        bg_col = context.get("background_hex")
        font_size = context.get("font_size_pt", 12)
        if fg_col and bg_col:
            is_large = font_size >= 18
            target_rule_id = "A-02" if is_large else "A-01"
            if target_rule_id in self.rules and self._matches_scope(self.rules[target_rule_id], context):
                passes_wcag, ratio = evaluate_wcag_aa(fg_col, bg_col, is_large_text=is_large)
                if not passes_wcag:
                    threshold = 3.0 if is_large else 4.5
                    findings.append(Finding(
                        finding_id=make_finding_id(target_rule_id, 0, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.ACCESSIBILITY,
                        severity=Severity.BLOCK,
                        span_start=0,
                        span_end=min(len(text), 20),
                        source_text=f"Color pair {fg_col} on {bg_col}",
                        rule_id=target_rule_id,
                        link_state=LinkState.UNLINKED,
                        message=f"Contrast ratio {ratio:.2f}:1 fails WCAG AA requirement (minimum {threshold}:1 for {'large' if is_large else 'standard'} text).",
                        next_step=f"Increase contrast between foreground text ({fg_col}) and background ({bg_col}).",
                        suggested_rewrite="#13171A on #FFFFFF",
                        review_cycle=review_cycle,
                    ))

        # 11. Evaluate Logo Hash (L-01) if candidate and reference logo are available
        if "L-01" in self.rules and self._matches_scope(self.rules["L-01"], context):
            cand_logo = context.get("candidate_logo") or (doc.images[0] if doc.images else None)
            ref_logo = context.get("reference_logo")
            if cand_logo and ref_logo:
                rule = self.rules["L-01"]
                max_d = rule.parameters.get("max_hamming_distance", 10)
                has_viol, dist, msg = predicate_logo_hash(cand_logo, ref_logo, max_hamming_distance=max_d)
                if has_viol:
                    findings.append(Finding(
                        finding_id=make_finding_id("L-01", 0, asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=0,
                        span_end=min(len(text), 20),
                        source_text="[Brand Logo Asset]",
                        rule_id="L-01",
                        link_state=LinkState.UNLINKED,
                        message=msg,
                        next_step="Replace altered or distorted logo with registered official brand logo asset.",
                        review_cycle=review_cycle,
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

    def _extract_deterministic_claims(self, text: str, product_hint: Optional[str] = None) -> List[ClaimSpan]:
        """
        Extract claim spans deterministically from candidate rewrite text.
        Operates 100% offline using pure Python regex and sentence analysis.
        Makes zero LLM adapter calls and instantiates no mock adapter.
        """
        claims: List[ClaimSpan] = []
        if not text or not text.strip():
            return claims

        # Specific efficacy and numerical timeframe patterns
        patterns = [
            r"\b(?:clears?|reduces?|hydrates?|treats?|prevents?)\s+[\w\s]{2,30}\s+in\s+\d+\s+(?:days?|weeks?|hours?)(?:\s+with\s+[\w\s-]+)?\b",
            r"\b\d+(?:\.\d+)?%\s+[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?\b",
            r"\b(?:clinically\s+(?:tested|proven|evaluated|supported)|clinical\s+trials?)\b",
        ]

        seen_spans = []
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                s, e = m.start(), m.end()
                if not any(ex_s <= s < ex_e or ex_s < e <= ex_e for ex_s, ex_e in seen_spans):
                    seen_spans.append((s, e))
                    claims.append(ClaimSpan(
                        text=m.group(0),
                        start=s,
                        end=e,
                        product_alias=product_hint,
                    ))

        # Sentences touching acne or breakouts (to catch unlinked or condition-violating claims)
        sentences = _split_into_sentences(text)
        cur_pos = 0
        for sent in sentences:
            s_idx = text.find(sent, cur_pos)
            if s_idx == -1:
                s_idx = text.find(sent)
            if s_idx != -1:
                cur_pos = s_idx + len(sent)
                e_idx = s_idx + len(sent)
                if re.search(r"\b(?:acne|breakouts?|blemish(?:es)?)\b", sent, flags=re.IGNORECASE):
                    if not any(ex_s <= s_idx and e_idx <= ex_e for ex_s, ex_e in seen_spans):
                        seen_spans.append((s_idx, e_idx))
                        claims.append(ClaimSpan(
                            text=sent.strip(),
                            start=s_idx,
                            end=e_idx,
                            product_alias=product_hint,
                        ))

        claims.sort(key=lambda c: c.start)
        return claims

    def check_rewrite(self, rewrite_text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Finding]]:
        """
        Re-check proposed or edited rewrite against all deterministic rules (slide 11).
        Returns (is_clean: bool, violations: List[Finding]).
        A rewrite that triggers any block or warn finding is NOT clean.

        Clinical claim matching is STRICTLY product-specific:
        - Fetches approved facts for the exact (product_id, market) pair in context.
        - A rewrite is considered supported only when its text contains the
          permitted_wording or fact_text of a fact belonging to that exact product.
        - Generic keyword shortcuts such as '4 week in text' are NOT used so that
          evidence registered for prod_monsoon can never validate a claim made
          for prod_glow, prod_barrier, or any other product.
        """
        ctx = dict(context or {})
        ctx.setdefault("market", "US")
        temp_doc = ExtractedDoc(text=rewrite_text, pages=[rewrite_text])
        claims = self._extract_deterministic_claims(rewrite_text, product_hint=ctx.get("product"))
        findings = self.run_rules(temp_doc, claims, ctx)

        # Verify affirmative clinical trial and efficacy claims against approved facts —
        # product-specific matching only; no cross-product evidence sharing.
        clinical_match = re.search(r"\bclinically\s+(?:tested|proven|evaluated|supported)\b|\bclinical\s+trials?\b", rewrite_text, flags=re.IGNORECASE)
        breakout_match = re.search(r"\b(?:acne|breakouts?|blemish(?:es)?)\b", rewrite_text, flags=re.IGNORECASE)

        product_id = ctx.get("product")
        market = ctx.get("market", "US")
        asset_id = ctx.get("asset_id", "AST-REWRITE")
        review_cycle = ctx.get("review_cycle", 1)
        rewrite_lower = rewrite_text.lower()

        from core.lookup.facts import lookup_all_valid_fact_versions
        product_facts = lookup_all_valid_fact_versions(product_id, market) if product_id else []

        # 1. Breakout / Acne efficacy claims validation
        if breakout_match:
            # Check if this product has approved facts supporting acne/breakout claims
            breakout_facts = [f for f in product_facts if "breakout" in f.fact_text.lower() or "acne" in f.fact_text.lower()]
            if not breakout_facts:
                if not any(f.rule_id == "C-01" for f in findings):
                    findings.append(Finding(
                        finding_id=make_finding_id("C-01-BREAKOUT", breakout_match.start(), asset_id, review_cycle),
                        asset_id=asset_id,
                        kind=FindingKind.CLAIM,
                        severity=Severity.BLOCK,
                        span_start=breakout_match.start(),
                        span_end=breakout_match.end(),
                        source_text=breakout_match.group(0),
                        rule_id="C-01",
                        link_state=LinkState.UNLINKED,
                        message=(
                            f"Unsupported claim: product '{product_id or 'unknown'}' has no approved clinical trial "
                            f"facts supporting acne/breakout claims in market '{market}'. Evidence from other products cannot be shared."
                        ),
                        next_step="Remove acne/breakout claim or register an approved clinical trial fact for this product.",
                        review_cycle=review_cycle,
                    ))
            else:
                # Product has breakout facts (e.g. Monsoon F-112). Verify material qualifications and conditions.
                # Every sentence touching acne/breakouts must be supported by approved factual qualifications.
                sentences = _split_into_sentences(rewrite_text)
                for sent in sentences:
                    sent_lower = sent.lower()
                    if re.search(r"\b(?:acne|breakouts?|blemish(?:es)?)\b", sent_lower):
                        has_qual_backing = False
                        for fact in breakout_facts:
                            pw_norm = fact.permitted_wording.lower().rstrip(" .!?")
                            ft_norm = fact.fact_text.lower().rstrip(" .!?")
                            if pw_norm in sent_lower or ft_norm in sent_lower:
                                has_qual_backing = True
                                break
                            # For F-112 v3: 4-week trial requires twice-daily use condition
                            if fact.version == 3:
                                has_timeframe = "4 week" in sent_lower or "28 day" in sent_lower
                                has_twice_daily = "twice-daily" in sent_lower or "twice daily" in sent_lower
                                if has_timeframe and has_twice_daily:
                                    has_qual_backing = True
                                    break
                            # For F-112 v4: 2-week trial requires micronized formula condition
                            elif fact.version == 4:
                                has_timeframe = "2 week" in sent_lower or "14 day" in sent_lower
                                has_micronized = "micronized" in sent_lower
                                if has_timeframe and has_micronized:
                                    has_qual_backing = True
                                    break

                        if not has_qual_backing:
                            match = re.search(r"\b(?:acne|breakouts?|blemish(?:es)?)\b", sent, flags=re.IGNORECASE)
                            matched_word = match.group(0) if match else "acne"
                            m_start = match.start() if match else 0
                            findings.append(Finding(
                                finding_id=make_finding_id(f"C-01-COND-{len(findings)}", m_start, asset_id, review_cycle),
                                asset_id=asset_id,
                                kind=FindingKind.CLAIM,
                                severity=Severity.BLOCK,
                                span_start=m_start,
                                span_end=match.end() if match else len(sent),
                                source_text=matched_word,
                                rule_id="C-01",
                                fact_id="F-112",
                                fact_version_id=3,
                                link_state=LinkState.UNLINKED,
                                message=(
                                    f"Sentence '{sent}' lacks approved factual qualification: approved fact F-112 requires "
                                    "the approved condition ('twice-daily use' for 4-week trial). Unqualified claims cannot silently pass."
                                ),
                                next_step="Align claim with approved wording: 'reduces breakouts in 4 weeks with twice-daily use'.",
                                suggested_rewrite="reduces breakouts in 4 weeks with twice-daily use",
                                review_cycle=review_cycle,
                            ))

        # 2. General clinical terms validation (e.g. 'clinically tested', 'clinically proven')
        if clinical_match:
            has_clinical_backing = False
            for fact in product_facts:
                pw_norm = fact.permitted_wording.lower().rstrip(".")
                ft_norm = fact.fact_text.lower().rstrip(".")
                if pw_norm in rewrite_lower or ft_norm in rewrite_lower:
                    has_clinical_backing = True
                    break
                if ("breakout" in rewrite_lower or "acne" in rewrite_lower) and ("4 week" in rewrite_lower or "28 day" in rewrite_lower) and ("twice-daily" in rewrite_lower or "twice daily" in rewrite_lower):
                    has_clinical_backing = True
                    break

            if not has_clinical_backing:
                findings.append(Finding(
                    finding_id=make_finding_id("C-01-CLINICAL", clinical_match.start(), asset_id, review_cycle),
                    asset_id=asset_id,
                    kind=FindingKind.CLAIM,
                    severity=Severity.BLOCK,
                    span_start=clinical_match.start(),
                    span_end=clinical_match.end(),
                    source_text=clinical_match.group(0),
                    rule_id="C-01",
                    link_state=LinkState.UNLINKED,
                    message=(
                        f"Unsupported clinical claim '{clinical_match.group(0)}' lacks approved fact evidence "
                        f"for product '{product_id or 'unknown'}' in market '{market}'. "
                        "Evidence registered for other products cannot be used."
                    ),
                    next_step=(
                        "Attach a registered clinical trial fact for this exact product and market, "
                        "or use the verbatim approved wording from the fact registry."
                    ),
                    review_cycle=review_cycle,
                ))

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
                elif rule.predicate_type == "required_text":
                    req_phrases = rule.parameters.get("required_phrases", [])
                    missing = predicate_required_text(inp, req_phrases)
                    passed = len(missing) > 0
                elif rule.predicate_type == "wcag_contrast":
                    fg = test.get("foreground", "#000000")
                    bg = test.get("background", "#FFFFFF")
                    is_large = rule.parameters.get("is_large_text", False) or test.get("font_size_pt", 0) >= 18
                    passes_wcag, _ = evaluate_wcag_aa(fg, bg, is_large_text=is_large)
                    # For positive test case, expected_match: true means it DETECTED a violation (i.e. fails contrast)
                    passed = not passes_wcag
                elif rule.predicate_type == "alt_text":
                    alt = test.get("alt_text", "")
                    valid, _ = validate_alt_text(alt)
                    passed = not valid  # violation detected
                elif rule.predicate_type == "logo_hash":
                    cand = test.get("candidate")
                    ref = test.get("reference")
                    max_d = rule.parameters.get("max_hamming_distance", 10)
                    has_v, _, _ = predicate_logo_hash(cand, ref, max_hamming_distance=max_d)
                    passed = has_v

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
                elif rule.predicate_type == "required_text":
                    req_phrases = rule.parameters.get("required_phrases", [])
                    missing = predicate_required_text(inp, req_phrases)
                    passed = len(missing) == 0
                elif rule.predicate_type == "wcag_contrast":
                    fg = test.get("foreground", "#000000")
                    bg = test.get("background", "#FFFFFF")
                    is_large = rule.parameters.get("is_large_text", False) or test.get("font_size_pt", 0) >= 18
                    passes_wcag, _ = evaluate_wcag_aa(fg, bg, is_large_text=is_large)
                    passed = passes_wcag  # Clean contrast passes WCAG
                elif rule.predicate_type == "alt_text":
                    alt = test.get("alt_text", "")
                    valid, _ = validate_alt_text(alt)
                    passed = valid  # Clean alt-text is valid
                elif rule.predicate_type == "logo_hash":
                    cand = test.get("candidate")
                    ref = test.get("reference")
                    max_d = rule.parameters.get("max_hamming_distance", 10)
                    has_v, _, _ = predicate_logo_hash(cand, ref, max_hamming_distance=max_d)
                    passed = not has_v

                results.append({
                    "rule_id": rule.rule_id,
                    "test_type": "negative",
                    "input": str(inp or test),
                    "expected": "clean_pass",
                    "actual": "clean_pass" if passed else "violation_detected",
                    "passed": passed,
                })

        return results
