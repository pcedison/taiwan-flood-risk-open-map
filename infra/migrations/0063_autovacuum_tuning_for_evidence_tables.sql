-- The retention pass added in #367/#370 deletes up to 50 000 rejected
-- staging_evidence rows every five minutes, but deleted rows only become dead
-- tuples: their heap space and index entries stay allocated until autovacuum
-- clears them. PostgreSQL's default autovacuum_vacuum_scale_factor of 0.2 waits
-- for 20% of the table to die first, which on the hosted node (staging_evidence
-- 14.35M live rows / 21.5 GB, evidence 2.25M rows / 8.5 GB on 2026-09-06) means
-- roughly 2.9M dead rows before a single vacuum runs. Observed last_autovacuum
-- was 9/4 for staging_evidence and the morning of 9/6 for evidence, so the
-- retention pass reclaims nothing for days while the dead tuples keep occupying
-- the page cache of a 2 GB node.
--
-- Per-table storage parameters lower those thresholds to match each table's
-- churn:
--
--   staging_evidence  2% of 14.35M rows  ~= 287k dead tuples per vacuum cycle
--                     (about six retention cycles' worth of deletes)
--   evidence          5% of 2.25M rows   ~= 113k dead tuples per vacuum cycle
--                     (evidence churns far more slowly than staging)
--
-- The cost parameters pace the extra vacuum work. autovacuum_vacuum_cost_delay
-- is pinned at 2 ms per table -- the PostgreSQL 12+ default, written down here
-- so a hosting-provider change to the global setting cannot silently throttle
-- these two tables. staging_evidence additionally raises
-- autovacuum_vacuum_cost_limit from the default 200 to 1000, giving its vacuum
-- five times the IO budget per cycle so it can keep pace with up to 600k
-- deleted rows per hour. evidence keeps the default cost limit: it churns far
-- less and is read-hot, so a slower, cheaper vacuum is the right trade.
--
-- Idempotent, pure DDL, and instant: ALTER TABLE ... SET (storage parameters)
-- only rewrites the pg_class row and re-running it writes the same values.

BEGIN;

ALTER TABLE staging_evidence SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 1000
);

ALTER TABLE evidence SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_vacuum_cost_delay = 2
);

COMMIT;
