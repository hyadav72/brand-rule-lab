-- Migration 002: Creator Audit Trail and Provenance Tracking
-- Adds structured provenance columns and performance indexes to review_events.

-- 1. Add creator decision tracking columns
ALTER TABLE review_events ADD COLUMN finding_id TEXT;
ALTER TABLE review_events ADD COLUMN previous_action TEXT;
ALTER TABLE review_events ADD COLUMN new_action TEXT;
ALTER TABLE review_events ADD COLUMN event_fingerprint TEXT;
ALTER TABLE review_events ADD COLUMN provenance TEXT NOT NULL DEFAULT 'USER_ACTION';
ALTER TABLE review_events ADD COLUMN known_before_timestamp TIMESTAMP;

-- 2. Deduplication and audit lookup indexes
CREATE INDEX IF NOT EXISTS idx_review_events_asset_fingerprint
ON review_events(asset_id, event_fingerprint);

CREATE INDEX IF NOT EXISTS idx_review_events_asset_timestamp
ON review_events(asset_id, timestamp);
