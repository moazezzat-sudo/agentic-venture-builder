"""Search plan: which queries to run for which kind of evidence, built in plain Python.

    build_search_plan(briefcase) -> [{"evidence_type", "query", "why"}]   # at most MAX_QUERIES

Evidence types: pain | competitors | pricing | market | regulation. Keywords come from the confirmed
brief (discovery keywords when present, otherwise words taken from the confirmed understanding and
the idea); templates per type turn them into queries. Market evidence is World Bank indicators for
the country, not a web search. Regulation is searched only when the activity touches a regulated
area (payments, personal data, children, health, ...).
"""

from __future__ import annotations

import re
from typing import Any

from agents._common import cut
from logger import log_action, write_output

MAX_QUERIES = 12
STOP = {"a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "that", "who", "their", "they",
        "them", "app", "apps", "web", "website", "platform", "tool", "tools", "online", "lets", "let", "allows",
        "helps", "people", "users", "using", "use", "via", "into", "from", "your", "our", "is", "are", "be", "can",
        "unclear", "not", "stated", "yet", "it", "this", "which", "would", "will", "get", "make", "have", "has",
        "own", "there", "about", "when", "what"}
ARABIC_COUNTRIES = {"EG", "SA", "AE", "JO", "MA", "TN"}
GOV_DOMAIN = {"EG": "gov.eg", "SA": "gov.sa", "AE": "gov.ae", "JO": "gov.jo", "MA": "gov.ma", "TN": "gov.tn",
              "KE": "go.ke", "NG": "gov.ng", "ZA": "gov.za", "IN": "gov.in", "PK": "gov.pk", "ID": "go.id",
              "TR": "gov.tr", "GB": "gov.uk", "US": "gov", "CA": "gc.ca", "DE": "bund.de", "FR": "gouv.fr"}
REGULATED = re.compile(
    r"\b(pay|payment|payments|money|wallet|card|bank|loan|personal data|data|privacy|children|child|kids|minor|minors|"
    r"school|students|health|medical|food|delivery|transport|ride|video|videos|recording|record|film|filming|photo|photos|camera|"
    r"location|tracking|insurance|licen[cs]e|tax|employment|hiring|gambling|betting)\b", re.I)


def words(text: Any, n: int = 4, skip: Any = "") -> str:
    """The first n content words of a text, leaving out words in `skip`: a plain keyword phrase for a search."""
    skipped = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", str(skip or ""))}
    found: list[str] = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", str(text or "")):
        if w.lower() not in STOP and len(w) > 2 and w.lower() not in skipped and w.lower() not in {f.lower() for f in found}:
            found.append(w)
    return " ".join(found[:n])


def country(brief: dict[str, Any]) -> tuple[str, str]:
    """(country name, ISO code) from the brief's location, or ("", "")."""
    from agents.researcher import COUNTRY_CODES

    location = str(brief.get("location") or "").lower()
    for name, code in COUNTRY_CODES.items():
        if re.search(rf"\b{re.escape(name)}\b", location):
            return name.title() if len(name) > 3 else name.upper(), code
    return "", ""


def keywords(brief: dict[str, Any]) -> dict[str, Any]:
    """Short keyword phrases from the confirmed brief."""
    kw = dict(brief.get("keywords") or {})
    understood = brief.get("confirmed_understanding") or {}
    clean = {k: re.sub(r"^\s*Unclear:\s*", "", str(v)) for k, v in understood.items()}
    place = brief.get("location") or ""
    customer = kw.get("customer") or words(clean.get("customer") or brief.get("target_market"), 3, place)
    # Without discovery keywords: the idea's own words, minus the customer and the place.
    solution = kw.get("solution") or words(brief.get("idea"), 4, f"{customer} {place}")
    problem = kw.get("problem") or words(clean.get("problem"), 4, place) or solution
    activity = kw.get("activity") or solution
    name, code = country(brief)
    return {"customer": cut(customer, 50), "problem": cut(problem, 60), "solution": cut(solution, 50),
            "activity": cut(activity, 40), "country": name, "cc": code,
            "location": words(brief.get("location"), 2), "arabic": list(kw.get("arabic") or [])[:5]}


