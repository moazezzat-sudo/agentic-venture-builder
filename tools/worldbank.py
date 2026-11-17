"""World Bank Open Data indicators (free, no key). Every value is a tier A source.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.worldbank import indicator, POPULATION
    indicator("EG", POPULATION)
    # -> {"value": <float>, "year": <int>,
    #     "source_url": "https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json"}

country is an ISO 2- or 3-letter code ("EG", "EGY"). code is a World Bank
indicator code; the three the researchers need are named below. The value
is the most recent year that has data. source_url is the API URL the value
came from, so it can be stored on a Claim with tier "A".

STUBBED: no request is made yet. indicator() returns value=None and
year=None with the real source_url, so nothing can be quoted from it.
"""

from __future__ import annotations

from typing import Optional, TypedDict

STUBBED = True  # set to False once the real API call replaces the placeholder body

API_BASE = "https://api.worldbank.org/v2"

POPULATION = "SP.POP.TOTL"
INTERNET_USERS_PCT = "IT.NET.USER.ZS"
GDP_PER_CAPITA_USD = "NY.GDP.PCAP.CD"

INDICATORS: dict[str, str] = {
    POPULATION: "Population, total",
    INTERNET_USERS_PCT: "Individuals using the Internet (% of population)",
    GDP_PER_CAPITA_USD: "GDP per capita (current US$)",
}


class IndicatorValue(TypedDict):
    value: Optional[float]
    year: Optional[int]
    source_url: str


def source_url(country: str, code: str) -> str:
    """The public API URL for one country and indicator."""
    return f"{API_BASE}/country/{country.strip().upper()}/indicator/{code.strip()}?format=json"


def indicator(country: str, code: str) -> IndicatorValue:
    """Return the latest {value, year, source_url} for a country and indicator code.

    STUBBED: returns value=None, year=None and the real source_url, without a network call.
    """
    if not isinstance(country, str) or not country.strip():
        raise ValueError("country must be an ISO country code such as 'EG'")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a World Bank indicator code such as 'SP.POP.TOTL'")
    return {"value": None, "year": None, "source_url": source_url(country, code)}


__all__ = [
    "indicator",
    "source_url",
    "IndicatorValue",
    "POPULATION",
    "INTERNET_USERS_PCT",
    "GDP_PER_CAPITA_USD",
    "INDICATORS",
    "STUBBED",
]
