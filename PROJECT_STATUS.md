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
| **Day 0** | **D0-08** | Seed rule JSON specifications (`data/rules/`) | P0 | A2 | ✅ Complete | V-04, T-12, C-01, D-02, T-05, A-01, A-03 |
| **Day 0** | **D0-09** | 60-claim labeled evaluation dataset (`eval/claims_60.csv`) | P1 | A5 | ✅ Complete | 60 labeled claims across products and states |
| **Day 0** | **D0-10** | 30 adversarial prompt injection test cases (`eval/injection_30.jsonl`) | P1 | A5 | ✅ Complete | 30 injection vectors |
| **Day 0** | **D0-11** | Engineering assumptions & ADR logs (ADR 001–007) | P0 | A0 | ✅ Complete | `docs/assumptions.md`, `docs/architecture_decisions.md` |
| **Day 0** | **D0-12** | Python 3.15 Compatibility Investigation | P0 | A0 | ❌ Rejected | Failed on `pandas`/`streamlit` (lack of wheels) |
| **Day 1** | **D1-01** | Python 3.11 environment setup & package installation | P0 | Team | ✅ Complete | Verified: `tests/test_environment_smoke.py` (6/6 pytest passed) |
| **Day 1** | **D1-02** | Database initialization & seed import (`db.py`, `seed.py`) | P0 | A1 | ⏳ Ready | Hours 0–4 |
| **Day 1** | **D1-03** | Multi-format ingestion pipeline (`ingest/`) | P1 | A1 | ⏳ Ready | Hours 2–6 |
| **Day 1** | **D1-04** | LLM Adapter core (`llm/adapter.py`, `mock.py`, `live.py`) | P0 | A3 | ⏳ Ready | Hours 2–8 |
| **Day 1** | **D1-05** | Rule engine & pure Python predicates (`rules/engine.py`) | P0 | A2 | ⏳ Ready | Hours 4–10 |
| **Day 1** | **D1-06** | Streamlit shell, theme, and role switcher (`app/`) | P0 | A4 | ⏳ Ready | Hours 6–12 |
| **Day 1** | **D1-07** | Claim extraction, fact ranking & rewrite re-check | P0 | A3 | ⏳ Ready | Hours 8–16 |
| **Day 1** | **D1-08** | Creator & Reviewer UI workflows | P0 | A4 | ⏳ Ready | Hours 12–20 |
| **Day 1** | **D1-09** | Automated tests for Day 1 modules (predicates, ingestion) | P0 | A5 | ⏳ Ready | Hours 16–24 |
| **Day 2** | **D2-01** | Stable claim ID generation (`SC-xxxx`) and approved text hashing | P0 | A1 | ⏳ Ready | Hours 24–28 |
| **Day 2** | **D2-02** | Single-SQL fact drift cascade and expiry sweeps (`ledger/`) | P0 | A1 | ⏳ Ready | Hours 26–30 |
| **Day 2** | **D2-03** | Fact Owner dashboard with drift statistics & impact preview | P0 | A4 | ⏳ Ready | Hours 28–34 |
| **Day 2** | **D2-04** | Rule Tests Runner page for hackathon judges | P1 | A4/A2 | ⏳ Ready | Hours 32–36 |
| **Day 2** | **D2-05** | 60-claim matching evaluation execution & benchmark | P1 | A5 | ⏳ Ready | Hours 34–38 |
| **Day 2** | **D2-06** | 30-prompt adversarial injection verification | P1 | A5 | ⏳ Ready | Hours 36–40 |
| **Day 2** | **D2-07** | 10-asset review turnaround timing study | P1 | A5 | ⏳ Ready | Hours 38–42 |
| **Day 2** | **D2-08** | Offline demo verification, backup DB & final README | P0 | A0/A5 | ⏳ Ready | Hours 42–46 |
| **Day 2** | **D2-09** | Fresh-clone install verification & release freeze | P0 | A0 | ⏳ Ready | Hours 46–48 |

---

## 3. Known Bugs & Issues
- None (zero application runtime code committed per Day 0 boundary).

---

## 4. Current Blockers & Technical Risks
1. **Python 3.11 Environment (RESOLVED)**:
   - Fresh virtual environment `.venv` active with Python 3.11.9.
   - All pinned binary wheels (Streamlit, PyMuPDF, Pillow, python-docx, pytest) installed and verified with zero compilation errors.
2. **48-Hour Deadline Compression**:
   - Compressed timeframe requires absolute discipline: P0 features must take precedence over cosmetic UI flourishes.
   - Mock LLM mode guarantees that the entire demo scenario (*Monsoon Clear Skin*) runs instantaneously without risk of live API quota or network failures.

---

## 5. Next Recommended Action
Awaiting user confirmation that official hackathon window is open to begin parallel execution of **Day 1: Tasks D1-02 (Database/Seeds), D1-03 (Ingestion), and D1-04 (Mock LLM Adapter)**.
