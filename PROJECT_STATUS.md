# Brand Rule Lab — Project Status & Execution Dashboard

**Current Phase:** Phase 0 (Day 0 Preparation)  
**Hackathon Target:** INKLOOM AI Hackathon MVP (Compressed 48-Hour Deadline)  
**Last Updated:** 2026-11-05  
**Architect:** Agent A0 (Architect & Integrator)  

---

## 1. Executive Summary & Strategy
The project timeline is compressed from 5 days to **48 Hours (2 Days)**:
- **Day 1 (Hours 0–24): Core Implementation**: Core review workflow, database schema & seeds, rule engine with deterministic predicates, LLM adapter (mock & live), Creator/Reviewer/Fact Owner UI shells, and automated tests.
- **Day 2 (Hours 24–48): Integration, Drift Ledger & Submission**: Single-SQL fact drift cascade, claim lineage & stable IDs, 60-claim matching evaluation, 30-prompt injection tests, 10-asset timing study, offline backup, fresh-clone launch verification, and demo script.

### Priority Hierarchy
- **P0 (Absolute Must-Have):** Core review loop, deterministic rules, fact matching, human approval, claim ledger (`approved_claims`), single-SQL fact drift cascade, and offline mock LLM.
- **P1 (High Priority):** Document ingestion (PDF, DOCX, TXT), WCAG AA contrast check, role dashboards, and evaluation suites.
- **P2 (Polish):** Advanced UI animations, image OCR fine-tuning.

---

## 2. Task Tracking Matrix (48-Hour Schedule)

