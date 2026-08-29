-- Keep CAP lifecycle/idempotency checks bounded as the general evidence table grows.
--
-- NCDR and CWA warning promotion deliberately inspect retained Alert/Update/Cancel
-- messages before publishing a current warning. Those checks filter a very small
-- warning subset through JSONB properties, while the shared evidence table also
-- contains high-volume rainfall, water-level, and sensor observations. Without
-- partial indexes PostgreSQL scans the unrelated observations and promotion can
-- exceed the worker's statement timeout even when only a handful of CAP messages
-- are being promoted.
--
-- These indexes contain only reviewed, current, actual official warning rows. They
-- change no source gate, warning lifecycle rule, evidence row, or public scoring
-- behavior.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_evidence_current_actual_cap_identity
    ON evidence (
        (properties ->> 'cap_sender'),
        (properties ->> 'cap_identifier'),
        (properties ->> 'admin_code')
    )
    WHERE source_type = 'official'
        AND event_type = 'flood_warning'
        AND properties ->> 'evidence_scope' = 'current'
        AND properties ->> 'cap_status' = 'Actual';

CREATE INDEX IF NOT EXISTS idx_evidence_current_actual_cap_message_type
    ON evidence ((properties ->> 'cap_message_type'))
    WHERE source_type = 'official'
        AND event_type = 'flood_warning'
        AND properties ->> 'evidence_scope' = 'current'
        AND properties ->> 'cap_status' = 'Actual';

COMMIT;
