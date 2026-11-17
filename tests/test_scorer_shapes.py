"""The scorer accepts the reply shapes small local models return (qwen3:4b)."""

from agents import scorer

CLAIMS = [{"id": "C1", "text": "Players say amateur stats apps are inaccurate", "support": "url",
           "url": "https://www.reddit.com/r/football/x", "tier": "D", "area": "problem_evidence", "kind": "pain"}]
N = scorer.MODEL_CRITERIA


def run(data):
    return scorer.clean_scores(scorer.normalize_scores(data), CLAIMS, {})


def test_expected_shape():
    s, _, _, inc = run({"criteria": {k: {"score": 2, "claim_ids": ["C1"], "reasoning": "r"} for k in N}})
    assert inc == [] and s["founder_fit"] == 2


def test_scores_and_reasons_shape():
    s, notes, _, inc = run({"scores": {k: 2 for k in N}, "reasons": {k: "because" for k in N}})
    assert inc == [] and notes["feasibility"] == "because"


def test_flat_and_string_scores():
    s, _, _, inc = run({k.replace("_", " ").title(): f"{3}/4" for k in N})
    assert inc == [] and s["feasibility"] == 3


def test_list_shape_and_text_ids():
    s, _, cited, inc = run({"criteria": [{"criterion": k, "score": 2, "claims": "C1"} for k in N]})
    assert inc == [] and cited["problem_evidence"] == ["C1"]


def test_missing_stays_incomplete_never_zero():
    s, _, _, inc = run({"scores": {"market": 1}})
    assert "founder_fit" in inc and "founder_fit" not in s and s["rules_risk"] == 4