| Phase / Day | Task ID | Description | Priority | Owner | Status | Verification / Artifact |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Day 0** | **D0-01** | Git repository initialization | P0 | A0 | ✅ Complete | `.git/` initialized |
| **Day 0** | **D0-02** | Repository directory structure layout | P0 | A0 | ✅ Complete | `app/`, `core/`, `data/`, `eval/`, `docs/`, `tests/` |
| **Day 0** | **D0-03** | Pinned `requirements.txt` (Python 3.11 stack) | P0 | A0 | ✅ Complete | Streamlit, PyMuPDF, python-docx, Pillow, pytest |
| **Day 0** | **D0-04** | Configuration templates (`.env.example`, `.gitignore`) | P0 | A0 | ✅ Complete | Pinned configuration and git hygiene |
| **Day 0** | **D0-05** | Shared Contracts & Stubs (`core/models.py`) | P0 | A0 | ✅ Complete | Dataclasses, Enums, Stubs frozen |
| **Day 0** | **D0-06** | SQLite relational schema (`core/schema.sql`) | P0 | A0/A1 | ✅ Complete | Tables, triggers, CHECK constraints |
| **Day 0** | **D0-07** | Seed data specifications (`products.csv`, `facts.csv`) | P0 | A1 | ✅ Complete | 3 products, 12 facts (including F-112 v1-v4) |
| **Day 0** | **D0-08** | Seed rule JSON specifications (`data/rules/`) | P0 | A2 | ✅ Complete | 12/12 Rules: V-04, T-12, C-01, D-02, T-05, A-01, A-02, A-03, T-08, T-15, R-01, L-01 |
| **Day 0** | **D0-09** | 60-claim labeled evaluation dataset (`eval/claims_60.csv`) | P1 | A5 | ✅ Complete | 60 labeled claims across products and states |
| **Day 0** | **D0-10** | 30 adversarial prompt injection test cases (`eval/injection_30.jsonl`) | P1 | A5 | ✅ Complete | 30 injection vectors |
| **Day 0** | **D0-11** | Engineering assumptions & ADR logs (ADR 001–007) | P0 | A0 | ✅ Complete | `docs/assumptions.md`, `docs/architecture_decisions.md` |
| **Day 0** | **D0-12** | Python 3.15 Compatibility Investigation | P0 | A0 | ❌ Rejected | Failed on `pandas`/`streamlit` (lack of wheels) |
| **Day 1** | **D1-01** | Python 3.11 environment setup & package installation | P0 | Team | ✅ Complete | Verified: `tests/test_environment_smoke.py` (6/6 pytest passed) |
| **Day 1** | **D1-02** | Database initialization & seed import (`db.py`, `seed.py`) | P0 | A1 | ✅ Complete | Verified by `test_db_and_seed.py` |
| **Day 1** | **D1-03** | Multi-format ingestion pipeline (`ingest/`) | P1 | A1 | ✅ Complete | Verified by `test_ingest.py` (TXT, DOCX, PDF, OCR) |
| **Day 1** | **D1-04** | LLM Adapter core (`llm/adapter.py`, `mock.py`, `live.py`) | P0 | A3 | ✅ Complete | Verified by `test_llm_adapter.py` |
| **Day 1** | **D1-05** | Rule engine & pure Python predicates (`rules/engine.py`) | P0 | A2 | ✅ Complete | Verified by `test_rules_engine.py` (100% tests pass) |
| **Day 1** | **D1-06** | Streamlit shell, theme, and role switcher (`app/`) | P0 | A4 | ✅ Complete | `app/Home.py`, `theme.py`, `components.py` |
| **Day 1** | **D1-07** | Claim extraction, fact ranking & rewrite re-check | P0 | A3 | ✅ Complete | Verified by `check_rewrite()` in rule engine |
| **Day 1** | **D1-08** | Creator & Reviewer UI workflows | P0 | A4 | ✅ Complete | `1_Creator.py`, `2_Reviewer.py` with UNLINKED guard |
| **Day 1** | **D1-09** | Automated tests for Day 1 modules (predicates, ingestion) | P0 | A5 | ✅ Complete | 35 pytest unit and integration tests passing |
| **Day 2** | **D2-01** | Stable claim ID generation (`SC-xxxx`) and approved text hashing | P0 | A1 | ✅ Complete | `ledger/approve.py`, verified in `test_e2e_loop.py` |
| **Day 2** | **D2-02** | Single-SQL fact drift cascade and expiry sweeps (`ledger/`) | P0 | A1 | ✅ Complete | `ledger/drift.py` (0 LLM calls, 1 SQL UPDATE) |
| **Day 2** | **D2-03** | Fact Owner dashboard with drift statistics & impact preview | P0 | A4 | ✅ Complete | `3_Fact_Owner.py` |
| **Day 2** | **D2-04** | Rule Tests Runner page for hackathon judges | P1 | A4/A2 | ✅ Complete | `4_Rule_Tests.py` |
| **Day 2** | **D2-05** | 60-claim matching evaluation execution & benchmark | P1 | A5 | ✅ Complete | `eval/run_matching_eval.py` (97.56% Top-3 accuracy) |
| **Day 2** | **D2-06** | 30-prompt adversarial injection verification | P1 | A5 | ✅ Complete | `eval/run_injection_eval.py` (100% defended) |
| **Day 2** | **D2-07** | 10-asset review turnaround timing study | P1 | A5 | ✅ Complete | `eval/timing_study.md` (-86.3% median reduction) |
| **Day 2** | **D2-08** | Offline demo verification, backup DB & final README | P0 | A0/A5 | ✅ Complete | `README.md`, `Makefile`, `data/brand_rule_lab.db` |
| **Day 2** | **D2-09** | Fresh-clone install verification & release freeze | P0 | A0 | ✅ Complete | Full verification complete |

---

## 3. Known Bugs & Issues
- None. All 41 automated pytest tests and all 41 declarative rule unit tests pass cleanly in under 2 seconds.

---

## 4. Current Blockers & Technical Risks
- **Blockers:** None.
- **Rule Inventory:** 12/12 planned rules implemented with deterministic Python predicates, owner approval, and unit tests.
- **Demo Readiness:** 100% functional, both offline (via `MockLLM`) and with live API adapter. Single-SQL drift verified (0 LLM calls, 1 SQL UPDATE). Distinct UNLINKED vs NOT_OBSERVED boundaries established.

---

## 5. Next Recommended Action
The complete application, claim ledger, deterministic rule engine, Streamlit UI, evaluation suites, and documentation are fully functional and verified. Ready for demo walkthrough and final submission presentation.
