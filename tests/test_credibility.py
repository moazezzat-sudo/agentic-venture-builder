"""Source credibility tiers (PLAN.md section 3a): tools/credibility.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.credibility import rate, rate_with_reason  # noqa: E402


@pytest.mark.parametrize(
    "url",
    [
        "https://www.capmas.gov.eg/Pages/Publications.aspx",
        "https://www.census.gov/data.html",
        "https://www.gov.uk/government/statistics",
        "https://www.gob.mx/inegi",
        "https://www.stat.go.jp/english/",
        "https://www.who.int/data",
        "https://data.worldbank.org/indicator/SP.POP.TOTL",
        "https://api.worldbank.org/v2/country/EG/indicator/SP.POP.TOTL?format=json",
        "https://www.imf.org/en/Data",
        "https://data.un.org/",
        "https://www.ecb.europa.eu/stats/",
        "https://www.cbe.org.eg/en/economic-research",
    ],
)
def test_official_sources_are_tier_a(url):
    assert rate(url) == "A"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reddit.com/r/smallbusiness/",
        "https://old.reddit.com/r/egypt/comments/abc",
        "https://www.facebook.com/groups/123",
        "https://x.com/someone/status/1",
        "https://twitter.com/someone",
        "https://news.ycombinator.com/item?id=1",
        "https://www.quora.com/What-is",
        "https://www.trustpilot.com/review/example.com",
        "https://forum.example.com/t/pain-point",
        "https://community.shopify.com/c/thread",
    ],
)
def test_social_forums_and_reviews_are_tier_d(url):
    assert rate(url) == "D"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reuters.com/technology/x",
        "https://www.bbc.co.uk/news/business",
        "https://english.ahram.org.eg/News/1.aspx",
        "https://www.mckinsey.com/featured-insights",
        "https://en.wikipedia.org/wiki/Freelancer",
    ],
)
def test_news_and_research_firms_are_tier_c(url):
    assert rate(url) == "C"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.freshbooks.com/pricing",
        "https://apps.apple.com/us/app/id123",
        "https://arxiv.org/abs/2401.00001",
        "https://go.com/",  # "go" counts as official only before a country code
        "https://notreddit.com/",  # suffix match is by whole labels, not by string
    ],
)
def test_everything_else_is_tier_b(url):
    assert rate(url) == "B"


def test_reason_names_the_matched_domain():
    tier, reason = rate_with_reason("https://www.reddit.com/r/freelance")
    assert tier == "D" and "reddit.com" in reason
    tier, reason = rate_with_reason("https://www.freshbooks.com/pricing")
    assert tier == "B" and "freshbooks.com" in reason


def test_hosts_are_case_insensitive():
    assert rate("HTTPS://WWW.REDDIT.COM/r/x") == "D"


@pytest.mark.parametrize("bad", ["", "reddit.com", "ftp://example.org/file", "https://", None])
def test_rejects_non_urls(bad):
    with pytest.raises(ValueError):
        rate(bad)
