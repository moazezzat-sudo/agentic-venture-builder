"""Free web search for the researcher agents (DuckDuckGo via the ddgs package).

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.search import search
    results = search("freelance invoicing pain points egypt", max_results=3)
    # -> [{"title": "...", "url": "https://...", "snippet": "..."}]

- Only DuckDuckGo is queried (ddgs backend "duckduckgo"); no key, no paid service.
- Results are cached on disk under .cache/search/ (one JSON file per query), so
  repeated runs spend no search requests and give the same results.
- Snippets are cut to SNIPPET_CHARS to keep each run inside the token budget.
- Rate limits, timeouts and other search errors are retried with backoff
  (MAX_ATTEMPTS). If every attempt fails, search() returns []: the caller
  then has no source, so its claims stay ASSUMPTION.
- Empty results are never cached, because DuckDuckGo's bot check also comes
  back as "No results found"; the next run searches again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional, TypedDict

from config import settings
from schemas import utc_now

STUBBED = False

DEFAULT_MAX_RESULTS = 3
SNIPPET_CHARS = 300
BACKEND = "duckduckgo"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
TIMEOUT_SECONDS = 10

log = logging.getLogger(__name__)


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str


def _cache_dir() -> Path:
    return Path(settings.cache_dir) / "search"


def _cache_path(query: str, max_results: int, cache_dir: Path) -> Path:
    key = f"{BACKEND}|{max_results}|{' '.join(query.lower().split())}"
    return cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}.json"


def _ddgs_text(query: str, max_results: int) -> list[dict[str, Any]]:
    """One DuckDuckGo request through ddgs. Raises ddgs exceptions on failure."""
    from ddgs import DDGS

    return DDGS(timeout=TIMEOUT_SECONDS).text(query, max_results=max_results, backend=BACKEND)


def _is_no_results(exc: Exception) -> bool:
    return "no results" in str(exc).lower()


def _normalise(raw: list[dict[str, Any]], max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in raw or []:
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        snippet = " ".join(str(item.get("body") or item.get("snippet") or "").split())
        results.append({
            "title": " ".join(str(item.get("title") or "").split()) or url,
            "url": url,
            "snippet": snippet[:SNIPPET_CHARS],
        })
        if len(results) == max_results:
            break
    return results


def search(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> list[SearchResult]:
    """Search DuckDuckGo and return up to max_results results as {title, url, snippet}.

    Cached on disk under .cache/search/ (or cache_dir); retried on errors.
    Returns [] if the search keeps failing; that empty result is not cached.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be a positive integer")
    query = query.strip()
    folder = Path(cache_dir or _cache_dir())
    path = _cache_path(query, max_results, folder)

    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["results"]
        except (OSError, ValueError, KeyError):
            log.warning("ignoring unreadable search cache file %s", path)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            results = _normalise(_ddgs_text(query, max_results), max_results)
            break
        except Exception as exc:  # ddgs raises DDGSException, RatelimitException, TimeoutException
            if _is_no_results(exc):
                results = []
                break
            log.warning("search attempt %d/%d failed for %r: %s", attempt, MAX_ATTEMPTS, query, exc)
            if attempt == MAX_ATTEMPTS:
                return []
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))

    # Empty results are never cached: DuckDuckGo answers a bot check with an empty page,
    # which ddgs reports as "No results found", and that must not stick once it clears.
    if use_cache and results:
        folder.mkdir(parents=True, exist_ok=True)
        payload = {"query": query, "backend": BACKEND, "fetched_at": utc_now(), "results": results}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    return results


__all__ = ["search", "SearchResult", "DEFAULT_MAX_RESULTS", "SNIPPET_CHARS", "STUBBED"]