def regulation_relevant(brief: dict[str, Any]) -> bool:
    understood = " ".join(str(v) for v in (brief.get("confirmed_understanding") or {}).values())
    activity = (brief.get("keywords") or {}).get("activity", "")
    return bool(REGULATED.search(f"{brief.get('idea', '')} {understood} {activity}"))


def build_search_plan(briefcase: dict[str, Any]) -> list[dict[str, str]]:
    brief = briefcase.get("brief") or {}
    k = keywords(brief)
    loc = k["location"] or k["country"]
    plan: list[dict[str, str]] = []

    def add(etype: str, query: str, why: str) -> None:
        query = " ".join(query.split())
        if query and query.lower() not in {p["query"].lower() for p in plan}:
            plan.append({"evidence_type": etype, "query": query, "why": why})

    # Extra queries the coach asked for after a repeat or pivot come first: they target the missing evidence.
    for q in (briefcase.get("coach_notes") or {}).get("search") or []:
        if isinstance(q, dict) and q.get("evidence_type") in ("pain", "competitors", "pricing", "regulation"):
            add(q["evidence_type"], cut(q.get("query"), 120), "Asked for by the coach to close an evidence gap.")

    add("pain", f"{k['customer']} {words(k['problem'], 5, k['customer'])} {words(loc, 2, k['customer'])}",
        "People in the target market describing the problem.")
    add("pain", f"{k['problem']} site:reddit.com", "Forum threads where people describe the problem in their own words.")
    add("pain", f"{k['customer']} {k['problem']} site:news.ycombinator.com", "A second, independent forum.")
    if k["arabic"] and k["cc"] in ARABIC_COUNTRIES:
        add("pain", " ".join(k["arabic"]), "The same problem in Arabic, the language the customers search in.")
    add("competitors", f"{k['solution']} app {loc}", "Existing products that already solve it, in the launch market.")
    add("competitors", f"{k['solution']} site:play.google.com", "Mobile apps that already do this.")
    add("pricing", f"{k['solution']} price {k['country'] or loc}", "What people pay for this kind of product today.")
    if k["cc"]:
        add("market", f"World Bank indicators for {k['cc']}: population, internet users",
            "Official (tier A) size of the reachable market.")
    if regulation_relevant(brief) and k["cc"] in GOV_DOMAIN:
        add("regulation", f"{k['activity']} regulation site:{GOV_DOMAIN[k['cc']]}",
            "The activity touches a regulated area; official rules for the country.")
    return plan[:MAX_QUERIES]


def node(state: dict[str, Any]) -> dict[str, Any]:
    plan = build_search_plan(state)
    k = keywords(state["brief"])
    log_action(agent="search_plan", action="build_search_plan", model=None, run_id=state.get("run_id"),
               round=state.get("round", 1), queries=len(plan), evidence_types=sorted({p["evidence_type"] for p in plan}))
    rows = "\n".join(f"| {i + 1} | {p['evidence_type']} | `{p['query']}` | {p['why']} |" for i, p in enumerate(plan))
    kw = ", ".join(f"{name}: {k[name]}" for name in ("customer", "problem", "solution", "activity", "country") if k[name])
    write_output(1, 2, "search plan", (
        f"# Phase 1, step 2: search plan (round {state.get('round', 1)})\n\n"
        f"Built in Python from the confirmed brief. Keywords: {kw}."
        + (f" Arabic: {', '.join(k['arabic'])}." if k["arabic"] else "") + "\n\n"
        "| # | Evidence type | Query | Why |\n|---|---|---|---|\n" + rows + "\n\n"
        f"At most {MAX_QUERIES} queries. Market figures come from the World Bank API, not a web search.\n"
    ))
    return {"search_plan": plan}
