-- Migration 001: Finding Identity and Review Cycle Tracking
-- Adds review_cycle to assets and findings tables, and composite unique index.

-- 1. Add review_cycle to assets
ALTER TABLE assets ADD COLUMN review_cycle INTEGER NOT NULL DEFAULT 1;

-- 2. Add review_cycle to findings
ALTER TABLE findings ADD COLUMN review_cycle INTEGER NOT NULL DEFAULT 1;

-- 3. Composite unique index on findings ensuring uniqueness per asset, rule, span, and cycle
CREATE UNIQUE INDEX IF NOT EXISTS uq_findings_asset_rule_span_cycle
ON findings(asset_id, rule_id, span_start, span_end, review_cycle);
