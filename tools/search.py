"""Free web search for the researcher agents, with a fallback chain of free engines.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.search import search
    results = search("freelance invoicing pain points egypt", max_results=3)
    # -> [{"title": "...", "url": "https://...", "snippet": "...", "engine": "ddgs:duckduckgo"}]

Engines are tried in order until one returns results (ENGINES):
  1. ddgs with DuckDuckGo, then its other web backends (Brave, Mojeek, Yahoo, Startpage)
  2. Wikipedia search API (free, no key)
  3. Hacker News Algolia search API (free, no key); links point to the HN
     discussion, which tools.credibility rates D (community signal)
Every result carries "engine", the engine that answered, so the source of each
link is visible in the app and the log. No engine needs a key or a paid plan.

- Results are cached on disk under .cache/search/ (one JSON file per query), so
  repeated runs spend no search requests and give the same results.
- Snippets are cut to SNIPPET_CHARS to keep each run inside the token budget.
- Nothing fails silently: every engine that errors or comes back empty is
  logged with the reason, and so is the engine that answered. If every engine
  fails, search() returns [] and logs a warning listing them all.
- Empty results are never cached: DuckDuckGo's bot check also comes back as
  "No results found", and the next run must search again.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from functools import partial
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict
from urllib.parse import quote

import requests

from config import settings
from schemas import utc_now

STUBBED = False

DEFAULT_MAX_RESULTS = 3
SNIPPET_CHARS = 300
TIMEOUT_SECONDS = 5
# ddgs text backends, in order. Grokipedia (AI-written) is left out on purpose, and Wikipedia
# goes through its own API below. Names are checked, because ddgs silently swaps an unknown
# backend for "auto", which would mislabel the engine that answered.
DDGS_BACKENDS = ("duckduckgo", "brave", "mojeek", "yahoo", "startpage")
USER_AGENT = "agentic-venture-builder/0.1 (https://github.com/moazezzat-sudo/agentic-venture-builder)"

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    engine: str


Engine = Callable[[str, int], list[dict[str, Any]]]


def _clean(text: Any) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", str(text or ""))).split())


# ---------------------------------------------------------------- engines
# Each engine takes (query, max_results) and returns raw dicts with title/url/snippet.
# It raises on errors and returns [] when it has nothing.

def _ddgs_text(query: str, max_results: int, backend: str) -> list[dict[str, Any]]:
    from ddgs import DDGS
    from ddgs.engines import ENGINES as DDGS_ENGINES

    if backend not in DDGS_ENGINES.get("text", {}):
        raise ValueError(f"ddgs has no text backend {backend!r}")
    raw = DDGS(timeout=TIMEOUT_SECONDS).text(query, max_results=max_results, backend=backend)
    return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in raw or []]


def _wikipedia(query: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query, "srlimit": max_results, "format": "json"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    hits = response.json().get("query", {}).get("search", [])
    return [
        {
            "title": h.get("title"),
            "url": "https://en.wikipedia.org/wiki/" + quote(str(h.get("title", "")).replace(" ", "_")),
            "snippet": h.get("snippet"),
        }
        for h in hits
        if h.get("title")
    ]


def _hacker_news(query: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.get(
        "https://hn.algolia.com/api/v1/search",
        params={"query": query, "hitsPerPage": max_results, "tags": "(story,comment)"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    return [
        {
            "title": h.get("title") or h.get("story_title"),
            "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
            "snippet": h.get("story_text") or h.get("comment_text") or h.get("title") or h.get("story_title"),
        }
        for h in hits
        if h.get("objectID")
    ]


ENGINES: list[tuple[str, Engine]] = [
    *[(f"ddgs:{b}", partial(_ddgs_text, backend=b)) for b in DDGS_BACKENDS],
    ("wikipedia", _wikipedia),
    ("hackernews", _hacker_news),
]
# Fallback engines are not general web search: never cache them on disk, so the next run
# tries the web search backends again instead of serving a fallback answer from cache.
FALLBACK_ENGINES = ("wikipedia", "hackernews")


# ---------------------------------------------------------------- search

def _cache_dir() -> Path:
    return Path(settings.cache_dir) / "search"


def _cache_path(query: str, max_results: int, cache_dir: Path) -> Path:
    key = f"{max_results}|{' '.join(query.lower().split())}"
    return cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}.json"


def _normalise(raw: list[dict[str, Any]], max_results: int, engine: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in raw or []:
        url = str(item.get("url") or item.get("href") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({
            "title": _clean(item.get("title")) or url,
            "url": url,
            "snippet": _clean(item.get("snippet") or item.get("body"))[:SNIPPET_CHARS],
            "engine": engine,
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
    """Return up to max_results results as {title, url, snippet, engine}, from the first engine that answers.

    Cached on disk under .cache/search/ (or cache_dir). Returns [] only when every engine
    fails or finds nothing; each failure is logged.
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
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("engine") in FALLBACK_ENGINES:
                log.info("search %r: ignoring cached fallback engine %s", query, cached.get("engine"))
            else:
                log.info("search %r: served from cache (engine %s)", query, cached.get("engine"))
                return cached["results"]
        except (OSError, ValueError, KeyError):
            log.warning("search: ignoring unreadable cache file %s", path)

    failures: list[str] = []
    for name, engine in ENGINES:
        try:
            results = _normalise(engine(query, max_results), max_results, name)
        except Exception as exc:  # each engine has its own errors; none may stop the chain
            reason = str(exc).strip().splitlines()[0][:120] if str(exc).strip() else type(exc).__name__
            failures.append(f"{name}: {reason}")
            continue
        if not results:
            failures.append(f"{name}: no results")
            continue
        if failures:
            log.warning("search %r: answered by %s after %s", query, name, "; ".join(failures))
        else:
            log.info("search %r: answered by %s", query, name)
        if use_cache and name not in FALLBACK_ENGINES:
            folder.mkdir(parents=True, exist_ok=True)
            payload = {"query": query, "engine": name, "fetched_at": utc_now(), "results": results}
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return results

    log.warning("search %r: no engine returned results (%s)", query, "; ".join(failures))
    return []


__all__ = ["search", "SearchResult", "ENGINES", "DEFAULT_MAX_RESULTS", "SNIPPET_CHARS", "STUBBED"]
