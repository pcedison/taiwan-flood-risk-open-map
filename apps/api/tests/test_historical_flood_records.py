from urllib.parse import urlparse

from app.domain.history.flood_records import bundled_historical_flood_records


def test_bundled_news_history_records_keep_verifiable_source_urls() -> None:
    records = [
        record
        for record in bundled_historical_flood_records()
        if record.source_type == "news"
    ]

    assert records
    for record in records:
        parsed = urlparse(record.url)
        assert parsed.scheme in {"http", "https"}
        assert parsed.netloc
