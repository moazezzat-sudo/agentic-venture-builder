"""Researcher: one per business area, run in parallel (LangGraph Send).

Searches (top 3 results), rates each source A-D, and asks the model to turn
snippets into claims. URLs and tiers are attached in Python from the source
number the model gives, so the model can never invent a URL. Anything the
model states without a valid source becomes an ASSUMPTION.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from agents._common import SNIPPET_CHARS, ask_json, claims_markdown, cut, model_fields
from logger import log_action, write_output
from schemas import Claim

CRITERIA = ("problem_evidence", "market", "competition", "willingness_to_pay", "rules_risk")
# Words models use instead of the rubric's names (seen: "pricing" left price claims untagged).
CRITERION_ALIASES = {
    "pricing": "willingness_to_pay", "price": "willingness_to_pay", "prices": "willingness_to_pay",
    "willingness to pay": "willingness_to_pay", "wtp": "willingness_to_pay",
    "competitors": "competition", "competitor": "competition",
    "problem": "problem_evidence", "pain": "problem_evidence", "problem evidence": "problem_evidence",
    "market_size": "market", "market size": "market",
    "regulation": "rules_risk", "rules": "rules_risk", "risk": "rules_risk",
}
TIER_AB_ONLY = {"market": "a market figure", "rules_risk": "evidence on regulation"}
MAX_RESULTS = 3  # per search; an area runs its main query and, usually, one forum query
MAX_CLAIMS = 5

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


def plain_query(query: str) -> str:
    """Models write non-breaking hyphens and spaces ("time‑tracking"); search engines may not match them."""
    query = re.sub(r"[‐-―−]", "-", query)
    return " ".join(re.sub(r"[  -​ ]", " ", query).split())


STOPWORDS = {"site", "with", "that", "this", "from", "your", "their", "they", "have", "need", "needs", "into",
              "about", "what", "when", "which", "tools", "tool", "apps", "app", "software", "best", "online", "egypt"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in STOPWORDS}


def relevant(query: str, result: dict[str, Any]) -> bool:
    """False when a result shares no meaningful word with the query (search fallbacks sometimes return
    unrelated pages, such as encyclopedia articles about large companies). Plain word overlap, no model."""
    wanted = _words(re.sub(r"site:\S+", "", query))
    url = str(result.get("url", ""))
    if "wikipedia.org" in url:
        # Encyclopedia fallbacks match loosely (an article on a restaurant chain mentions "restaurants"):
        # count only words in the article's title.
        found = _words(str(result.get("title", "")))
    else:
        found = _words(f"{result.get('title', '')} {result.get('snippet', '')} {url}")
    return not wanted or bool(wanted & found) or bool({w[:5] for w in wanted} & {w[:5] for w in found})


# Engines that are not general web search (tools/search.py fallbacks). When only these answer,
# web search was unreachable for that query.
FALLBACK_ENGINES = ("wikipedia", "hn", "hackernews", "algolia")


def web_answered(results: list[dict[str, Any]]) -> bool:
    """True when a general web engine returned these results (results without an engine name count)."""
    return any(not str(r.get("engine") or "").lower().startswith(FALLBACK_ENGINES) for r in results)


def find_sources(query: str, web: Optional[list[bool]] = None,
                 dropped: Optional[list[dict[str, str]]] = None) -> list[dict[str, Any]]:
    """Search and rate. Returns [{i, title, url, snippet, tier}]. Skips ads, redirects, results unrelated
    to the query, and non-http(s) URLs. If `web` is a list, appends whether a web engine answered;
    if `dropped` is a list, appends {url, reason} for every result skipped here."""
    from tools.credibility import rate
    from tools.search import search

    def drop(url: str, reason: str) -> None:
        if dropped is not None:
            dropped.append({"url": url, "reason": reason})

    sources = []
    results = search(plain_query(query), max_results=MAX_RESULTS)[:MAX_RESULTS]
    if web is not None:
        web.append(web_answered(results))
    for r in results:
        url = str(r.get("url", ""))
        if AD_URL.match(url):
            drop(url, "advert or redirect link")
            continue
        if not relevant(query, r):
            drop(url, "keyword score 0: shares no word with the query")
            continue
        try:
            tier = rate(url)
        except ValueError:
            drop(url, "not an http(s) link")
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
        raw = str(item.get("criterion") or "").strip().lower()
        criterion = raw if raw in CRITERIA else CRITERION_ALIASES.get(raw)
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


def without_place(query: str, location: Any) -> str:
    """The query with the founder's location words removed ("Cairo, Egypt" -> drops cairo and egypt)."""
    places = {w.lower() for w in re.findall(r"[A-Za-z]+", str(location or "")) if len(w) > 2}
    kept = [w for w in query.split() if re.sub(r"[^a-z]", "", w.lower()) not in places]
    return " ".join(kept)


