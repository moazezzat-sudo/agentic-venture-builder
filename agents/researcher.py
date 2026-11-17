"""Researcher: one per business area, run in parallel (LangGraph Send).

Searches (top 3 results), rates each source A-D, and asks the model to turn
snippets into claims. URLs and tiers are attached in Python from the source
number the model gives, so the model can never invent a URL. Anything the
model states without a valid source becomes an ASSUMPTION.
"""

from __future__ import annotations

import re
from typing import Any

from agents._common import SNIPPET_CHARS, ask_json, claims_markdown, cut
from logger import log_action, write_output
from schemas import Claim

CRITERIA = ("problem_evidence", "market", "competition", "willingness_to_pay", "rules_risk")
TIER_AB_ONLY = {"market": "a market figure", "rules_risk": "evidence on regulation"}
MAX_RESULTS = 3
MAX_CLAIMS = 4

# ISO codes for the World Bank lookup, matched as whole words in brief["location"].
COUNTRY_CODES = {
    "egypt": "EG", "saudi arabia": "SA", "united arab emirates": "AE", "uae": "AE", "jordan": "JO",
    "morocco": "MA", "tunisia": "TN", "kenya": "KE", "nigeria": "NG", "south africa": "ZA",
    "india": "IN", "pakistan": "PK", "indonesia": "ID", "turkey": "TR", "germany": "DE",
    "france": "FR", "united kingdom": "GB", "uk": "GB", "united states": "US", "usa": "US",
    "canada": "CA", "brazil": "BR", "mexico": "MX",
}


def _stubbed_tools() -> list[str]:
    from tools import credibility, search, worldbank

    return [m.__name__ for m in (search, credibility, worldbank) if getattr(m, "STUBBED", False)]


# Search-engine ads and click redirects: not a source anyone can cite or check.
AD_URL = re.compile(
    r"^https?://([^/]*\.)?(bing\.com/aclick|google\.[a-z.]+/aclk|googleadservices\.com|doubleclick\.net"
    r"|duckduckgo\.com/y\.js|r\.search\.yahoo\.com)", re.I,
)


def find_sources(query: str) -> list[dict[str, Any]]:
    """Search and rate. Returns [{i, title, url, snippet, tier}]. Skips ads, redirects and non-http(s) URLs."""
    from tools.credibility import rate
    from tools.search import search

    sources = []
    for r in search(query, max_results=MAX_RESULTS)[:MAX_RESULTS]:
        url = str(r.get("url", ""))
        if AD_URL.match(url):
            continue
        try:
            tier = rate(url)
        except ValueError:
            continue
        sources.append({"i": len(sources), "title": cut(r.get("title"), 120), "url": url,
                        "snippet": cut(r.get("snippet"), SNIPPET_CHARS), "tier": tier})
    return sources


def country_facts(brief: dict[str, Any], round_no: int) -> list[dict[str, Any]]:
    """World Bank figures for the founder's country, as tier A claims. No model involved."""
    from tools.worldbank import INDICATORS, INTERNET_USERS_PCT, POPULATION, indicator

    location = str(brief.get("location") or "").lower()
    code = next((c for name, c in COUNTRY_CODES.items() if re.search(rf"\b{re.escape(name)}\b", location)), None)
    if not code:
        return []
    facts = []
    for ind in (POPULATION, INTERNET_USERS_PCT):
        value = indicator(code, ind)
        if value.get("value") is None:
            continue
        facts.append(Claim(
            text=f"{INDICATORS[ind]} in {code}, {value['year']}: {value['value']:,.1f} (World Bank).",
            support="url", url=value["source_url"], tier="A", area="market", agent="researcher",
        ).model_dump() | {"round": round_no})
    return facts


def build_claims(raw: Any, sources: list[dict[str, Any]], round_no: int) -> list[dict[str, Any]]:
    """Model output -> Claim dicts. Invalid source numbers become ASSUMPTIONs."""
    claims = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_CLAIMS]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        text = cut(item["text"], 200)
        criterion = item.get("criterion") if item.get("criterion") in CRITERIA else None
        src = item.get("source")
        source = sources[src] if isinstance(src, int) and not isinstance(src, bool) and 0 <= src < len(sources) else None
        if source is None:
            claim = Claim(text=text, support="ASSUMPTION", area=criterion, agent="researcher")
        else:
            tier = source["tier"]
            if tier == "D":
                text = f"Community signal: {text}"
            if criterion in TIER_AB_ONLY and tier not in ("A", "B"):
                # Market size and regulation need tier A or B (PLAN.md 3a); keep it only as context.
                text = f"{text} (tier {tier}: not usable as {TIER_AB_ONLY[criterion]})"
                criterion = None
            claim = Claim(text=text, support="url", url=source["url"], tier=tier, area=criterion, agent="researcher")
        claims.append(claim.model_dump() | {"round": round_no})
    return claims


def research(area: dict[str, Any], brief: dict[str, Any], round_no: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Returns (claims, usage, sources). No model call when the search finds nothing."""
    sources = find_sources(area["query"])
    usage: dict[str, Any] = {"tokens": 0, "cost": 0.0, "model": None, "parsed": None}
    claims: list[dict[str, Any]] = []
    if sources:
        payload = {
            "idea": cut(brief.get("idea"), 300), "location": brief.get("location"), "area": area["name"],
            "looking_for": area.get("focus", "problem"),
            "sources": [{k: s[k] for k in ("i", "tier", "title", "snippet")} for s in sources],
        }
        data, usage = ask_json("researcher", payload, role="fast", max_tokens=450)
        claims = build_claims(data.get("claims"), sources, round_no)
    return claims, usage, sources


def node(state: dict[str, Any]) -> dict[str, Any]:
    """Runs once per area. state is the Send payload: {research_area, brief, round}."""
    area, brief, round_no = state["research_area"], state["brief"], state.get("round", 1)
    claims, usage, sources = research(area, brief, round_no)
    if area.get("index") == 0:
        claims = country_facts(brief, round_no) + claims

    stubbed = _stubbed_tools()
    log_action(
        agent="researcher", action="research_area" if sources else "research_area_no_results",
        sources=[s["url"] for s in sources], model=usage["model"], cost=usage["cost"], tokens=usage["tokens"],
        area=area["name"], query=area["query"], round=round_no, stubbed_tools=stubbed,
    )
    src_lines = "\n".join(f"- tier {s['tier']}: [{s['title'] or s['url']}]({s['url']})" for s in sources) or "_The search returned no results._"
    write_output(1, 4, f"research {area['name']}", (
        f"# Phase 1, step 4: research on \"{area['name']}\" (round {round_no})\n\n"
        f"Query: `{area['query']}`\n\n## Sources\n\n{src_lines}\n\n## Claims\n\n{claims_markdown(claims)}\n"
    ), status="STUBBED" if stubbed else "Working")
    return {"claims": claims, "tokens": usage["tokens"]}
