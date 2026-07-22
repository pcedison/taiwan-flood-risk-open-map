ALTER TABLE staging_evidence
    DROP CONSTRAINT IF EXISTS staging_evidence_event_type_check;

ALTER TABLE staging_evidence
    ADD CONSTRAINT staging_evidence_event_type_check CHECK (
        event_type IN (
            'rainfall',
            'water_level',
            'flood_warning',
            'flood_potential',
            'flood_report',
            'status_only',
            'road_closure',
            'discussion'
        )
    );

ALTER TABLE evidence
    DROP CONSTRAINT IF EXISTS evidence_event_type_check;

ALTER TABLE evidence
    ADD CONSTRAINT evidence_event_type_check CHECK (
        event_type IN (
            'rainfall',
            'water_level',
            'flood_warning',
            'flood_potential',
            'flood_report',
            'status_only',
            'road_closure',
            'discussion'
        )
    );