def gather_sources(area: dict[str, Any], location: Any = None, web: Optional[list[bool]] = None) -> list[dict[str, Any]]:
    """Top results for the area's query, plus its forum query (people describing the problem), if any.

    Each search gives at most MAX_RESULTS; duplicates are dropped and sources renumbered from 0.
    A main query naming a place often finds nothing; then it is tried once without the place.
    """
    found = find_sources(area["query"], web)
    broader = without_place(area["query"], location)
    if not found and broader and broader != area["query"]:
        found = find_sources(broader, web)
    if area.get("forum_query"):
        # Keep only results from the forum itself: a search fallback that ignores "site:" returns other pages.
        site = re.search(r"site:(\S+)", area["forum_query"])
        found += [dict(s, forum=True) for s in find_sources(area["forum_query"], web)
                  if not site or site.group(1).lower() in s["url"].lower()]
    sources, seen = [], set()
    for s in found:
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        sources.append({**s, "i": len(sources)})
    return sources


def research(area: dict[str, Any], brief: dict[str, Any], round_no: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Returns (claims, usage, sources). No model call when the search finds nothing."""
    web: list[bool] = []
    sources = gather_sources(area, brief.get("location"), web)
    usage: dict[str, Any] = {"tokens": 0, "cost": 0.0, "model": None, "parsed": None, "retried": False}
    claims: list[dict[str, Any]] = []
    if sources:
        payload = {
            "idea": cut(brief.get("idea"), 300), "location": brief.get("location"), "area": area["name"],
            "looking_for": area.get("focus", "problem"),
            "sources": [{k: s[k] for k in ("i", "tier", "title", "snippet")} | ({"forum": True} if s.get("forum") else {})
                        for s in sources],
        }
        data, usage = ask_json("researcher", payload, role="fast", temperature=0, expect=("claims",))
        claims = build_claims(data.get("claims"), sources, round_no)
    usage["web_search_ok"] = any(web)  # False: no web engine answered any of this area's searches
    return claims, usage, sources


def node(state: dict[str, Any]) -> dict[str, Any]:
    """Runs once per area. state is the Send payload: {research_area, brief, round}."""
    area, brief, round_no = state["research_area"], state["brief"], state.get("round", 1)
    claims, usage, sources = research(area, brief, round_no)
    if area.get("index") == 0:
        claims = country_facts(brief, round_no) + claims

    stubbed = _stubbed_tools()
    web_ok = usage.get("web_search_ok", True)
    log_action(
        agent="researcher", action="research_area" if sources else "research_area_no_results",
        sources=[s["url"] for s in sources], run_id=state.get("run_id"), round=round_no, **model_fields(usage),
        area=area["name"], query=area["query"], forum_query=area.get("forum_query"), stubbed_tools=stubbed,
        web_search_ok=web_ok,
    )
    src_lines = "\n".join(
        f"- tier {s['tier']}{' (forum)' if s.get('forum') else ''}: [{s['title'] or s['url']}]({s['url']})" for s in sources
    ) or "_The search returned no results._"
    forum = f"\n\nForum query: `{area['forum_query']}`" if area.get("forum_query") else ""
    write_output(1, 4, f"research {area['name']}", (
        f"# Phase 1, step 4: research on \"{area['name']}\" (round {round_no})\n\n"
        f"Query: `{area['query']}`{forum}\n\n## Sources\n\n{src_lines}\n\n## Claims\n\n{claims_markdown(claims)}\n"
    ), status="STUBBED" if stubbed else "Working")
    gaps = [] if web_ok else [{"round": round_no, "area": area["name"], "focus": area.get("focus", "problem")}]
    return {"claims": claims, "tokens": usage["tokens"], "search_gaps": gaps}


# ================================================================ evidence research (search plan)
# One researcher per evidence type runs that type's queries from agents/search_plan.py. A result is
# kept only if a plain keyword-overlap score passes AND the model flags it relevant; sources are
# deduplicated (a site counts once, each forum thread once); every query logs what it kept and dropped.

RELEVANCE_MIN = 0.25  # share of the idea's keywords a result must mention (our choice)
MAX_EVIDENCE_CLAIMS = 6  # per evidence type


def keyword_score(keywords_text: str, result: dict[str, Any]) -> float:
    """Share of the idea's keywords (at most 4 counted) found in a result's title, snippet or URL."""
    wanted = _words(keywords_text)
    if not wanted:
        return 1.0
    found = _words(f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}")
    hits = len(wanted & found) or len({w[:5] for w in wanted} & {w[:5] for w in found})
    return round(min(hits / min(len(wanted), 4), 1.0), 2)


def evidence_claim(etype: str, text: str, source: dict[str, Any], round_no: int, query: str) -> dict[str, Any]:
    from schemas import EVIDENCE_CRITERION

    text, tier, criterion = cut(text, 200), source["tier"], EVIDENCE_CRITERION[etype]
    if tier == "D":
        text = f"Community signal: {text}"
    if criterion in TIER_AB_ONLY and tier not in ("A", "B"):
        text, criterion = f"{text} (tier {tier}: not usable as {TIER_AB_ONLY[criterion]})", None
    claim = Claim(text=text, support="url", url=source["url"], tier=tier, area=criterion, agent="researcher")
    return claim.model_dump() | {"kind": etype, "round": round_no, "query": query}


def evidence_node(state: dict[str, Any]) -> dict[str, Any]:
    """Runs once per evidence type. state is the Send payload: {evidence_type, items, brief, round, run_id}."""
    from agents.search_plan import keywords
    from gates import source_key

    etype, items, brief = state["evidence_type"], state["items"], state["brief"]
    round_no, run_id = state.get("round", 1), state.get("run_id")
    if etype == "market":
        claims = [dict(c, kind="market") for c in country_facts(brief, round_no)]
        log_action(agent="researcher", action="market_indicators", run_id=run_id, round=round_no, model=None,
                   sources=[c["url"] for c in claims], evidence_type="market")
        return {"claims": claims, "tokens": 0, "search_gaps": []}

    k = keywords(brief)
    kw_text = " ".join([k["customer"], k["problem"], k["solution"], k["activity"]])
    web: list[bool] = []
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    per_query: dict[str, dict[str, list]] = {}
    for item in items:
        q = item["query"]
        log = per_query.setdefault(q, {"kept": [], "dropped": []})
        site = re.search(r"site:(\S+)", q)
        for s in find_sources(q, web, log["dropped"]):
            score = keyword_score(kw_text, s)
            if site and site.group(1).lower() not in s["url"].lower():
                log["dropped"].append({"url": s["url"], "reason": "not from the site asked for"})
            elif source_key(s["url"]) in seen:
                log["dropped"].append({"url": s["url"], "reason": "same source already kept"})
            elif score < RELEVANCE_MIN:
                log["dropped"].append({"url": s["url"], "reason": f"keyword score {score} < {RELEVANCE_MIN}"})
            else:
                seen.add(source_key(s["url"]))
                candidates.append({**s, "query": q, "score": score})

    usage: dict[str, Any] = {"tokens": 0, "cost": 0.0, "model": None, "parsed": None, "retried": False}
    verdicts: dict[int, dict[str, Any]] = {}
    if candidates:
        payload = {"evidence_type": etype,
                   "idea": {"customer": k["customer"], "problem": k["problem"], "solution": k["solution"],
                            "summary": cut(brief.get("discovery_summary") or brief.get("idea"), 300)},
                   "results": [{"i": i, "tier": c["tier"], "title": c["title"], "snippet": c["snippet"]}
                               for i, c in enumerate(candidates)]}
        data, usage = ask_json("evidence", payload, role="fast", max_tokens=900, temperature=0, expect=("results",))
        for r in data.get("results") or []:
            if isinstance(r, dict) and isinstance(r.get("i"), int) and not isinstance(r.get("i"), bool):
                verdicts[r["i"]] = r

    claims = []
    for i, c in enumerate(candidates):
        v = verdicts.get(i)
        if usage.get("parsed") and (not v or v.get("relevant") is not True):
            per_query[c["query"]]["dropped"].append({"url": c["url"], "reason": "the model judged it not relevant"})
            continue
        if not usage.get("parsed") and c["score"] < 0.5:  # no model verdict: only clear keyword matches
            per_query[c["query"]]["dropped"].append({"url": c["url"], "reason": "no model verdict and keyword score < 0.5"})
            continue
        if len(claims) >= MAX_EVIDENCE_CLAIMS:
            per_query[c["query"]]["dropped"].append({"url": c["url"], "reason": "evidence type already has enough sources"})
            continue
        text = (v or {}).get("claim") or c["title"]
        claims.append(evidence_claim(etype, str(text), c, round_no, c["query"]))
        per_query[c["query"]]["kept"].append(c["url"])

    # Anything the model states for a result number that doesn't exist has no source: an ASSUMPTION,
    # kept visible but never counted as evidence.
    for i, v in verdicts.items():
        if not 0 <= i < len(candidates) and v.get("relevant") is True and str(v.get("claim", "")).strip():
            claims.append(Claim(text=cut(v["claim"], 200), support="ASSUMPTION", agent="researcher").model_dump()
                          | {"kind": etype, "round": round_no, "query": None})

    for q, log in per_query.items():
        log_action(agent="researcher", action="search_query", run_id=run_id, round=round_no, model=None,
                   evidence_type=etype, query=q, sources=log["kept"], kept=len(log["kept"]),
                   dropped=log["dropped"])
    web_ok = any(web)
    log_action(agent="researcher", action="judge_relevance", run_id=run_id, round=round_no, evidence_type=etype,
               sources=[c["url"] for c in claims], candidates=len(candidates), kept=len(claims),
               web_search_ok=web_ok, **model_fields(usage))
    gaps = [] if web_ok else [{"round": round_no, "area": f"{etype} searches", "focus": etype}]
    return {"claims": claims, "tokens": usage.get("tokens", 0), "search_gaps": gaps}


def fan_out_plan(state: dict[str, Any]):
    """One researcher per evidence type in the plan, in parallel."""
    from langgraph.types import Send

    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in state.get("search_plan") or []:
        by_type.setdefault(item["evidence_type"], []).append(item)
    return [Send("researcher", {"evidence_type": t, "items": items, "brief": state["brief"],
                                "round": state.get("round", 1), "run_id": state.get("run_id")})
            for t, items in by_type.items()]


def summary_node(state: dict[str, Any]) -> dict[str, Any]:
    """After the parallel researchers: write the claims grouped by evidence type."""
    from agents.scorer import current_claims
    from schemas import EVIDENCE_TYPES

    claims = [c for c in current_claims(state) if c.get("round", 1) == state.get("round", 1)]
    order = {t: i for i, t in enumerate(EVIDENCE_TYPES)}
    claims.sort(key=lambda c: (order.get(c.get("kind"), 99), int(str(c.get("id", "C0"))[1:] or 0)))
    counts = {t: sum(1 for c in claims if c.get("kind") == t) for t in EVIDENCE_TYPES}
    rows = "\n".join(f"| {t} | {n} |" for t, n in counts.items())
    gaps = [g["focus"] for g in state.get("search_gaps") or [] if g.get("round") == state.get("round", 1)]
    log_action(agent="researcher", action="research_summary", run_id=state.get("run_id"), model=None,
               round=state.get("round", 1), claims=len(claims), by_type=counts, search_gaps=gaps)
    write_output(1, 3, "research", (
        f"# Phase 1, step 3: research, claims by evidence type (round {state.get('round', 1)})\n\n"
        "Each kept search result is one claim with its id, its source URL and the source's tier. Results that "
        "missed the keywords, repeated a source or that the model judged off-topic were dropped (see the "
        "search_query entries in decision_log.json).\n\n"
        "| Evidence type | Claims |\n|---|---|\n" + rows + "\n\n"
        + (f"Web search could not be reached for: {', '.join(gaps)}.\n\n" if gaps else "")
        + "## Claims\n\n" + claims_markdown(claims) + "\n"
    ))
    return {}
