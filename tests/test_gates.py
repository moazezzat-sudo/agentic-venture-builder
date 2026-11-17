"""Gate 1 decision rules (gates.py + rubric.yaml): plain Python, no model."""

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import gates  # noqa: E402
from schemas import Claim  # noqa: E402

NAMES = ["problem_evidence", "market", "competition", "founder_fit", "feasibility", "willingness_to_pay", "rules_risk"]


def scores(default=3.0, **override):
    s = {n: default for n in NAMES}
    s.update(override)
    return s


def pain(domain):
    return Claim(text="pain", support="url", url=f"https://{domain}/thread", tier="D", area="problem_evidence")


def assumption():
    return Claim(text="guess", support="ASSUMPTION")


GOOD_CLAIMS = [pain("reddit.com"), pain("news.ycombinator.com"), pain("example.gov"), assumption()]


# ---- rubric

def test_rubric_loads_and_weights_sum_to_one():
    rubric = gates.load_rubric()
    assert gates.criteria_names(rubric) == NAMES
    assert sum(c["weight"] for c in rubric["criteria"].values()) == pytest.approx(1.0)


def test_bad_rubric_rejected():
    rubric = gates.load_rubric()
    bad = {**rubric, "criteria": {**rubric["criteria"], "market": {"weight": 0.5}}}
    with pytest.raises(ValueError):
        gates.validate_rubric(bad)


# ---- weighted total and score checks

def test_weighted_total():
    assert gates.weighted_total(scores(4)) == 4.0
    assert gates.weighted_total(scores(0)) == 0.0
    # 0.20*4 + 0.15*(2+2+2+2) + 0.10*(0+4) = 0.8 + 1.2 + 0.4
    assert gates.weighted_total(scores(2, problem_evidence=4, willingness_to_pay=0, rules_risk=4)) == 2.4


@pytest.mark.parametrize("bad", [
    {n: 3 for n in NAMES[:-1]},              # missing criterion
    {**scores(), "vibes": 4},                # unknown criterion
    scores(market=5),                        # above scale
    scores(market=-1),                       # below scale
    scores(market="3"),                      # not a number
    scores(market=True),                     # bool is not a score
])
def test_invalid_scores_raise(bad):
    with pytest.raises(ValueError):
        gates.weighted_total(bad)


def test_outcome_from_total_boundaries():
    assert gates.outcome_from_total(2.8, 2) == "go"
    assert gates.outcome_from_total(2.79, 3) == "pivot"
    assert gates.outcome_from_total(2.0, 2) == "repeat"
    assert gates.outcome_from_total(1.99, 4) == "stop"


# ---- claims

def test_claim_stats_counts_independent_domains():
    stats = gates.claim_stats([pain("www.reddit.com"), pain("reddit.com"), pain("x.com"), assumption()])
    assert stats["pain_domains"] == ["reddit.com", "x.com"]
    assert stats["sourced"] == 3 and stats["unsourced"] == 1


def test_claim_stats_accepts_dicts_and_no_claims():
    assert gates.claim_stats([pain("a.org").model_dump()])["sourced"] == 1
    assert gates.claim_stats([])["unsourced_share"] == 1.0


# ---- gate 1 decisions

def test_strong_idea_go():
    r = gates.evaluate_gate_1(scores(3), GOOD_CLAIMS)
    assert r.recommendation == "go" and r.score == 3.0 and r.phase == 1 and r.gate == "gate_1"


def test_weak_idea_stop():
    r = gates.evaluate_gate_1(scores(1.5), GOOD_CLAIMS)
    assert r.recommendation == "stop"
    assert any("below 2.0" in reason for reason in r.reasons)


@pytest.mark.parametrize("zeroed", ["problem_evidence", "competition", "rules_risk"])
def test_zero_on_key_criterion_stops_whatever_total(zeroed):
    r = gates.evaluate_gate_1(scores(4, **{zeroed: 0}), GOOD_CLAIMS)
    assert r.recommendation == "stop"
    assert gates.weighted_total(scores(4, **{zeroed: 0})) >= 2.8


def test_guardrail_violation_stops():
    r = gates.evaluate_gate_1(scores(4), GOOD_CLAIMS, violations=["banned category: health_advice"])
    assert r.recommendation == "stop" and "health_advice" in r.reasons[0]


def test_competition_zero_means_a_free_tool_already_solves_it():
    r = gates.evaluate_gate_1(scores(4, competition=0), GOOD_CLAIMS)
    assert r.recommendation == "stop" and "competition scored 0" in r.reasons[0]


def test_draft_violation_holds_at_repeat_but_never_upgrades_stop():
    hit = "income_promise: 'you will earn 5000 a month'"
    r = gates.evaluate_gate_1(scores(4), GOOD_CLAIMS, rewritable_violations=[hit])
    assert r.recommendation == "repeat" and any(hit in reason for reason in r.reasons)
    assert gates.evaluate_gate_1(scores(1), GOOD_CLAIMS, rewritable_violations=[hit]).recommendation == "stop"


def test_mostly_assumptions_stops():
    claims = [pain("a.org")] + [assumption() for _ in range(3)]  # 75% unsourced
    assert gates.evaluate_gate_1(scores(4), claims).recommendation == "stop"
    assert gates.evaluate_gate_1(scores(4), []).recommendation == "stop"


def test_half_unsourced_caps_go_at_repeat():
    claims = [pain("a.org"), pain("b.org"), pain("c.org"), assumption(), assumption(), assumption(), assumption()]
    r = gates.evaluate_gate_1(scores(4), claims)  # 4 of 7 unsourced = 57%
    assert r.recommendation == "repeat"


def test_too_few_pain_sources_caps_go_at_repeat():
    r = gates.evaluate_gate_1(scores(4), [pain("reddit.com"), pain("www.reddit.com"), pain("x.com")])
    assert r.recommendation == "repeat"
    assert any("independent source" in reason for reason in r.reasons)


def test_low_founder_fit_caps_go_at_repeat():
    r = gates.evaluate_gate_1(scores(4, founder_fit=1), GOOD_CLAIMS)
    assert r.recommendation == "repeat"


def test_middle_band_pivot_when_pain_is_real():
    r = gates.evaluate_gate_1(scores(2, problem_evidence=3), GOOD_CLAIMS)  # 2.2
    assert r.recommendation == "pivot"


def test_middle_band_repeat_when_pain_is_thin():
    r = gates.evaluate_gate_1(scores(2.5, problem_evidence=1), GOOD_CLAIMS)  # 2.2
    assert r.recommendation == "repeat"


def test_caps_never_upgrade_an_outcome():
    r = gates.evaluate_gate_1(scores(2, problem_evidence=3), [pain("a.org"), assumption()])
    assert r.recommendation == "pivot"
