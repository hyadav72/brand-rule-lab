-- Brand Rule Lab: SQLite Relational Schema
-- Enforces foreign keys and CHECK constraints for all enum columns.

PRAGMA foreign_keys = ON;

-- Registered Products
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sku_aliases TEXT NOT NULL, -- JSON array of string aliases
    market TEXT NOT NULL
);

-- Approved Fact Versions (Compound Primary Key: fact_id, version)
CREATE TABLE IF NOT EXISTS fact_versions (
    fact_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    market TEXT NOT NULL,
    fact_text TEXT NOT NULL,
    permitted_wording TEXT NOT NULL,
    valid_from TEXT NOT NULL,    -- YYYY-MM-DD
    expires_at TEXT,            -- YYYY-MM-DD (NULL if indefinite)
    owner TEXT NOT NULL DEFAULT 'brand_science',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fact_id, version),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
);

-- Ingested Marketing Assets
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    product_id TEXT NOT NULL,
    market TEXT NOT NULL,
    channel TEXT NOT NULL CHECK(channel IN ('paid_social', 'organic_social', 'email', 'pdp', 'banner')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'ready_for_review', 'changes_requested', 'escalated', 'approved')),
    created_by TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    text_content TEXT NOT NULL,
    planned_publish_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- Compliance Findings Emitted by Deterministic Rules
CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('tone', 'terminology', 'claim', 'offer_date', 'visual_text', 'accessibility')),
    severity TEXT NOT NULL CHECK(severity IN ('block', 'warn', 'info')),
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    rule_id TEXT,
    fact_id TEXT,
    fact_version_id INTEGER,
    link_state TEXT NOT NULL CHECK(link_state IN ('LINKED', 'UNLINKED')),
    message TEXT NOT NULL,
    next_step TEXT NOT NULL,
    suggested_rewrite TEXT,
    creator_action TEXT NOT NULL DEFAULT 'pending' CHECK(creator_action IN ('pending', 'accepted', 'edited', 'dismissed')),
    dismiss_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
);

-- Immutable Claim Ledger (Approved Claims Linked to Specific Fact Versions)
CREATE TABLE IF NOT EXISTS approved_claims (
    stable_claim_id TEXT PRIMARY KEY, -- e.g. SC-7f3a
    asset_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    approved_text_hash TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    fact_version_id INTEGER NOT NULL,
    drift_status TEXT NOT NULL DEFAULT 'CURRENT' CHECK(drift_status IN ('CURRENT', 'REVIEW_REQUIRED', 'EXPIRED')),
    approved_by TEXT NOT NULL,
    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    flagged_at TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY (fact_id, fact_version_id) REFERENCES fact_versions(fact_id, version)
);

-- Append-Only Audit Trail (No UPDATE or DELETE allowed by convention and triggers)
CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('creator', 'reviewer', 'fact_owner')),
    action TEXT NOT NULL,
    comment TEXT,
    override_reason TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

-- Registered Rules Specification Table
CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY,
    predicate_type TEXT NOT NULL,
    scope TEXT NOT NULL,             -- JSON object specifying product/market/channel restrictions
    parameters_json TEXT NOT NULL,   -- JSON parameters for predicate
    owner_approved INTEGER NOT NULL CHECK(owner_approved IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1
);

-- Seeded Users (Role Picker in UI)
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('creator', 'reviewer', 'fact_owner'))
);

-- Prevent Updates and Deletes on Append-Only Audit Table
CREATE TRIGGER IF NOT EXISTS trg_prevent_review_events_update
BEFORE UPDATE ON review_events
BEGIN
    SELECT RAISE(ABORT, 'Mutation forbidden: review_events table is append-only.');
END;

CREATE TRIGGER IF NOT EXISTS trg_prevent_review_events_delete
BEFORE DELETE ON review_events
BEGIN
    SELECT RAISE(ABORT, 'Deletion forbidden: review_events table is append-only.');
END;
