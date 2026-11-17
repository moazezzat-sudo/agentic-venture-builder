"""Gate decision rules in plain Python. The model never decides the outcome.

    from gates import evaluate_gate_1
    result = evaluate_gate_1(scores, claims, violations=[])   # -> schemas.GateResult

The scorer agent proposes a 0-4 score per rubric criterion. Everything after
that (weighted total, go/repeat/pivot/stop, caps and hard stops) is here, read
from rubric.yaml (PLAN.md sections 3b and 4).

Order of checks (section 4):
  1. Guardrail violations          -> stop
  2. A 0 on a stop_if_zero criterion (problem evidence, competition, rules and risk) -> stop
  3. "Mostly ASSUMPTIONs"          -> stop
  4. Weighted total: >= go_min go; < stop_below stop; between -> pivot or repeat
  5. Caps: more than half the claims unsourced, or a missed Gate 1 target,
     turns go into repeat (the recommendation can't be better than repeat).
  6. Rewritable violations (in our own drafts) turn anything but stop into repeat:
     the drafts are rewritten in the next round.

The founder then approves or overrides; that is approval.record_decision, not here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union
from urllib.parse import urlparse

import yaml

from config import ROOT_DIR
from schemas import Claim, GateResult, Outcome

RUBRIC_PATH = ROOT_DIR / "rubric.yaml"

ClaimLike = Union[Claim, Mapping[str, Any]]


# ---------------------------------------------------------------- rubric

@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    rubric = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_rubric(rubric)
    return rubric


def load_rubric(path: Optional[Path] = None) -> dict[str, Any]:
    """Read and check rubric.yaml (cached)."""
    return _load(str(path or RUBRIC_PATH))


def validate_rubric(rubric: Mapping[str, Any]) -> None:
    """Raise ValueError if the rubric is inconsistent."""
    criteria = rubric.get("criteria") or {}
    if not criteria:
        raise ValueError("rubric has no criteria")
    total = sum(float(c["weight"]) for c in criteria.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"rubric weights must sum to 1.0, got {total}")
    d = rubric["decision"]
    if not d["stop_below"] < d["go_min"]:
        raise ValueError("decision.stop_below must be below decision.go_min")
    for name in d.get("stop_if_zero", []):
        if name not in criteria:
            raise ValueError(f"stop_if_zero names an unknown criterion: {name}")


def criteria_names(rubric: Optional[Mapping[str, Any]] = None) -> list[str]:
    rubric = rubric or load_rubric()
    return list(rubric["criteria"])


# ---------------------------------------------------------------- scores

def check_scores(scores: Mapping[str, float], rubric: Optional[Mapping[str, Any]] = None) -> dict[str, float]:
    """Every criterion must have a number within the scale. Missing scores are an error, never a default."""
    rubric = rubric or load_rubric()
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    names = criteria_names(rubric)
    missing = [n for n in names if n not in scores]
    unknown = [n for n in scores if n not in names]
    if missing or unknown:
        raise ValueError(f"scores do not match the rubric: missing={missing} unknown={unknown}")
    clean: dict[str, float] = {}
    for name in names:
        value = scores[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"score for {name} must be a number, got {value!r}")
        if not lo <= value <= hi:
            raise ValueError(f"score for {name} must be between {lo} and {hi}, got {value}")
        clean[name] = float(value)
    return clean


def weighted_total(scores: Mapping[str, float], rubric: Optional[Mapping[str, Any]] = None) -> float:
    """Sum of weight x score over all criteria, on the 0-4 scale, rounded to 2 decimals."""
    rubric = rubric or load_rubric()
    clean = check_scores(scores, rubric)
    total = sum(float(c["weight"]) * clean[name] for name, c in rubric["criteria"].items())
    return round(total, 2)


def outcome_from_total(total: float, problem_score: float, rubric: Optional[Mapping[str, Any]] = None) -> Outcome:
    """Map a weighted total to an outcome. In the middle band: pivot if the pain is real, else repeat."""
    d = (rubric or load_rubric())["decision"]
    if total >= d["go_min"]:
        return "go"
    if total < d["stop_below"]:
        return "stop"
    return "pivot" if problem_score >= d["pivot_problem_min"] else "repeat"


# ---------------------------------------------------------------- claims

def _as_claim(claim: ClaimLike) -> Claim:
    return claim if isinstance(claim, Claim) else Claim(**dict(claim))


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host[4:] if host.startswith(("old.", "new.")) and host.endswith("reddit.com") else host


# On these sites each thread is written by different people, so each thread is an independent source
# (PLAN.md section 4: "at least 3 independent source URLs"). Everywhere else one site counts once,
# so a single vendor blog can't count several times.
FORUM_DOMAINS = ("reddit.com", "news.ycombinator.com", "stackexchange.com", "stackoverflow.com", "quora.com")


def source_key(url: str) -> str:
    """What makes a pain source independent: the site, or the thread on a forum."""
    domain = _domain(url)
    if not any(domain == f or domain.endswith("." + f) for f in FORUM_DOMAINS):
        return domain
    parts = urlparse(url)
    path = "/".join(p for p in parts.path.lower().split("/") if p)
    if domain.endswith("reddit.com"):
        segs = path.split("/")  # r/<sub>/comments/<id>/<slug>: the id names the thread
        path = "/".join(segs[:4]) if len(segs) >= 4 and segs[2] == "comments" else path
    query = f"?{parts.query}" if domain == "news.ycombinator.com" and parts.query else ""
    return f"{domain}/{path}{query}"


def claim_stats(claims: Iterable[ClaimLike]) -> dict[str, Any]:
    """Counts the gate needs. 'Sourced' means a URL or our own evidence; ASSUMPTION is unsourced.

    No claims at all counts as fully unsourced (there is no evidence).
    """
    parsed = [_as_claim(c) for c in claims]
    total = len(parsed)
    sourced = sum(1 for c in parsed if c.support in ("url", "evidence"))
    # Name kept for the app and tests: the independent pain sources (a site, or a forum thread).
    pain_domains = sorted({
        source_key(c.url) for c in parsed
        if c.support == "url" and c.url and c.area == "problem_evidence"
    })
    return {
        "total": total,
        "sourced": sourced,
        "unsourced": total - sourced,
        "sourced_share": (sourced / total) if total else 0.0,
        "unsourced_share": ((total - sourced) / total) if total else 1.0,
        "pain_domains": pain_domains,
    }


# ---------------------------------------------------------------- gate 1

def evaluate_gate_1(
    scores: Mapping[str, float],
    claims: Iterable[ClaimLike],
    violations: Optional[Iterable[str]] = None,
    rubric: Optional[Mapping[str, Any]] = None,
    rewritable_violations: Optional[Iterable[str]] = None,
    evidence_gaps: Optional[Iterable[str]] = None,
) -> GateResult:
    """Recommend go / repeat / pivot / stop for Gate 1 (Discover), with reasons the founder can read.

    violations: guardrail hits that stop the idea (banned category, the founder's own text).
    rewritable_violations: hits in drafts our agents wrote; they can be rewritten, so -> repeat.
    evidence_gaps: areas where web search could not be reached (no web engine answered). A stop that
        rests only on missing evidence then becomes repeat: no data is not evidence against the idea.
        Stops from guardrails, a free competitor or rules and risk stay stop.
    """
    gaps = [g for g in (evidence_gaps or []) if g]
    if gaps:
        result = evaluate_gate_1(scores, claims, violations, rubric, rewritable_violations)
        clean = check_scores(scores, rubric or load_rubric())
        evidence_stop = (
            result.recommendation == "stop" and not [v for v in (violations or []) if v]
            and clean["competition"] != 0 and clean["rules_risk"] != 0
            # No pain evidence is held at repeat only if the pain searches themselves failed.
            and not (clean["problem_evidence"] == 0 and not any("pain" in g or "problem" in g for g in gaps))
        )
        if evidence_stop:
            reasons = [*result.reasons,
                       "Held at repeat instead of stop: web search returned nothing usable for "
                       + ", ".join(gaps) + ", so the evidence could not be gathered. Run again when search works."]
            return result.model_copy(update={"recommendation": "repeat", "reasons": reasons})
        return result.model_copy(update={"reasons": [*result.reasons, "Web search returned nothing usable for "
                                                     + ", ".join(gaps) + "."]})
    rubric = rubric or load_rubric()
    d, g1 = rubric["decision"], rubric["gate_1"]
    clean = check_scores(scores, rubric)
    total = weighted_total(clean, rubric)
    stats = claim_stats(claims)
    violations = [v for v in (violations or []) if v]
    summary = (
        f"Weighted score {total:.2f} of 4. {stats['sourced']} of {stats['total']} claims sourced "
        f"({stats['sourced_share']:.0%}). Independent pain sources: {len(stats['pain_domains'])}."
    )

    def result(outcome: Outcome, reasons: list[str]) -> GateResult:
        return GateResult(
            phase=1, gate="gate_1", recommendation=outcome, reasons=reasons,
            target=" ".join(str(g1["target"]).split()), evidence_summary=summary, score=total,
        )

    # 1. Guardrails
    if violations:
        return result("stop", [f"Guardrail: {v}" for v in violations])

    # 2. Hard zeros
    zeros = [n for n in d["stop_if_zero"] if clean[n] == 0]
    if zeros:
        return result("stop", [f"{n} scored 0, which stops the idea whatever the total." for n in zeros])

    # 3. Mostly assumptions
    if stats["unsourced_share"] >= d["stop_unsourced_share"]:
        return result("stop", [
            f"{stats['unsourced_share']:.0%} of claims are ASSUMPTIONs or unsourced "
            f"(stop at {d['stop_unsourced_share']:.0%} or more)."
        ])

    # 4. Total
    outcome = outcome_from_total(total, clean["problem_evidence"], rubric)
    reasons: list[str] = []
    if outcome == "stop":
        reasons.append(f"Weighted score {total:.2f} is below {d['stop_below']}.")
    elif outcome == "go":
        reasons.append(f"Weighted score {total:.2f} meets {d['go_min']}.")
    elif outcome == "pivot":
        reasons.append(
            f"Weighted score {total:.2f} is between {d['stop_below']} and {d['go_min']}; "
            f"the pain looks real (problem evidence {clean['problem_evidence']:g}) but the idea as framed scores low."
        )
    else:
        reasons.append(
            f"Weighted score {total:.2f} is between {d['stop_below']} and {d['go_min']}; "
            f"problem evidence ({clean['problem_evidence']:g}) is too thin, so more evidence is needed."
        )
    weakest = sorted(clean.items(), key=lambda kv: kv[1])[:2]
    if outcome != "go":
        reasons.append("Weakest criteria: " + ", ".join(f"{n} {s:g}" for n, s in weakest) + ".")

    # 5. Caps: go can be held back to repeat
    misses: list[str] = []
    if stats["unsourced_share"] > d["cap_unsourced_share"]:
        misses.append(f"more than half the claims are unsourced ({stats['unsourced_share']:.0%})")
    if len(stats["pain_domains"]) < g1["min_pain_sources"]:
        misses.append(
            f"only {len(stats['pain_domains'])} independent source(s) show the pain "
            f"(target {g1['min_pain_sources']})"
        )
    if stats["sourced_share"] < g1["min_sourced_share"]:
        misses.append(f"{stats['sourced_share']:.0%} of claims sourced (target {g1['min_sourced_share']:.0%})")
    if clean["founder_fit"] < g1["min_founder_fit"]:
        misses.append(f"founder fit {clean['founder_fit']:g} is below {g1['min_founder_fit']}")
    if misses:
        if outcome == "go":
            outcome = "repeat"
            reasons.append("Held at repeat because the Gate 1 target is not met.")
        reasons.extend(f"Target missed: {m}." for m in misses)

    # 6. Draft violations: rewrite and run again
    rewritable = [v for v in (rewritable_violations or []) if v]
    if rewritable:
        if outcome != "stop":
            outcome = "repeat"
            reasons.append("Held at repeat: a draft breaks a guardrail and must be rewritten.")
        reasons.extend(f"Guardrail (draft): {v}" for v in rewritable)

    return result(outcome, reasons)


__all__ = [
    "load_rubric", "validate_rubric", "criteria_names", "check_scores", "weighted_total",
    "outcome_from_total", "claim_stats", "evaluate_gate_1", "RUBRIC_PATH", "source_key",
    "PHASE_GATES", "evaluate_gate_2", "evaluate_gate_3_plan", "evaluate_gate_3", "evaluate_gate_4",
    "evaluate_gate_5", "evaluate_gate_6",
]


def evaluate_scoring_incomplete(missing: Iterable[str], gate: str = "gate_1",
                                rubric: Optional[Mapping[str, Any]] = None) -> GateResult:
    """The scorer did not return every criterion: repeat, never a 0 for what is missing."""
    missing = [m for m in missing if m]
    g1 = (rubric or load_rubric())["gate_1"]
    return GateResult(
        phase=1, gate=gate, recommendation="repeat",
        reasons=[f"Scoring incomplete: no valid score for {', '.join(missing)}. Run the scoring again; "
                 "missing scores are never counted as 0."],
        target=" ".join(str(g1["target"]).split()), evidence_summary="Scoring incomplete.", score=None,
    )


# ================================================================ Phases 2-6 gates
# PLAN.md section 4. Each gate checks the phase's draft against the target written before the phase,
# in plain Python. Guardrail hits left in a draft (after the agent's one rewrite) -> repeat.

PHASE_GATES: dict[str, dict[str, Any]] = {
    "gate_2": {"phase": 2, "target": "The founder sets a waitlist target before the test and enters the real sign-up count. "
                                     "Stop when the real count is far below the target (under a quarter of it)."},
    "gate_3_plan": {"phase": 3, "target": "A build plan the founder accepts: stack, database, flows and MVP features that "
                                          "test the riskiest assumption; no guardrail hits."},
    "gate_3": {"phase": 3, "target": "Smoke tests pass and user docs exist: the files exist and are not empty, the HTML "
                                     "parses, and every text passes the guardrails."},
    "gate_4": {"phase": 4, "target": "The price has a stated basis; terms, privacy and refund drafts exist; no prohibited claims."},
    "gate_5": {"phase": 5, "target": "The founder approves each post and the store page; the MOCKED delivery test passes."},
    "gate_6": {"phase": 6, "target": "A persevere-or-pivot memo backed by the logged metrics, against the targets set at Gate 2."},
}
FAR_BELOW_SHARE = 0.25  # "Real count far below target (e.g. 12 of 100)" -> stop. Our choice for "far".


def _phase_result(gate: str, outcome: Outcome, reasons: list[str], summary: str) -> GateResult:
    spec = PHASE_GATES[gate]
    return GateResult(phase=spec["phase"], gate=gate, recommendation=outcome, reasons=reasons,
                      target=spec["target"], evidence_summary=summary)


def _draft_violations(draft: Mapping[str, Any]) -> list[str]:
    return [f"{v.get('rule')}: \"{v.get('excerpt', '')}\"" for v in (draft.get("violations") or []) if isinstance(v, Mapping)]


def _with_violations(outcome: Outcome, reasons: list[str], draft: Mapping[str, Any]) -> tuple[Outcome, list[str]]:
    hits = _draft_violations(draft)
    if hits:
        reasons = [*reasons, *(f"Guardrail (draft): {h}" for h in hits)]
        if outcome != "stop":
            outcome = "repeat"
            reasons.append("Held at repeat: the draft still breaks a guardrail after one rewrite.")
    return outcome, reasons


def _count(value: Any) -> Optional[int]:
    try:
        number = int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def evaluate_gate_2(draft: Mapping[str, Any], targets: Mapping[str, Any]) -> GateResult:
    """Validate: the founder's waitlist target against the real count. No real count -> repeat, never invented."""
    target, count = _count(targets.get("waitlist_target")), _count(targets.get("waitlist_count"))
    if not draft:
        return _phase_result("gate_2", "repeat", ["The Phase 2 draft is missing."], "No draft.")
    outcome: Outcome
    if not target:
        outcome, reasons = "repeat", ["No waitlist target was set before the test. Set one, then run the waitlist test."]
    elif count is None:
        outcome, reasons = "repeat", [f"Waitlist target {target}; no real sign-up count yet. Run the test and enter "
                                      "the real count; nothing is estimated for you."]
    elif count < FAR_BELOW_SHARE * target:
        outcome, reasons = "stop", [f"{count} real sign-ups against a target of {target}: far below the target."]
    elif count < target:
        outcome, reasons = "repeat", [f"{count} real sign-ups against a target of {target}: missed by a little."]
    else:
        outcome, reasons = "go", [f"{count} real sign-ups against a target of {target}: target met."]
    outcome, reasons = _with_violations(outcome, reasons, draft)
    summary = (f"Waitlist target {target if target else 'not set'}; "
               f"real count {count if count is not None else 'not entered'}.")
    return _phase_result("gate_2", outcome, reasons, summary)


def evaluate_gate_3_plan(draft: Mapping[str, Any]) -> GateResult:
    missing = [k for k in ("stack", "mvp_features") if not draft.get(k)]
    outcome: Outcome
    if not draft or missing:
        outcome, reasons = "repeat", [f"The build plan is missing: {', '.join(missing) or 'everything'}."]
    else:
        outcome, reasons = "go", [f"Build plan with {len(draft['mvp_features'])} MVP feature(s) for the founder to accept."]
    outcome, reasons = _with_violations(outcome, reasons, draft)
    return _phase_result("gate_3_plan", outcome, reasons, "Plan only: nothing is built until the founder accepts it.")


def evaluate_gate_3(draft: Mapping[str, Any]) -> GateResult:
    """Build: phase3_build's own plain-Python checks (files exist, HTML parses, guardrails pass)."""
    if not draft:
        return _phase_result("gate_3", "repeat", ["The build did not run."], "No build.")
    failures = [str(f) for f in (draft.get("checks") or [])]
    outcome: Outcome = "repeat" if failures or draft.get("recommendation") == "repeat" else "go"
    reasons = [f"Check failed: {f}" for f in failures] or ["All Gate 3 checks passed: files exist, HTML parses, guardrails pass."]
    outcome, reasons = _with_violations(outcome, reasons, draft)
    return _phase_result("gate_3", outcome, reasons, f"{len(failures)} failed check(s).")


def evaluate_gate_4(draft: Mapping[str, Any]) -> GateResult:
    pricing, policies = draft.get("pricing") or {}, draft.get("policies") or {}
    problems = []
    if not str(pricing.get("price", "")).strip():
        problems.append("no price")
    if not pricing.get("basis"):
        problems.append("the price has no stated basis")
    problems += [f"no {name} policy draft" for name in ("terms", "privacy", "refund") if not policies.get(name)]
    outcome: Outcome
    if problems:
        outcome, reasons = "repeat", [f"Missing: {', '.join(problems)}."]
    else:
        outcome = "go"
        reasons = ["Price with a stated basis; terms, privacy and refund drafts exist (drafts, not legal advice)."]
        if not draft.get("price_has_sourced_basis"):
            reasons.append("The price basis is an ASSUMPTION, not a sourced figure.")
    outcome, reasons = _with_violations(outcome, reasons, draft)
    price = f"{pricing.get('price') or 'none'} {pricing.get('currency') or ''}".strip()
    return _phase_result("gate_4", outcome, reasons, f"Price: {price}.")


def evaluate_gate_5(draft: Mapping[str, Any], payment_test_passed: bool, payment_test_note: str = "") -> GateResult:
    problems = []
    if not (draft.get("store_page") or {}).get("title"):
        problems.append("no store-page draft")
    if not draft.get("launch_posts"):
        problems.append("no launch-post drafts")
    if not payment_test_passed:
        problems.append("the MOCKED payment and delivery test failed" + (f" ({payment_test_note})" if payment_test_note else ""))
    outcome: Outcome
    if problems:
        outcome, reasons = "repeat", [f"Not ready: {', '.join(problems)}."]
    else:
        outcome = "go"
        reasons = ["Store page and launch posts drafted; nothing is posted until the founder approves and posts it.",
                   "The MOCKED payment, delivery, refund and reconciliation test passed."]
    outcome, reasons = _with_violations(outcome, reasons, draft)
    return _phase_result("gate_5", outcome, reasons, f"{len(draft.get('launch_posts') or [])} post draft(s); payments MOCKED.")


def evaluate_gate_6(draft: Mapping[str, Any]) -> GateResult:
    """Operate: phase6_memo's plain-Python recommendation (MOCKED data -> repeat; targets missed -> stop/pivot)."""
    if not draft:
        return _phase_result("gate_6", "repeat", ["The memo did not run."], "No memo.")
    rec = draft.get("recommendation")
    outcome: Outcome = rec if rec in ("go", "repeat", "pivot", "stop") else "repeat"
    reasons = [str(draft["why"])] if draft.get("why") else ["No reason given."]
    if draft.get("mocked") and not any("MOCKED" in r for r in reasons):
        reasons.append("The sales data is MOCKED: there are no real customers yet.")
    outcome, reasons = _with_violations(outcome, reasons, draft)
    summary = "Metrics from MOCKED sales." if draft.get("mocked") else "Metrics from the store."
    return _phase_result("gate_6", outcome, reasons, summary)
