"""World Bank indicators: tools/worldbank.py. No network: the HTTP call is replaced by a fake.

The fake payloads copy the shape of real API answers ([meta, rows] or [meta, null]);
the numbers in them are test fixtures, not data.
"""

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import worldbank as wb  # noqa: E402
from tools.credibility import rate  # noqa: E402

META = {"page": 1, "pages": 1, "per_page": 50, "total": 2}


def _row(year, value):
    return {
        "indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
        "country": {"id": "EG", "value": "Egypt, Arab Rep."},
        "countryiso3code": "EGY",
        "date": str(year),
        "value": value,
    }


class FakeGet:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(wb.time, "sleep", lambda s: None)


def test_returns_latest_value_year_and_api_url(tmp_path, monkeypatch):
    fake = FakeGet([[META, [_row(2023, 10.0), _row(2024, 12.5), _row(2025, None)]]])
    monkeypatch.setattr(wb, "_get_json", fake)
    result = wb.indicator("eg", wb.POPULATION, cache_dir=tmp_path)
    assert result["value"] == 12.5 and result["year"] == 2024
    assert result["source_url"] == (
        "https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1"
    )
    assert fake.urls == [result["source_url"]]
    assert result["indicator"] == "Population, total" and result["country"] == "Egypt, Arab Rep."
    assert rate(result["source_url"]) == "A"


def test_successful_answer_is_cached(tmp_path, monkeypatch):
    fake = FakeGet([[META, [_row(2024, 12.5)]]])
    monkeypatch.setattr(wb, "_get_json", fake)
    first = wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path)
    second = wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path)
    assert first == second and len(fake.urls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_unknown_country_gives_none_not_a_guess(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "_get_json", FakeGet([[{"page": 0, "total": 0}, None]]))
    result = wb.indicator("XX", wb.POPULATION, cache_dir=tmp_path)
    assert result["value"] is None and result["year"] is None and "no data" in result["error"]
    assert not list(tmp_path.glob("*.json"))


def test_api_error_message_is_reported(tmp_path, monkeypatch):
    payload = [{"message": [{"id": "175", "key": "Invalid format", "value": "The indicator was not found."}]}]
    fake = FakeGet([payload])
    monkeypatch.setattr(wb, "_get_json", fake)
    result = wb.indicator("EG", "NOT.REAL", cache_dir=tmp_path)
    assert result["value"] is None and "indicator was not found" in result["error"]
    assert len(fake.urls) == 1  # an API error is an answer, not retried


def test_retries_then_succeeds(tmp_path, monkeypatch):
    fake = FakeGet([requests.ReadTimeout("slow"), requests.ConnectionError("reset"), [META, [_row(2024, 1.0)]]])
    monkeypatch.setattr(wb, "_get_json", fake)
    assert wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path)["value"] == 1.0
    assert len(fake.urls) == 3


def test_retry_switches_query_form_and_cites_the_url_that_answered(tmp_path, monkeypatch):
    fake = FakeGet([requests.ReadTimeout("hangs on mrnev"), [META, [_row(2024, 3.0), _row(2023, 2.0)]]])
    monkeypatch.setattr(wb, "_get_json", fake)
    result = wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path)
    assert fake.urls[0].endswith("mrnev=1") and fake.urls[1].endswith("mrv=5")
    assert result["source_url"] == fake.urls[1] and result["value"] == 3.0 and result["year"] == 2024
    # the cache is keyed on the request, so the next call is served from disk
    assert wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path) == result and len(fake.urls) == 2


def test_gives_up_with_none_after_max_attempts(tmp_path, monkeypatch):
    fake = FakeGet([requests.ReadTimeout("slow")] * wb.MAX_ATTEMPTS)
    monkeypatch.setattr(wb, "_get_json", fake)
    result = wb.indicator("EG", wb.POPULATION, cache_dir=tmp_path)
    assert result["value"] is None and "did not answer" in result["error"]
    assert result["source_url"].startswith("https://api.worldbank.org/")
    assert len(fake.urls) == wb.MAX_ATTEMPTS
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("country,code", [("", "SP.POP.TOTL"), ("Egypt", "SP.POP.TOTL"), ("EG", ""),
                                          ("EG", "SP.POP.TOTL&x=1"), (None, "SP.POP.TOTL")])
def test_rejects_malformed_arguments(tmp_path, country, code):
    with pytest.raises(ValueError):
        wb.indicator(country, code, cache_dir=tmp_path)
