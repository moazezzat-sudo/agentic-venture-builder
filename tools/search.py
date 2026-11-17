"""Free web search for the researcher agents (DuckDuckGo via the ddgs package).

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.search import search
    results = search("freelance invoicing pain points egypt", max_results=3)
    # -> [{"title": "...", "url": "https://...", "snippet": "..."}]

Results are cached on disk under .cache/search/ so repeated runs do not
spend search requests, and snippets are cut to SNIPPET_CHARS to keep each
run inside the token budget.

STUBBED: no search is made yet. search() returns an empty list, so callers
treat every claim as unsourced (ASSUMPTION) until the real search lands.
"""

from __future__ import annotations

from typing import TypedDict

STUBBED = True  # set to False once the real DuckDuckGo search replaces the placeholder body

DEFAULT_MAX_RESULTS = 3
SNIPPET_CHARS = 300


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
    """Search the web and return up to max_results results as {title, url, snippet}.

    Cached on disk under .cache/search/; retried on transient errors.

    STUBBED: returns [] (no results) without any network call.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    return []


__all__ = ["search", "SearchResult", "DEFAULT_MAX_RESULTS", "SNIPPET_CHARS", "STUBBED"]
