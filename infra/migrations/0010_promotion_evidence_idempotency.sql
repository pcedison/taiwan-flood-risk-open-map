DO $$
DECLARE
    duplicate_group_count integer;
BEGIN
    SELECT count(*)
    INTO duplicate_group_count
    FROM (
        SELECT source_id, raw_ref
        FROM evidence
        GROUP BY source_id, raw_ref
        HAVING count(*) > 1
    ) duplicate_evidence_groups;

    IF duplicate_group_count > 0 THEN
        RAISE EXCEPTION
            'cannot add evidence_source_raw_ref_unique: found % duplicate evidence source_id/raw_ref group(s); reconcile duplicates before applying migration 0010',
            duplicate_group_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'evidence'::regclass
            AND conname = 'evidence_source_raw_ref_unique'
    ) THEN
        ALTER TABLE evidence
            ADD CONSTRAINT evidence_source_raw_ref_unique
            UNIQUE NULLS NOT DISTINCT (source_id, raw_ref);
    END IF;
END $$;
