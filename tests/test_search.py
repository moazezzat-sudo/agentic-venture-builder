"""Web search with disk cache and retry: tools/search.py. No network: ddgs is replaced by a fake."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import search as search_mod  # noqa: E402
from tools.search import SNIPPET_CHARS, search  # noqa: E402

RAW = [
    {"title": "Freelancers  can't get paid", "href": "https://www.reddit.com/r/freelance/1", "body": "x" * 1000},
    {"title": "Invoice tool pricing", "href": "https://www.freshbooks.com/pricing", "body": "Plans from ..."},
    {"title": "dup", "href": "https://www.reddit.com/r/freelance/1", "body": "same url again"},
    {"title": "no link", "href": "", "body": "dropped"},
    {"title": "Fourth", "href": "https://example.org/4", "body": "beyond max_results"},
]


class FakeDDGS:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, query, max_results):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(search_mod.time, "sleep", lambda s: None)


def test_returns_top_results_with_title_url_snippet(tmp_path, monkeypatch):
    fake = FakeDDGS([RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    results = search("freelance invoicing pain", cache_dir=tmp_path)
    assert [r["url"] for r in results] == [
        "https://www.reddit.com/r/freelance/1",
        "https://www.freshbooks.com/pricing",
        "https://example.org/4",
    ]
    assert set(results[0]) == {"title", "url", "snippet"}
    assert results[0]["title"] == "Freelancers can't get paid"
    assert len(results[0]["snippet"]) == SNIPPET_CHARS


def test_second_call_is_served_from_disk_cache(tmp_path, monkeypatch):
    fake = FakeDDGS([RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    first = search("Freelance invoicing pain", cache_dir=tmp_path)
    second = search("  freelance   INVOICING pain ", cache_dir=tmp_path)  # same query, other spacing/case
    assert first == second and fake.calls == 1
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    cached = json.loads(files[0].read_text(encoding="utf-8"))
    assert cached["query"] == "Freelance invoicing pain" and cached["backend"] == "duckduckgo"
    assert cached["fetched_at"].endswith("Z")


def test_max_results_is_part_of_the_cache_key(tmp_path, monkeypatch):
    fake = FakeDDGS([RAW, RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    assert len(search("q", max_results=1, cache_dir=tmp_path)) == 1
    assert len(search("q", max_results=2, cache_dir=tmp_path)) == 2
    assert fake.calls == 2


def test_retries_then_succeeds(tmp_path, monkeypatch):
    fake = FakeDDGS([TimeoutError("timed out"), RuntimeError("202 Ratelimit"), RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    assert len(search("q", cache_dir=tmp_path)) == 3
    assert fake.calls == 3


def test_gives_up_with_empty_list_and_caches_nothing(tmp_path, monkeypatch):
    fake = FakeDDGS([RuntimeError("down")] * search_mod.MAX_ATTEMPTS)
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    assert search("q", cache_dir=tmp_path) == []
    assert fake.calls == search_mod.MAX_ATTEMPTS
    assert not list(tmp_path.glob("*.json"))


def test_no_results_is_not_retried_and_not_cached(tmp_path, monkeypatch):
    fake = FakeDDGS([RuntimeError("No results found."), RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    assert search("q", cache_dir=tmp_path) == []
    assert fake.calls == 1
    assert not list(tmp_path.glob("*.json"))
    assert len(search("q", cache_dir=tmp_path)) == 3  # next call searches again
    assert fake.calls == 2


def test_use_cache_false_always_searches(tmp_path, monkeypatch):
    fake = FakeDDGS([RAW, RAW])
    monkeypatch.setattr(search_mod, "_ddgs_text", fake)
    search("q", cache_dir=tmp_path, use_cache=False)
    search("q", cache_dir=tmp_path, use_cache=False)
    assert fake.calls == 2 and not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("query,max_results", [("", 3), ("   ", 3), (None, 3), ("q", 0)])
def test_rejects_bad_arguments(tmp_path, query, max_results):
    with pytest.raises(ValueError):
        search(query, max_results=max_results, cache_dir=tmp_path)
