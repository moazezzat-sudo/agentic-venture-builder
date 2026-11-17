"""Web search with a fallback chain and disk cache: tools/search.py. No network: engines are fakes."""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import search as search_mod  # noqa: E402
from tools.search import SNIPPET_CHARS, search  # noqa: E402

RAW = [
    {"title": "Freelancers  can't <b>get</b> paid", "url": "https://www.reddit.com/r/freelance/1", "snippet": "x" * 1000},
    {"title": "Invoice tool pricing", "url": "https://www.freshbooks.com/pricing", "snippet": "Plans &amp; prices"},
    {"title": "dup", "url": "https://www.reddit.com/r/freelance/1", "snippet": "same url again"},
    {"title": "no link", "url": "", "snippet": "dropped"},
    {"title": "Fourth", "url": "https://example.org/4", "snippet": "beyond max_results"},
]


class FakeEngine:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, query, max_results):
        self.calls += 1
        item = self.responses.pop(0) if self.responses else []
        if isinstance(item, Exception):
            raise item
        return item


def use_engines(monkeypatch, **engines):
    monkeypatch.setattr(search_mod, "ENGINES", list(engines.items()))
    return engines


def test_first_engine_with_results_answers(tmp_path, monkeypatch):
    e = use_engines(monkeypatch, first=FakeEngine(RAW), second=FakeEngine(RAW))
    results = search("freelance invoicing pain", cache_dir=tmp_path)
    assert [r["url"] for r in results] == [
        "https://www.reddit.com/r/freelance/1",
        "https://www.freshbooks.com/pricing",
        "https://example.org/4",
    ]
    assert set(results[0]) == {"title", "url", "snippet", "engine"}
    assert all(r["engine"] == "first" for r in results)
    assert results[0]["title"] == "Freelancers can't get paid"  # tags and extra spaces removed
    assert results[1]["snippet"] == "Plans & prices"  # HTML entities decoded
    assert len(results[0]["snippet"]) == SNIPPET_CHARS
    assert e["second"].calls == 0


def test_falls_back_past_errors_and_empty_engines_and_logs_them(tmp_path, monkeypatch, caplog):
    use_engines(
        monkeypatch,
        **{"ddgs:duckduckgo": FakeEngine(RuntimeError("No results found.")),
           "ddgs:brave": FakeEngine(TimeoutError("timed out")),
           "wikipedia": FakeEngine([]),
           "hackernews": FakeEngine(RAW[:1])},
    )
    with caplog.at_level(logging.INFO, logger="tools.search"):
        results = search("q", cache_dir=tmp_path)
    assert [r["engine"] for r in results] == ["hackernews"]
    message = caplog.text
    assert "answered by hackernews" in message
    assert "ddgs:duckduckgo: No results found." in message and "ddgs:brave: timed out" in message
    assert "wikipedia: no results" in message


def test_every_engine_failing_returns_empty_list_logs_and_caches_nothing(tmp_path, monkeypatch, caplog):
    use_engines(monkeypatch, a=FakeEngine(RuntimeError("down")), b=FakeEngine([]))
    with caplog.at_level(logging.WARNING, logger="tools.search"):
        assert search("q", cache_dir=tmp_path) == []
    assert "no engine returned results" in caplog.text and "a: down" in caplog.text and "b: no results" in caplog.text
    assert not list(tmp_path.glob("*.json"))


def test_second_call_is_served_from_disk_cache(tmp_path, monkeypatch):
    e = use_engines(monkeypatch, only=FakeEngine(RAW))
    first = search("Freelance invoicing pain", cache_dir=tmp_path)
    second = search("  freelance   INVOICING pain ", cache_dir=tmp_path)  # same query, other spacing/case
    assert first == second and e["only"].calls == 1
    [cache_file] = tmp_path.glob("*.json")
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["query"] == "Freelance invoicing pain" and cached["engine"] == "only"
    assert cached["fetched_at"].endswith("Z")


def test_empty_answer_is_not_cached_so_the_next_run_searches_again(tmp_path, monkeypatch):
    e = use_engines(monkeypatch, only=FakeEngine([], RAW))
    assert search("q", cache_dir=tmp_path) == []
    assert not list(tmp_path.glob("*.json"))
    assert len(search("q", cache_dir=tmp_path)) == 3
    assert e["only"].calls == 2


def test_max_results_is_part_of_the_cache_key(tmp_path, monkeypatch):
    e = use_engines(monkeypatch, only=FakeEngine(RAW, RAW))
    assert len(search("q", max_results=1, cache_dir=tmp_path)) == 1
    assert len(search("q", max_results=2, cache_dir=tmp_path)) == 2
    assert e["only"].calls == 2


def test_use_cache_false_always_searches(tmp_path, monkeypatch):
    e = use_engines(monkeypatch, only=FakeEngine(RAW, RAW))
    search("q", cache_dir=tmp_path, use_cache=False)
    search("q", cache_dir=tmp_path, use_cache=False)
    assert e["only"].calls == 2 and not list(tmp_path.glob("*.json"))


def test_default_chain_order_uses_real_ddgs_backends():
    from ddgs.engines import ENGINES as DDGS_ENGINES

    names = [name for name, _ in search_mod.ENGINES]
    assert names[0] == "ddgs:duckduckgo"
    assert names[-2:] == ["wikipedia", "hackernews"]
    for name in names[:-2]:
        assert name.startswith("ddgs:") and name.split(":", 1)[1] in DDGS_ENGINES["text"]


def test_unknown_ddgs_backend_raises_instead_of_falling_back_to_auto():
    with pytest.raises(ValueError):
        search_mod._ddgs_text("q", 3, backend="google")


@pytest.mark.parametrize("query,max_results", [("", 3), ("   ", 3), (None, 3), ("q", 0)])
def test_rejects_bad_arguments(tmp_path, query, max_results):
    with pytest.raises(ValueError):
        search(query, max_results=max_results, cache_dir=tmp_path)


def test_fallback_engines_are_not_cached_and_stale_fallback_cache_is_ignored(tmp_path, monkeypatch):
    e = use_engines(
        monkeypatch,
        **{"ddgs:duckduckgo": FakeEngine([], RAW[:1]),
           "wikipedia": FakeEngine(RAW[:1])},
    )
    first = search("q", cache_dir=tmp_path)
    assert first[0]["engine"] == "wikipedia"
    assert not list(tmp_path.glob("*.json"))  # fallback result is not cached
    second = search("q", cache_dir=tmp_path)
    assert second[0]["engine"] == "ddgs:duckduckgo" and e["ddgs:duckduckgo"].calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 1

