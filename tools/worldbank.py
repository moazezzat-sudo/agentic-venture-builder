"""World Bank Open Data indicators (free, no key). Every value is a tier A source.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.worldbank import indicator, POPULATION
    indicator("EG", POPULATION)
    # -> {"value": <float>, "year": <int>,
    #     "source_url": "https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json&mrnev=1",
    #     "indicator": "Population, total", "country": "Egypt, Arab Rep."}

country is an ISO 2- or 3-letter code ("EG", "EGY"), a country name ("Egypt",
"Egypt, Arab Rep.", "UAE", "South Korea") or a location ending in one
("Cairo, Egypt"). Names are matched against the World Bank country list
(fetched once, cached under .cache/worldbank/), with a small built-in list
used when the API cannot be reached. country_code() exposes the lookup.
code is a World Bank indicator code; the three the researchers need are named below. The value is
the most recent year that has data. source_url is the exact API URL the value
came from, so it can be stored on a Claim with tier "A".

The API is free but sometimes hangs on one query form while another answers at
once, so retries alternate between mrnev=1 and mrv=5 with backoff, and
successful answers are cached under .cache/worldbank/. If no value can be
had (unknown country or code, no data, or the API keeps failing), value and
year are None and "error" says why: nothing is ever made up.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional, TypedDict

import requests

from config import settings
from schemas import utc_now

STUBBED = False

API_BASE = "https://api.worldbank.org/v2"
TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0

POPULATION = "SP.POP.TOTL"
INTERNET_USERS_PCT = "IT.NET.USER.ZS"
GDP_PER_CAPITA_USD = "NY.GDP.PCAP.CD"

INDICATORS: dict[str, str] = {
    POPULATION: "Population, total",
    INTERNET_USERS_PCT: "Individuals using the Internet (% of population)",
    GDP_PER_CAPITA_USD: "GDP per capita (current US$)",
}

_COUNTRY_RE = re.compile(r"^[A-Za-z]{2,3}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_.]+$")

log = logging.getLogger(__name__)


class IndicatorValue(TypedDict, total=False):
    value: Optional[float]
    year: Optional[int]
    source_url: str
    indicator: Optional[str]
    country: Optional[str]
    error: str


class WorldBankError(RuntimeError):
    """The API answered, but with an error message (for example an unknown indicator)."""


# The API sometimes hangs on one query form while another answers at once, so
# retries alternate: the latest non-empty value, then the last five values.
QUERY_VARIANTS = ("format=json&mrnev=1", "format=json&mrv=5")


def source_url(country: str, code: str, variant: int = 0) -> str:
    """The public API URL for one indicator in one country (variant picks the query form)."""
    query = QUERY_VARIANTS[variant % len(QUERY_VARIANTS)]
    return f"{API_BASE}/country/{country.strip().upper()}/indicator/{code.strip()}?{query}"


def _get_json(url: str) -> Any:
    """One API request. Raises requests exceptions on network or HTTP errors."""
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _parse(payload: Any, url: str) -> IndicatorValue:
    """Turn the API's [meta, rows] answer into {value, year, source_url, indicator, country}."""
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "message" in payload[0]:
        messages = payload[0]["message"] or [{}]
        raise WorldBankError("; ".join(str(m.get("value") or m.get("key") or m) for m in messages))
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
    if not rows:
        return {"value": None, "year": None, "source_url": url, "indicator": None, "country": None,
                "error": "no data for this country and indicator"}
    rows = sorted((r for r in rows if r.get("value") is not None), key=lambda r: str(r.get("date")), reverse=True)
    if not rows:
        return {"value": None, "year": None, "source_url": url, "indicator": None, "country": None,
                "error": "no non-empty value for this country and indicator"}
    row = rows[0]
    year = str(row.get("date", ""))
    return {
        "value": float(row["value"]),
        "year": int(year) if year.isdigit() else None,
        "source_url": url,
        "indicator": (row.get("indicator") or {}).get("value"),
        "country": (row.get("country") or {}).get("value"),
    }


def _cache_path(url: str, cache_dir: Path) -> Path:
    return cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]}.json"


# ---------------------------------------------------------------- country names

COUNTRY_LIST_URL = f"{API_BASE}/country?format=json&per_page=400"

# Common names that differ from the World Bank's official names, or are ambiguous there.
COUNTRY_ALIASES: dict[str, str] = {
    "uae": "AE", "emirates": "AE", "uk": "GB", "britain": "GB", "great britain": "GB", "england": "GB",
    "usa": "US", "us": "US", "united states of america": "US", "america": "US",
    "south korea": "KR", "north korea": "KP", "russia": "RU", "iran": "IR",
    "turkey": "TR", "vietnam": "VN", "syria": "SY", "laos": "LA", "slovakia": "SK",
    "kyrgyzstan": "KG", "palestine": "PS", "drc": "CD", "dr congo": "CD", "ivory coast": "CI",
    "czech republic": "CZ", "micronesia": "FM", "hong kong": "HK", "macau": "MO", "macao": "MO",
}
# Used only when the World Bank country list cannot be fetched.
BUILTIN_COUNTRIES: dict[str, str] = {
    "egypt": "EG", "saudi arabia": "SA", "united arab emirates": "AE", "jordan": "JO", "lebanon": "LB",
    "morocco": "MA", "tunisia": "TN", "algeria": "DZ", "libya": "LY", "sudan": "SD", "iraq": "IQ",
    "kuwait": "KW", "qatar": "QA", "bahrain": "BH", "oman": "OM", "kenya": "KE", "nigeria": "NG",
    "ghana": "GH", "south africa": "ZA", "india": "IN", "pakistan": "PK", "bangladesh": "BD",
    "indonesia": "ID", "malaysia": "MY", "philippines": "PH", "china": "CN", "japan": "JP",
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES", "netherlands": "NL",
    "united kingdom": "GB", "united states": "US", "canada": "CA", "brazil": "BR", "mexico": "MX",
    "argentina": "AR", "australia": "AU", "turkiye": "TR",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"^the ", "", " ".join(text.split()))
    return text


