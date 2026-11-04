# Brand Rule Lab — Project Status & Execution Dashboard

**Current Phase:** Phase 0 (Day 0 Preparation)  
**Hackathon Target:** INKLOOM AI Hackathon MVP  
**Last Updated:** 2026-11-04  
**Architect:** Agent A0 (Architect & Integrator)  

---

## 1. Executive Summary
Phase 0 foundation is established. The repository structure, Git version control, dependency pinning, Day 0 draft specifications, shared contracts (`core/models.py`), schema definitions (`core/schema.sql`), seed datasets, and evaluation test cases are authored. Application implementation code remains strictly gated until the official hackathon window opens (Day 1).

---

## 2. Task Tracking Matrix

| Phase / Day | Task ID | Description | Owner | Status | Verification / Artifact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Day 0** | **D0-01** | Git repository initialization | A0 | ✅ Complete | `.git/` initialized |
| **Day 0** | **D0-02** | Repository directory structure layout | A0 | ✅ Complete | `app/`, `core/`, `data/`, `eval/`, `docs/`, `tests/` |
| **Day 0** | **D0-03** | Pinned `requirements.txt` (Python 3.11 stack) | A0 | ✅ Complete | Streamlit, PyMuPDF, python-docx, Pillow, pytest |
| **Day 0** | **D0-04** | Configuration templates (`.env.example`, `.gitignore`) | A0 | ✅ Complete | Pinned configuration and git hygiene |
| **Day 0** | **D0-05** | Shared Contracts & Stubs (`core/models.py`) | A0 | ✅ Complete | Dataclasses, Enums, Stubs frozen |
| **Day 0** | **D0-06** | SQLite relational schema (`core/schema.sql`) | A0/A1 | ✅ Complete | Tables, triggers, CHECK constraints |
| **Day 0** | **D0-07** | Seed data specifications (`products.csv`, `facts.csv`) | A1 | ✅ Complete | 3 products, 12 facts (including F-112 v1-v4) |
| **Day 0** | **D0-08** | Seed rule JSON specifications (`data/rules/`) | A2 | ✅ Complete | V-04, T-12, C-01, D-02, T-05, A-01, A-03 |
| **Day 0** | **D0-09** | 60-claim labeled evaluation dataset (`eval/claims_60.csv`) | A5 | ✅ Complete | 60 labeled claims across products and states |
| **Day 0** | **D0-10** | 30 adversarial prompt injection test cases (`eval/injection_30.jsonl`) | A5 | ✅ Complete | 30 injection vectors |
| **Day 0** | **D0-11** | Engineering assumptions & ADR logs | A0 | ✅ Complete | `docs/assumptions.md`, `docs/architecture_decisions.md` |
| **Day 1** | **D1-01** | Environment readiness: Python 3.11 verification | Team | ⏳ Pending Blocker | Waiting on Python 3.11 environment setup |
| **Day 1** | **D1-02** | Database initialization & seed loader (`db.py`, `seed.py`) | A1 | ⏳ Ready | Day 1 window |
| **Day 1** | **D1-03** | Multi-format ingestion pipeline (`ingest/`) | A1 | ⏳ Ready | Day 1 window |
| **Day 1** | **D1-04** | LLM Adapter core (`llm/adapter.py`, `mock.py`, `live.py`) | A3 | ⏳ Ready | Day 1 window |
| **Day 1** | **D1-05** | Streamlit shell, theme, and role switcher | A4 | ⏳ Ready | Day 1 window |
| **Day 2** | **D2-01** | Rule engine and pure Python predicates (`rules/`) | A2 | ⏳ Ready | Day 2 window |
| **Day 2** | **D2-02** | Rule Test Runner page and automated test suite | A4/A5 | ⏳ Ready | Day 2 window |
| **Day 3** | **D3-01** | Claim extraction and fact ranking pipeline | A3 | ⏳ Ready | Day 3 window |
| **Day 3** | **D3-02** | Intent-preserving rewrite generator and re-checker | A3 | ⏳ Ready | Day 3 window |
| **Day 3** | **D3-03** | Creator and Reviewer dashboards | A4 | ⏳ Ready | Day 3 window |
| **Day 4** | **D4-01** | Claim ledger & stable claim ID generation (`ledger/`) | A1 | ⏳ Ready | Day 4 window |
| **Day 4** | **D4-02** | Single-SQL fact drift cascade and expiry sweeps | A1 | ⏳ Ready | Day 4 window |
| **Day 4** | **D4-03** | Fact Owner dashboard with drift statistics | A4 | ⏳ Ready | Day 4 window |
| **Day 5** | **D5-01** | 60-claim matching evaluation execution | A5 | ⏳ Ready | Day 5 window |
| **Day 5** | **D5-02** | 30-prompt adversarial injection verification | A5 | ⏳ Ready | Day 5 window |
| **Day 5** | **D5-03** | 10-asset review turnaround timing study | A5 | ⏳ Ready | Day 5 window |
| **Day 5** | **D5-04** | Final demo script verification & release freeze | A0 | ⏳ Ready | Day 5 window |

---

## 3. Known Bugs & Issues
- None (zero application runtime code committed per Day 0 restriction).

---

## 4. Current Blockers & Technical Risks
1. **Python 3.11 Interpreter Missing**:
   - The host system currently only provides `Python 3.15.0b1` (a pre-release beta version that lacks compiled wheels for `PyMuPDF` and `Pillow`).
   - Per project non-negotiables, the required runtime is **Python 3.11**.
   - **Resolution Required:** User must install Python 3.11 (instructions provided in Phase 0 report).

---

## 5. Next Recommended Action
Await user review and confirmation of Python 3.11 installation. Upon confirmation and opening of the Day 1 hackathon window, begin **Phase 1: Foundation (Database setup, Seed Import, File Ingestion, and Mock LLM Adapter)**.
