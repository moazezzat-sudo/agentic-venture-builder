"""Source credibility tiers (PLAN.md section 3a).

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.credibility import rate, rate_with_reason
    rate("https://data.worldbank.org/...")          # -> "A"
    rate_with_reason("https://www.reddit.com/r/x")   # -> ("D", "community site or forum: reddit.com")

Tiers:
  A  official: government (.gov, gov.<cc>), regulators, central banks, international bodies
  B  primary: the company's or author's own record (competitor sites, filings, papers, app stores)
  C  reputable secondary: established news outlets, research firms' public pages
  D  community: social media, forums, review sites; signs of pain or demand only, never numbers

Rules are applied in that order of checks: official, then community, then news,
then the default. A domain that is in no list is rated B (a company's or author's
own site), and the reason says so, so the app can show why.

What each tier may support (market size and regulation need A or B) is enforced
by the gates; this module only rates the source. Weights are schemas.TIER_WEIGHTS.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

STUBBED = False

SourceTier = Literal["A", "B", "C", "D"]

# Top-level domains reserved for governments, the military and international treaty bodies.
OFFICIAL_TLDS = frozenset({"gov", "mil", "int"})
# Second-level labels used by governments under a country code: gov.uk, gov.eg, gob.mx, gouv.fr, go.jp.
OFFICIAL_SECOND_LEVEL = frozenset({"gov", "gob", "gouv", "go", "govt", "mil", "admin"})

OFFICIAL_DOMAINS = frozenset({
    # International bodies
    "worldbank.org", "imf.org", "oecd.org", "un.org", "unctad.org", "undp.org", "unesco.org",
    "unicef.org", "wto.org", "ilo.org", "itu.int", "who.int", "bis.org", "europa.eu", "afdb.org",
    "adb.org", "iadb.org", "ebrd.com",
    # Central banks and regulators outside government domains
    "cbe.org.eg", "bankofengland.co.uk", "centralbank.ae", "rbi.org.in",
})

COMMUNITY_DOMAINS = frozenset({
    # Social media
    "reddit.com", "redd.it", "facebook.com", "fb.com", "x.com", "twitter.com", "instagram.com",
    "tiktok.com", "linkedin.com", "youtube.com", "youtu.be", "threads.net", "pinterest.com",
    "t.me", "telegram.me", "discord.com", "discord.gg", "snapchat.com", "whatsapp.com",
    # Forums and Q&A
    "quora.com", "stackexchange.com", "stackoverflow.com", "news.ycombinator.com",
    "indiehackers.com", "producthunt.com", "medium.com", "substack.com", "tumblr.com",
    # Review sites
    "trustpilot.com", "g2.com", "capterra.com", "yelp.com", "tripadvisor.com", "glassdoor.com",
    "sitejabber.com", "getapp.com",
})
# Hostname prefixes that mark a forum or community section of any site.
COMMUNITY_SUBDOMAINS = ("forum.", "forums.", "community.", "discuss.", "answers.", "groups.")

NEWS_AND_RESEARCH_DOMAINS = frozenset({
    # International news
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com", "wsj.com", "ft.com",
    "bloomberg.com", "economist.com", "theguardian.com", "cnbc.com", "cnn.com", "aljazeera.com",
    "aljazeera.net", "forbes.com", "fortune.com", "businessinsider.com", "techcrunch.com",
    "theverge.com", "wired.com", "arstechnica.com", "axios.com", "washingtonpost.com",
    "npr.org", "dw.com", "france24.com", "time.com", "venturebeat.com", "restofworld.org",
    # Egypt and the region
    "ahram.org.eg", "english.ahram.org.eg", "egypttoday.com", "dailynewsegypt.com",
    "enterprise.press", "madamasr.com", "wamda.com", "magnitt.com", "arabnews.com",
    "thenationalnews.com", "zawya.com", "egyptindependent.com",
    # Research firms' and consultancies' public pages
    "mckinsey.com", "bcg.com", "bain.com", "deloitte.com", "pwc.com", "ey.com", "kpmg.com",
    "gartner.com", "forrester.com", "idc.com", "statista.com", "cbinsights.com",
    "pewresearch.org", "gsma.com", "datareportal.com",
    # Public summaries
    "wikipedia.org",
})


def _host(url: str) -> str:
    if not isinstance(url, str) or not url.strip().lower().startswith(("http://", "https://")):
        raise ValueError("url must be an http(s) URL")
    host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError(f"url has no host: {url!r}")
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domains: frozenset[str]) -> str | None:
    """Return the listed domain that host is, or is a subdomain of."""
    labels = host.split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        if candidate in domains:
            return candidate
    return None


def _is_official_suffix(host: str) -> bool:
    labels = host.split(".")
    if labels[-1] in OFFICIAL_TLDS:
        return True
    # gov.uk, gov.eg, gob.mx, go.jp: an official label right before a two-letter country code
    return len(labels) >= 2 and len(labels[-1]) == 2 and labels[-2] in OFFICIAL_SECOND_LEVEL


def rate_with_reason(url: str) -> tuple[SourceTier, str]:
    """Return (tier, reason) for a source URL. Raises ValueError for anything but an http(s) URL."""
    host = _host(url)
    if _is_official_suffix(host):
        return "A", f"official government or international domain: {host}"
    if match := _matches(host, OFFICIAL_DOMAINS):
        return "A", f"official body (international organisation, central bank or regulator): {match}"
    if match := _matches(host, COMMUNITY_DOMAINS):
        return "D", f"community site or forum: {match}"
    if host.startswith(COMMUNITY_SUBDOMAINS):
        return "D", f"forum or community section: {host}"
    if match := _matches(host, NEWS_AND_RESEARCH_DOMAINS):
        return "C", f"established news outlet or research firm's public page: {match}"
    return "B", f"not in any list; treated as a primary source (the company's or author's own site): {host}"


def rate(url: str) -> SourceTier:
    """Return the credibility tier "A" / "B" / "C" / "D" for a source URL."""
    return rate_with_reason(url)[0]


__all__ = ["rate", "rate_with_reason", "SourceTier", "STUBBED"]
