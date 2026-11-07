-- Migration 004: Repair Finding Identities, Provenance, and AST-ffed5f
-- Migrates legacy finding IDs to collision-safe format, reconstructs AST-ffed5f findings,
-- captures immutable effective submission snapshot, and records provenance audit events.

-- 1. Migrate AST-MONSOON-01 findings to asset-scoped cycle-aware IDs
UPDATE findings SET
    finding_id = 'FND-V04-20-MONSOON01-C1',
    review_cycle = 1
WHERE finding_id = 'FND-V04-20' AND asset_id = 'AST-MONSOON-01';

UPDATE findings SET
    finding_id = 'FND-T12-38-MONSOON01-C1',
    review_cycle = 1
WHERE finding_id = 'FND-T12-38' AND asset_id = 'AST-MONSOON-01';

UPDATE findings SET
    finding_id = 'FND-C01-47-MONSOON01-C1',
    review_cycle = 1
WHERE finding_id = 'FND-C01-47' AND asset_id = 'AST-MONSOON-01';

UPDATE findings SET
    finding_id = 'FND-V04-100-MONSOON01-C1',
    review_cycle = 1
WHERE finding_id = 'FND-V04-100' AND asset_id = 'AST-MONSOON-01';

UPDATE findings SET
    finding_id = 'FND-D02-0-MONSOON01-C1',
    review_cycle = 1
WHERE finding_id = 'FND-D02-0' AND asset_id = 'AST-MONSOON-01';

-- 2. Migrate existing finding on AST-ffed5f
UPDATE findings SET
    finding_id = 'FND-V04-0-ffed5f-C1',
    review_cycle = 1
WHERE finding_id = 'FND-V04-0' AND asset_id = 'AST-ffed5f';

-- 3. Restore missing findings for AST-ffed5f (guarded by asset existence)
INSERT INTO findings (
    finding_id, asset_id, kind, severity, span_start, span_end, source_text,
    rule_id, fact_id, fact_version_id, link_state, message, next_step,
    suggested_rewrite, creator_action, dismiss_reason, review_cycle
)
SELECT
    'FND-T12-38-ffed5f-C1',
    'AST-ffed5f',
    'terminology',
    'block',
    38,
    41,
    'BPO',
    'T-12',
    NULL,
    NULL,
    'UNLINKED',
    'Abbreviation ''BPO'' is prohibited in consumer copy under FDA/ASCI labeling guidelines.',
    'Expand to full approved chemical name ''Benzoyl Peroxide''.',
    'Benzoyl Peroxide',
    'accepted',
    NULL,
    1
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

INSERT INTO findings (
    finding_id, asset_id, kind, severity, span_start, span_end, source_text,
    rule_id, fact_id, fact_version_id, link_state, message, next_step,
    suggested_rewrite, creator_action, dismiss_reason, review_cycle
)
SELECT
    'FND-C01-47-ffed5f-C1',
    'AST-ffed5f',
    'claim',
    'block',
    47,
    73,
    'clears breakouts in 3 days',
    'C-01',
    'F-112',
    3,
    'LINKED',
    'Claim mismatch: turnaround of 3 days contradicts approved trial baseline (minimum 28 days). Approved fact F-112 v3 supports a 4-week clinical trial statement.',
    'Align claim with approved wording: ''reduces breakouts in 4 weeks with twice-daily use''.',
    'Reduces breakouts in 4 weeks with twice-daily use.',
    'edited',
    NULL,
    1
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

-- 4. Create topological submission parent for AST-ffed5f
-- Preserves original historical submission timestamp
INSERT INTO asset_submissions (
    submission_id, asset_id, review_cycle, submitted_by, submitted_at
)
SELECT
    'SUB-AST-ffed5f-C1',
    'AST-ffed5f',
    1,
    'Alex Chen (Creator)',
    '2026-11-05T18:49:29.564783'
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

-- 5. Create immutable effective snapshot for AST-ffed5f
-- captured_by identifies the reconstruction process; captured_at is the actual migration execution time
INSERT INTO asset_effective_snapshots (
    snapshot_id, submission_id, asset_id, review_cycle, effective_text, content_hash, captured_by, captured_at
)
SELECT
    'SNAP-EFF-REC-AST-ffed5f-C1',
    'SUB-AST-ffed5f-C1',
    'AST-ffed5f',
    1,
    'Gentle daily wash for clearer-looking skin! Our 2.5% Benzoyl Peroxide wash Reduces breakouts in 4 weeks with twice-daily use..',
    '1b7e597d753eb44a649adb5d18d971c25915a2eaad7b2fb8efe5688d81fe73bc',
    'MIGRATION_RECONSTRUCTION',
    CURRENT_TIMESTAMP
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

-- 6. Insert reconstructed audit events with explicit provenance
-- Actual execution timestamp is CURRENT_TIMESTAMP; historical boundary is known_before_timestamp
INSERT INTO review_events (
    event_id, asset_id, actor, role, action, comment, override_reason, timestamp,
    finding_id, previous_action, new_action, event_fingerprint, provenance, known_before_timestamp
)
SELECT
    'EVT-REC-ffed5f-V04',
    'AST-ffed5f',
    'Alex Chen (Creator)',
    'creator',
    'accept_rewrite',
    'Reconstructed creator decision: Accepted tone rewrite "Gentle daily wash for clearer-looking skin!"',
    NULL,
    CURRENT_TIMESTAMP,
    'FND-V04-0-ffed5f-C1',
    'pending',
    'accepted',
    'FPR-ffed5f-V04-ACCEPT',
    'MIGRATION_RECONSTRUCTION',
    '2026-11-05T18:49:29.564783'
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

INSERT INTO review_events (
    event_id, asset_id, actor, role, action, comment, override_reason, timestamp,
    finding_id, previous_action, new_action, event_fingerprint, provenance, known_before_timestamp
)
SELECT
    'EVT-REC-ffed5f-T12',
    'AST-ffed5f',
    'Alex Chen (Creator)',
    'creator',
    'accept_rewrite',
    'Reconstructed creator decision: Accepted terminology rewrite "Benzoyl Peroxide"',
    NULL,
    CURRENT_TIMESTAMP,
    'FND-T12-38-ffed5f-C1',
    'pending',
    'accepted',
    'FPR-ffed5f-T12-ACCEPT',
    'MIGRATION_RECONSTRUCTION',
    '2026-11-05T18:49:29.564783'
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');

INSERT INTO review_events (
    event_id, asset_id, actor, role, action, comment, override_reason, timestamp,
    finding_id, previous_action, new_action, event_fingerprint, provenance, known_before_timestamp
)
SELECT
    'EVT-REC-ffed5f-C01',
    'AST-ffed5f',
    'Alex Chen (Creator)',
    'creator',
    'edit_rewrite',
    'Reconstructed creator decision: Custom-edited clinical claim rewrite tied to F-112 v3',
    NULL,
    CURRENT_TIMESTAMP,
    'FND-C01-47-ffed5f-C1',
    'pending',
    'edited',
    'FPR-ffed5f-C01-EDIT',
    'MIGRATION_RECONSTRUCTION',
    '2026-11-05T18:49:29.564783'
WHERE EXISTS (SELECT 1 FROM assets WHERE asset_id = 'AST-ffed5f');
