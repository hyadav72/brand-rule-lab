-- Migration 003: Submissions and Effective Snapshots
-- Creates asset_submissions as common topological parent and immutable asset_effective_snapshots.

-- 1. Table: asset_submissions
CREATE TABLE IF NOT EXISTS asset_submissions (
    submission_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    review_cycle INTEGER NOT NULL DEFAULT 1,
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    UNIQUE (asset_id, review_cycle)
);

-- Immutability triggers for asset_submissions
CREATE TRIGGER IF NOT EXISTS trg_prevent_submissions_update
BEFORE UPDATE ON asset_submissions
BEGIN
    SELECT RAISE(ABORT, 'Mutation forbidden: asset_submissions table is immutable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_prevent_submissions_delete
BEFORE DELETE ON asset_submissions
BEGIN
    SELECT RAISE(ABORT, 'Deletion forbidden: asset_submissions table is immutable.');
END;

-- 2. Table: asset_effective_snapshots
CREATE TABLE IF NOT EXISTS asset_effective_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE,
    asset_id TEXT NOT NULL,
    review_cycle INTEGER NOT NULL DEFAULT 1,
    effective_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    captured_by TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submission_id) REFERENCES asset_submissions(submission_id) ON DELETE RESTRICT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    UNIQUE (asset_id, review_cycle)
);

-- Immutability triggers for asset_effective_snapshots
CREATE TRIGGER IF NOT EXISTS trg_prevent_effective_snapshots_update
BEFORE UPDATE ON asset_effective_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Mutation forbidden: asset_effective_snapshots table is immutable.');
END;

CREATE TRIGGER IF NOT EXISTS trg_prevent_effective_snapshots_delete
BEFORE DELETE ON asset_effective_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Deletion forbidden: asset_effective_snapshots table is immutable.');
END;
