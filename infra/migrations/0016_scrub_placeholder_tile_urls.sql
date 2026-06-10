UPDATE map_layers
SET
    metadata = metadata - 'tiles',
    status = CASE
        WHEN status = 'available' THEN 'degraded'
        ELSE status
    END,
    updated_at = now()
WHERE
    metadata ? 'tiles'
    AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(metadata -> 'tiles') AS tile(url)
        WHERE
            lower(tile.url) LIKE '%tiles.placeholder.flood-risk.local%'
            OR lower(tile.url) LIKE '%tiles.example.test%'
    );
