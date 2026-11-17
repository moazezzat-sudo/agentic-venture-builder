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


def _country(iso2, iso3, name, region="Somewhere"):
    return {"id": iso3, "iso2Code": iso2, "name": name, "region": {"value": region}}


COUNTRIES = [{"page": 1, "pages": 1, "per_page": "400", "total": 8}, [
    _country("EG", "EGY", "Egypt, Arab Rep."),
    _country("AE", "ARE", "United Arab Emirates"),
    _country("KR", "KOR", "Korea, Rep."),
    _country("KP", "PRK", "Korea, Dem. People's Rep."),
    _country("TR", "TUR", "Turkiye"),
    _country("CI", "CIV", "Cote d'Ivoire"),
    _country("ZZ", "ZZZ", "Nodata Land"),
    _country("1A", "ARB", "Arab World", "Aggregates"),
]]


class FakeGet:
    """Serves the country list on its own URL, and the queued responses for indicator URLs."""

    def __init__(self, responses, countries=COUNTRIES):
        self.responses = list(responses)
        self.countries = countries
        self.urls = []
        self.country_calls = 0

    def __call__(self, url):
        if url == wb.COUNTRY_LIST_URL:
            self.country_calls += 1
            if isinstance(self.countries, Exception):
                raise self.countries
            return self.countries
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _value_files(folder):
    return [f for f in folder.glob("*.json") if f.name != "countries.json"]


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
    assert len(_value_files(tmp_path)) == 1


def test_country_without_data_gives_none_not_a_guess(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "_get_json", FakeGet([[{"page": 0, "total": 0}, None]]))
    result = wb.indicator("ZZ", wb.POPULATION, cache_dir=tmp_path)
    assert result["value"] is None and result["year"] is None and "no data" in result["error"]
    assert not _value_files(tmp_path)


def test_unknown_country_name_gives_none_and_makes_no_indicator_request(tmp_path, monkeypatch):
    fake = FakeGet([])
    monkeypatch.setattr(wb, "_get_json", fake)
    result = wb.indicator("Atlantis", wb.POPULATION, cache_dir=tmp_path)
    assert result["value"] is None and "no World Bank country matches 'Atlantis'" in result["error"]
    assert result["source_url"] == wb.COUNTRY_LIST_URL and fake.urls == []


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
    assert not _value_files(tmp_path)


@pytest.mark.parametrize("name,expected", [
    ("Egypt", "EG"), ("egypt", "EG"), ("Egypt, Arab Rep.", "EG"), ("Cairo, Egypt", "EG"),
    ("EG", "EG"), ("eg", "EG"), ("EGY", "EGY"),
    ("UAE", "AE"), ("United Arab Emirates", "AE"), ("Dubai - United Arab Emirates", "AE"),
    ("Turkey", "TR"), ("Türkiye", "TR"), ("Côte d'Ivoire", "CI"), ("Ivory Coast", "CI"),
    ("South Korea", "KR"), ("UK", "GB"), ("USA", "US"),
    ("Korea", None),  # ambiguous: both Koreas are "Korea, ..." -> no guess
    ("Atlantis", None), ("", None),
])
def test_country_code_from_names_codes_and_locations(tmp_path, monkeypatch, name, expected):
    monkeypatch.setattr(wb, "_get_json", FakeGet([]))
    assert wb.country_code(name, cache_dir=tmp_path) == expected


def test_country_list_is_fetched_once_and_cached(tmp_path, monkeypatch):
    fake = FakeGet([[META, [_row(2024, 1.0)]], [META, [_row(2024, 2.0)]]])
    monkeypatch.setattr(wb, "_get_json", fake)
    assert wb.indicator("Egypt", wb.POPULATION, cache_dir=tmp_path)["value"] == 1.0
    assert fake.urls[0].startswith("https://api.worldbank.org/v2/country/EG/indicator/")
    assert wb.indicator("Cairo, Egypt", wb.INTERNET_USERS_PCT, cache_dir=tmp_path)["value"] == 2.0
    assert fake.country_calls == 1 and (tmp_path / "countries.json").exists()


def test_builtin_names_when_the_country_list_is_unreachable(tmp_path, monkeypatch):
    fake = FakeGet([[META, [_row(2024, 1.0)]]], countries=requests.ReadTimeout("slow"))
    monkeypatch.setattr(wb, "_get_json", fake)
    assert wb.country_code("Saudi Arabia", cache_dir=tmp_path) == "SA"
    assert wb.country_code("EG", cache_dir=tmp_path) == "EG"  # codes pass through unchecked
    assert wb.indicator("Egypt", wb.POPULATION, cache_dir=tmp_path)["value"] == 1.0
    assert not (tmp_path / "countries.json").exists()


@pytest.mark.parametrize("country,code", [("", "SP.POP.TOTL"), ("   ", "SP.POP.TOTL"), (None, "SP.POP.TOTL"),
                                          ("EG", ""), ("EG", "SP.POP.TOTL&x=1")])
def test_rejects_malformed_arguments(tmp_path, country, code):
    with pytest.raises(ValueError):
        wb.indicator(country, code, cache_dir=tmp_path)