def _country_rows(cache_dir: Path, use_cache: bool = True) -> Optional[list[dict[str, str]]]:
    """[{iso2, iso3, name}] from the World Bank country list, cached on disk; None if unreachable."""
    path = cache_dir / "countries.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["countries"]
        except (OSError, ValueError, KeyError):
            log.warning("ignoring unreadable World Bank country cache %s", path)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            payload = _get_json(COUNTRY_LIST_URL)
            rows = [
                {"iso2": str(r.get("iso2Code", "")).upper(), "iso3": str(r.get("id", "")).upper(), "name": str(r.get("name", ""))}
                for r in (payload[1] if isinstance(payload, list) and len(payload) > 1 and payload[1] else [])
                if r.get("iso2Code") and r.get("name")
            ]
            if not rows:
                raise ValueError("empty country list")
            break
        except (requests.RequestException, ValueError, TypeError, IndexError) as exc:
            log.warning("World Bank country list attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
            if attempt == MAX_ATTEMPTS:
                return None
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": utc_now(), "countries": rows}, indent=1), encoding="utf-8")
        tmp.replace(path)
    return rows


def _name_index(rows: Optional[list[dict[str, str]]]) -> dict[str, str]:
    """Normalised name -> ISO2 code. Short forms ("egypt" from "Egypt, Arab Rep.") only when unambiguous."""
    if rows is None:
        index = dict(BUILTIN_COUNTRIES)
    else:
        index = {_norm(r["name"]): r["iso2"] for r in rows}
        short: dict[str, set[str]] = {}
        for r in rows:
            if "," in r["name"]:
                short.setdefault(_norm(r["name"].split(",")[0]), set()).add(r["iso2"])
        for name, codes in short.items():
            if len(codes) == 1 and name not in index:
                index[name] = codes.pop()
    index.update(COUNTRY_ALIASES)
    return index


def country_code(country: str, cache_dir: Optional[Path] = None, use_cache: bool = True) -> Optional[str]:
    """Return the World Bank country code for an ISO code, a country name or a "City, Country" location.

    None when nothing matches. ISO codes are returned upper-case as given ("EGY" stays "EGY").
    """
    if not isinstance(country, str) or not country.strip():
        return None
    folder = Path(cache_dir or Path(settings.cache_dir) / "worldbank")
    text = country.strip()
    norm = _norm(text)
    if norm in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[norm]
    rows = _country_rows(folder, use_cache)
    if _COUNTRY_RE.match(text):
        codes = None if rows is None else {r["iso2"] for r in rows} | {r["iso3"] for r in rows}
        if codes is None or text.upper() in codes:
            return text.upper()
    index = _name_index(rows)
    if norm in index:
        return index[norm]
    # "Cairo, Egypt" / "Riyadh - Saudi Arabia": try the parts, last first.
    for part in reversed([p for p in re.split(r",|/|\s-\s|\(|\)", text) if p.strip()]):
        if _norm(part) in index:
            return index[_norm(part)]
    return None


# ---------------------------------------------------------------- indicator

def indicator(
    country: str,
    code: str,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> IndicatorValue:
    """Return the latest {value, year, source_url} (plus indicator and country names).

    country may be an ISO code, a country name or a "City, Country" location.
    value and year are None, with an "error" key, when no value is available
    (including a country name that matches no country).
    Raises ValueError only for an empty country or a malformed indicator code.
    """
    if not isinstance(country, str) or not country.strip():
        raise ValueError("country must be an ISO code such as 'EG' or a country name such as 'Egypt'")
    if not isinstance(code, str) or not _CODE_RE.match(code.strip()):
        raise ValueError("code must be a World Bank indicator code such as 'SP.POP.TOTL'")
    folder = Path(cache_dir or Path(settings.cache_dir) / "worldbank")
    resolved = country_code(country, cache_dir=folder, use_cache=use_cache)
    if resolved is None:
        return {"value": None, "year": None, "source_url": COUNTRY_LIST_URL, "indicator": None, "country": None,
                "error": f"no World Bank country matches {country.strip()!r}"}
    country = resolved
    url = source_url(country, code)
    path = _cache_path(url, folder)

    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["result"]
        except (OSError, ValueError, KeyError):
            log.warning("ignoring unreadable World Bank cache file %s", path)

    error = "World Bank API did not answer"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        url = source_url(country, code, variant=attempt - 1)
        try:
            result = _parse(_get_json(url), url)
            break
        except WorldBankError as exc:
            return {"value": None, "year": None, "source_url": url, "indicator": None, "country": None,
                    "error": f"World Bank API error: {exc}"}
        except (requests.RequestException, ValueError) as exc:
            error = f"World Bank API did not answer after {MAX_ATTEMPTS} attempts: {type(exc).__name__}"
            log.warning("World Bank attempt %d/%d failed for %s: %s", attempt, MAX_ATTEMPTS, url, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
    else:
        return {"value": None, "year": None, "source_url": url, "indicator": None, "country": None,
                "error": error}

    if use_cache and result["value"] is not None:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": utc_now(), "result": result}, indent=2), encoding="utf-8")
        tmp.replace(path)
    return result


__all__ = [
    "indicator",
    "country_code",
    "source_url",
    "IndicatorValue",
    "WorldBankError",
    "POPULATION",
    "INTERNET_USERS_PCT",
    "GDP_PER_CAPITA_USD",
    "INDICATORS",
    "STUBBED",
]
