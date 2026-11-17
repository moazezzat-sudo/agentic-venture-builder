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
    return host[4:] if host.startswith("www.") else host


def claim_stats(claims: Iterable[ClaimLike]) -> dict[str, Any]:
    """Counts the gate needs. 'Sourced' means a URL or our own evidence; ASSUMPTION is unsourced.

    No claims at all counts as fully unsourced (there is no evidence).
    """
    parsed = [_as_claim(c) for c in claims]
    total = len(parsed)
    sourced = sum(1 for c in parsed if c.support in ("url", "evidence"))
    pain_domains = sorted({
        _domain(c.url) for c in parsed
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
) -> GateResult:
    """Recommend go / repeat / pivot / stop for Gate 1 (Discover), with reasons the founder can read.

    violations: guardrail hits that stop the idea (banned category, the founder's own text).
    rewritable_violations: hits in drafts our agents wrote; they can be rewritten, so -> repeat.
    """
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
    "outcome_from_total", "claim_stats", "evaluate_gate_1", "RUBRIC_PATH",
]
