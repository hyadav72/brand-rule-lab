# Brand Rule Lab — Engineering Assumptions Log

This document records explicit assumptions made during the implementation of Brand Rule Lab to resolve any ambiguities in the build plan without guessing silently.

---

### Assumption 1: Product Identification & Scope Binding
- **Context:** An uploaded draft may not explicitly contain the internal product ID (e.g. `prod_monsoon`).
- **Resolution:** The Creator upload form requires explicit selection of `product_id`, `market`, and `channel`. The claim extraction prompt also searches for known `sku_aliases` as secondary hints. If conflicting, the user's explicitly selected context takes precedence.

### Assumption 2: Date Formats and Expiry Handling
- **Context:** Facts and planned publishing dates require comparison against calendar dates.
- **Resolution:** All dates are standardized as ISO 8601 strings (`YYYY-MM-DD`). A `NULL` `expires_at` value indicates perpetual validity. The current date is injected via parameter `today` (defaulting to system UTC date) to allow deterministic testing of future or past dates.

### Assumption 3: Graceful Degradation for Optical Character Recognition (OCR)
- **Context:** Tesseract OCR requires an external binary (`tesseract.exe`) which may not be present on all development or judging machines.
- **Resolution:** Ingestion checks if `tesseract` is available via `pytesseract`. If absent, image upload returns a clear, friendly UI state (`"OCR engine is not installed on this host. Please test with TXT, DOCX, or PDF drafts."`) rather than raising an unhandled exception. Ingestion tests mock the OCR reader to maintain 100% test coverage.

### Assumption 4: Stable Claim ID Generation and Collisions
- **Context:** The build plan specifies generating `stable_claim_id` as `SC-` plus the first 4 hex characters of SHA-256 over `asset_id, normalised claim text and fact_version_id`, extended on collision.
- **Resolution:** The hash input is formatted as `f"{asset_id}:{normalised_text}:{fact_version_id}".encode("utf-8")`. If `SC-{hex[:4]}` already exists in `approved_claims`, the length is extended to 6 hex characters, then 8, guaranteeing uniqueness.

### Assumption 5: Text Normalization for Text Hashing
- **Context:** Approved claims store an `approved_text_hash` over normalized text.
- **Resolution:** Normalization applies Unicode NFC form, strips leading/trailing whitespace, and collapses consecutive whitespace characters (including newlines and tabs) into a single ASCII space ` ` before SHA-256 computation.

### Assumption 6: Role Authentication Scope
- **Context:** MVP testing requires demonstrating Creator, Reviewer, and Fact Owner workflows without an external identity provider.
- **Resolution:** System implements a clean role picker stored in `st.session_state["active_role"]`. Enforced permissions prevent unauthorized actions (e.g., Creator cannot approve; Reviewer cannot create fact versions; Fact Owner cannot approve assets) at both the UI and data layer.
