from urllib.error import HTTPError, URLError

import pytest

from app.adapters.civil_iot import sta_client
from app.jobs.ingestion import run_adapter_batch
from app.adapters.civil_iot.sta_water_level import SEWER_WATER_LEVEL, StaWaterLevelApiAdapter


URL = "https://user:secret@sta.colife.org.tw/STA_RainSewer/v1.0/Things?token=secret"


@pytest.mark.parametrize(
    ("error", "category", "attempts"),
    [
        (TimeoutError("secret"), "timeout", 2),
        (URLError(TimeoutError("secret")), "timeout", 2),
        (URLError("secret"), "transport", 2),
        (UnicodeDecodeError("utf-8", b"secret", 0, 1, "secret"), "invalid_json", 1),
    ],
)
def test_fetch_error_is_bounded_and_redacted(monkeypatch, error, category, attempts):
    calls = []

    def fail(request, timeout):
        calls.append(timeout)
        raise error

    monkeypatch.setattr(sta_client, "urlopen", fail)
    with pytest.raises(sta_client.CivilIotStaFetchError) as caught:
        sta_client.fetch_sta_json(URL, 8)
    message = str(caught.value)
    assert f"category={category}" in message
    assert "service=STA_RainSewer" in message
    assert f"attempts={attempts}" in message
    assert "timeout_seconds=8" in message
    assert "secret" not in message
    assert "https://" not in message
    assert calls == [8] * attempts


@pytest.mark.parametrize(("status", "attempts"), [(503, 2), (403, 1), (429, 1)])
def test_http_diagnostics_preserve_status_and_retry_limit(monkeypatch, status, attempts):
    calls = []

    def fail(request, timeout):
        calls.append(timeout)
        raise HTTPError(URL, status, "secret", {}, None)

    monkeypatch.setattr(sta_client, "urlopen", fail)
    with pytest.raises(sta_client.CivilIotStaFetchError) as caught:
        sta_client.fetch_sta_json(URL, 8)
    assert f"HTTP {status}" in str(caught.value)
    assert f"attempts={attempts}" in str(caught.value)
    assert "secret" not in str(caught.value)
    assert len(calls) == attempts


@pytest.mark.parametrize("fetcher", [
    sta_client.fetch_paginated_sta_things,
    sta_client.fetch_paginated_sta_datastreams,
])
def test_second_page_failure_keeps_progress_and_fails_closed(fetcher):
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            return {"value": [], "@iot.nextLink": URL + "&$skip=1"}
        raise sta_client.CivilIotStaFetchError("category=timeout")

    with pytest.raises(sta_client.CivilIotStaFetchError) as caught:
        fetcher(URL, timeout_seconds=8, fetch_json=fetch, source_url=URL)
    assert "pages_fetched=1; source_items_seen=0" in str(caught.value)
    assert len(calls) == 2


def test_ingestion_records_safe_diagnostics_without_hiding_failure(monkeypatch):
    def fail(request, timeout):
        raise TimeoutError("secret")

    monkeypatch.setattr(sta_client, "urlopen", fail)
    adapter = StaWaterLevelApiAdapter(SEWER_WATER_LEVEL)
    summary = run_adapter_batch(adapter, job_key="offline-diagnostics")
    assert summary.status == "failed"
    assert summary.error_code == "CivilIotStaFetchError"
    assert "category=timeout" in summary.error_message
    assert "pages_fetched=0" in summary.error_message
    assert "secret" not in summary.error_message
    assert summary.items_fetched == 0



@pytest.mark.parametrize("fetcher", [
    sta_client.fetch_paginated_sta_things,
    sta_client.fetch_paginated_sta_datastreams,
])
def test_cycle_error_does_not_copy_next_link_credentials(fetcher):
    def fetch(url, timeout):
        return {"value": [], "@iot.nextLink": URL}

    with pytest.raises(sta_client.CivilIotStaPayloadError) as caught:
        fetcher(URL, timeout_seconds=8, fetch_json=fetch, source_url=URL)
    assert "repeated @iot.nextLink" in str(caught.value)
    assert "pages_fetched=1" in str(caught.value)
    assert "secret" not in str(caught.value)
