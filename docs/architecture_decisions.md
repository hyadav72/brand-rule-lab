# Architecture Decision Records (ADRs) — Brand Rule Lab

### ADR 001: Strict Separation of Generative AI and Deterministic Rule Verification
- **Status:** Accepted
- **Context:** Typical generative AI compliance tools delegate pass/fail verdicts to LLMs. This causes hallucinated compliance, non-reproducible checks, and vulnerability to adversarial prompt injection.
- **Decision:** The LLM is restricted to candidate extraction, semantic fact ranking, and rewrite generation. All pass/fail compliance decisions are executed exclusively by pure, deterministic Python predicates with zero LLM dependence.
- **Consequences:** 100% deterministic, reproducible, auditable compliance checks; zero risk of prompt injection suppressing a violation.

---

### ADR 002: Zero-LLM-Call, Single-SQL Fact Drift Propagation
- **Status:** Accepted
- **Context:** When brand facts or legal disclosures are updated, dependent approved marketing copy must be flagged. Running LLM passes over hundreds of approved assets is slow, expensive, and non-deterministic.
- **Decision:** Every approved claim is registered in `approved_claims` tied to `fact_id` and `fact_version_id`. Fact updates execute a single SQL query:
  ```sql
  UPDATE approved_claims
  SET drift_status = 'REVIEW_REQUIRED', flagged_at = CURRENT_TIMESTAMP
  WHERE fact_id = ? AND fact_version_id < ? AND drift_status = 'CURRENT';
  ```
- **Consequences:** Fact updates complete in sub-millisecond time with zero API cost, zero web crawls, and guaranteed 100% cascade accuracy.

---

### ADR 003: Append-Only Immutable Audit Log
- **Status:** Accepted
- **Context:** Compliance workflows require uncompromised legal traceability. If an audit log can be edited or deleted, enterprise governance fails.
- **Decision:** The `review_events` table contains SQLite triggers that raise exceptions on any `UPDATE` or `DELETE` operations. All actions (approvals, change requests, escalations, overrides, and dismissals) are append-only.
- **Consequences:** Complete tamper-evident audit history across all marketing assets.

---

### ADR 004: Explicit Distinction of Unmatched Claims (`UNLINKED` vs `NOT_OBSERVED`)
- **Status:** Accepted
- **Context:** Silent assumptions of compliance for unrecognized claims create catastrophic brand and legal liability.
- **Decision:** Claims without an approved matching fact are permanently designated as `UNLINKED`. Unlinked claims block approval unless a reviewer provides an explicit, logged override reason. Live marketing assets outside Brand Rule Lab's database are clearly designated as `NOT_OBSERVED` on all dashboards.
- **Consequences:** No false sense of security; clear visibility into compliance boundaries.

---

### ADR 005: Privacy and Data Sandboxing for LLM Context
- **Status:** Accepted
- **Context:** Uploaded brand assets may contain confidential roadmap details, unreleased pricing, or personally identifiable information.
- **Decision:** The LLM receives only isolated claim spans and candidate approved fact strings. The LLM never receives raw files, author identities, or entire unparsed documents.
- **Consequences:** Minimizes token usage, prevents confidential context leakage, and reduces attack surface.

---

### ADR 006: Dual LLM Adapter Pattern (Live vs Mock)
- **Status:** Accepted
- **Context:** Live network calls during hackathon judging presentations often fail due to Wi-Fi drops, API quotas, or third-party latency.
- **Decision:** Implement an abstract `LLMAdapter` base class with two concrete implementations: `LiveLLM` and `MockLLM`. `MockLLM` returns deterministic, canned responses for tests and offline demo presentation.
- **Consequences:** Guarantees instantaneous, 100% reliable offline demonstrations and enables fast, network-free automated testing.
