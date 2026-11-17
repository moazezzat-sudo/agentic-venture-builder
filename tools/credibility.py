"""Source credibility tiers (PLAN.md section 3a).

Public interface (PLAN.md section 11, "Shared interfaces"):

    from tools.credibility import rate, rate_with_reason
    rate("https://data.worldbank.org/...")          # -> "A"
    rate_with_reason("https://www.reddit.com/r/x")   # -> ("D", "community site: reddit.com")

Tiers:
  A  official: government (.gov, .gov.<cc>), regulators, central banks, international bodies
  B  primary: the company's or author's own record (competitor sites, filings, papers, app stores)
  C  reputable secondary: established news outlets, research firms' public pages
  D  community: social media, forums, review sites; signs of pain or demand only, never numbers

What each tier may support (market size and regulation need A or B) is enforced
by the gates; this module only rates the source. Weights are schemas.TIER_WEIGHTS.

STUBBED: no domain rules yet. Every URL is rated "D", the weakest tier, so
nothing is overstated until the real rules land.
"""

from __future__ import annotations

from typing import Literal

STUBBED = True  # set to False once the domain rules replace the placeholder body

SourceTier = Literal["A", "B", "C", "D"]


def rate_with_reason(url: str) -> tuple[SourceTier, str]:
    """Return (tier, reason) for a source URL.

    STUBBED: always ("D", "STUBBED: ...").
    """
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("url must be an http(s) URL")
    return "D", "STUBBED: domain rules not built yet; rated at the weakest tier"


def rate(url: str) -> SourceTier:
    """Return the credibility tier "A" / "B" / "C" / "D" for a source URL."""
    return rate_with_reason(url)[0]


__all__ = ["rate", "rate_with_reason", "SourceTier", "STUBBED"]
