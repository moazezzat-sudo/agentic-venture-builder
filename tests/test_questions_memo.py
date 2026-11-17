"""agents/questions.py and agents/evaluation_memo.py with a fake model: formats, validation, fallbacks."""

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

import agents._common as common  # noqa: E402
import logger  # noqa: E402
from agents import evaluation_memo, questions  # noqa: E402
from config import Settings  # noqa: E402
from schemas import Claim, GateResult  # noqa: E402


class Fake:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, agent, system, user, role="smart", max_tokens=500, temperature=None):
        self.calls.append({"agent": agent, "user": user, "temperature": temperature})
        r = self.replies.pop(0) if self.replies else "{}"
        return (r if isinstance(r, str) else json.dumps(r)), 50, 0.0, "fake"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(logger, "settings", Settings(outputs_dir=tmp_path / "out", decision_log_path=tmp_path / "log.json"))

    def use(*replies):
        fake = Fake(*replies)
        monkeypatch.setattr(common, "invoke_model", fake)
        return fake

    return {"use": use, "out": tmp_path / "out"}


STATE = {
    "run_id": "m1", "round": 1, "evidence_from_round": 1,
    "brief": {"idea": "Order form for small bakeries", "location": "Alexandria, Egypt", "target_market": "small bakeries"},
    "claims": [
        {**Claim(text="Bakers complain about lost phone orders", support="url", url="https://www.reddit.com/r/b/1", tier="D",
                 area="problem_evidence").model_dump(), "round": 1},
        {**Claim(text="A competitor charges 10 USD a month", support="url", url="https://comp.example.com/pricing", tier="B",
                 area="willingness_to_pay").model_dump(), "round": 1},
        {**Claim(text="An ordering app exists for cafes", support="url", url="https://app.example.com", tier="B",
                 area="competition").model_dump(), "round": 1},
    ],
    "scores": {"problem_evidence": 2, "market": 1, "competition": 2, "founder_fit": 3, "feasibility": 3,
               "willingness_to_pay": 1, "rules_risk": 4},
    "score_notes": {"problem_evidence": "One thread shows the pain [0].", "market": "no evidence"},
}


def gate(rec):
    return GateResult(phase=1, gate="gate_1", recommendation=rec, reasons=[f"Rules recommend {rec}."], target="t", score=2.3)


# --------------------------------------------------------------------------- questions


SUMMARY = {"summary": "Small bakeries lose phone orders. They take orders by hand today. The founder proposes an order form. They would pay monthly.",
           "assumptions": [{"text": t, "type": k} for t, k in [("Small bakery owners", "customer"), ("Bakeries lose orders weekly", "problem"),
                                                              ("Orders on WhatsApp by hand", "current_alternative"),
                                                              ("Owners will pay monthly", "payment"), ("Off-list type", "pricing")]],
           "keywords": {"customer": "bakery owners", "problem": "lost orders", "solution": "order form", "activity": "bakery",
                        "arabic": ["مخبز"]}}


def test_summary_format_and_the_echo_guard(env):
    fake = env["use"]('<think>x</think>' + json.dumps(STATE["brief"]), "</think>" + json.dumps(SUMMARY))  # echo first, then a reply
    out = questions.discovery_summary(STATE)
    assert out["source"] == "model" and len(fake.calls) == 2  # the echo has no "summary" key -> one retry
    assert [a["id"] for a in out["assumptions"]] == ["A1", "A2", "A3", "A4"]  # "pricing" isn't one of the 5 types
    assert all(a["type"] in questions.ASSUMPTION_TYPES for a in out["assumptions"])
    assert out["keywords"]["activity"] == "bakery" and out["keywords"]["arabic"] == ["مخبز"]
    assert "Do not repeat the input" in fake.calls[0]["user"] and fake.calls[0]["temperature"] == 0


def test_summary_fallback(env):
    env["use"]("nope", "still nope")
    out = questions.discovery_summary(STATE)
    assert out["source"] == "fallback" and [a["type"] for a in out["assumptions"]] == list(questions.ASSUMPTION_TYPES)
    assert "small bakeries" in out["summary"] and out["keywords"]["customer"] == "small bakeries"
    assert "bakeries" in out["keywords"]["solution"].lower()  # words from the idea, so searches aren't only the market


def test_questions_format_drops_hypotheticals_and_unsafe_ones(env):
    good = {"text": "When did a bakery last lose an order because nobody answered?", "why": "Tests frequency.",
            "suggestions": ["Last week", "Never seen it", "Every Friday", "extra"], "choices": None}
    env["use"]({"questions": [
        good,
        {"text": "Would you use an app that takes orders?", "why": "x", "suggestions": ["Yes"]},
        {"text": "Can you write 20 five-star reviews for launch?", "why": "x", "suggestions": ["Sure"]},
        {"text": "Which do you use now?", "why": "Shows the workaround.", "suggestions": [], "choices": ["WhatsApp", "Phone", "Nothing"]},
    ]})
    qs = questions.discovery_questions(STATE, 2)
    assert 3 <= len(qs) <= 5
    for q in qs:
        assert set(q) == {"id", "text", "why", "suggestions", "choices"} and q["id"].startswith("Q2_")
        assert not questions.HYPOTHETICAL.search(q["text"]) and len(q["suggestions"]) <= 3
    assert qs[0]["text"] == good["text"] and qs[1]["choices"] == ["WhatsApp", "Phone", "Nothing"]
    assert not any("five-star" in q["text"] for q in qs)


def test_questions_fallback(env):
    env["use"]("{}", "{}")
    qs = questions.discovery_questions(STATE)
    assert len(qs) == 3 and all(q["why"] and 2 <= len(q["suggestions"]) <= 3 for q in qs)


def test_later_round_with_nothing_to_ask_returns_no_questions(env):
    env["use"]({"questions": []})
    assert questions.discovery_questions(STATE, 2) == []
    env["use"]("{}", "{}")  # a failed call still gets the fallbacks
    assert len(questions.discovery_questions(STATE, 2)) == 3


def test_intake_and_coach_questions():
    intake = questions.intake_questions({"idea": "x", "location": "Cairo"})
    assert "location" not in [q["id"] for q in intake] and all(set(q) == {"id", "text", "why", "suggestions", "choices"} for q in intake)
    coach = questions.coach_questions(STATE)
    assert [q["id"] for q in coach] == ["coach_market", "coach_willingness_to_pay", "coach_problem_evidence"]
    assert "score 1 of 4" in coach[0]["why"]


# --------------------------------------------------------------------------- memo


MEMO = {
    "headline": "Bakers describe the pain, but nobody has shown they pay.",
    "why": [{"text": "A forum thread shows bakers losing phone orders.", "claim_ids": ["C1", "C9"]},
            {"text": "About 40% of bakeries lose orders every week.", "claim_ids": []},
            {"text": "This will make you $5,000 a month.", "claim_ids": ["C2"]}],
    "per_criterion": [{"criterion": "willingness_to_pay", "explanation": "One competitor charges 10 USD a month [C2] [C7].",
                       "claim_ids": ["C2"], "counter_evidence": "Most bakeries use free WhatsApp.", "what_would_change": "A price page."},
                      {"criterion": "market", "explanation": "Egypt has 12,000 bakeries.", "claim_ids": [], "score": 4}],
    "unknowns": ["How many orders are lost"],
}


def test_memo_validates_ids_numbers_and_guardrails(env):
    env["use"](MEMO)
    memo = evaluation_memo.write_memo(STATE, gate("repeat"))
    assert memo["source"] == "model" and memo["verdict"] == "repeat"
    assert memo["why"][0]["claim_ids"] == ["C1"]  # C9 doesn't exist
    assert all("40%" not in w["text"] and "$5,000" not in w["text"] for w in memo["why"])
    per = {p["criterion"]: p for p in memo["per_criterion"]}
    assert "[C7]" not in per["willingness_to_pay"]["explanation"] and "[C2]" in per["willingness_to_pay"]["explanation"]
    assert per["market"]["score"] == 1  # from Python, not the model's 4
    assert "12,000" not in per["market"]["explanation"]
    assert per["willingness_to_pay"]["counter_evidence"].startswith("ASSUMPTION:")
    assert memo["removed"]["unknown_claim_ids"] == 2 and memo["removed"]["uncited_numbers"] >= 2
    assert memo["removed"]["guardrail_sentences"] >= 1
    text = (env["out"] / "phase1_step5_evaluation.md").read_text(encoding="utf-8")
    assert text.startswith("> **STUBBED**") and "[C1]" in text and "## Sources" in text and "https://www.reddit.com/r/b/1" in text


def test_next_steps_differ_per_verdict(env):
    steps = {}
    for rec in ("go", "repeat", "pivot", "stop"):
        env["use"](MEMO)
        steps[rec] = evaluation_memo.write_memo(STATE, gate(rec))["next_steps"]
    assert len({json.dumps(s) for s in steps.values()}) == 4
    assert steps["go"][0].startswith("Test the riskiest assumption first")
    assert any("Mom Test" in s for s in steps["repeat"]) and steps["repeat"][0].startswith("Market (score 1 of 4)")
    assert "[C1]" in steps["pivot"][0] and "[C3]" in steps["pivot"][1] and len(steps["pivot"]) == 2
    assert steps["stop"][0].startswith("Why stop:") and any(s.startswith("What would change this") for s in steps["stop"])


def test_later_gate_memo_does_not_touch_phase1(env):
    env["use"]("broken", "broken")
    later = GateResult(phase=3, gate="gate_3", recommendation="repeat", reasons=["product: file is empty"], target="t")
    memo = evaluation_memo.write_memo(STATE, later)
    assert memo["per_criterion"] == [] and not (env["out"] / "phase1_step5_evaluation.md").exists()
    assert (env["out"] / "phase3_step9_evaluation.md").exists()


def test_memo_fallback_without_the_model(env):
    env["use"]("broken", "broken")
    memo = evaluation_memo.write_memo(STATE, gate("stop"))
    assert memo["source"] == "fallback" and memo["headline"] == "The fixed rules recommend STOP."
    per = {p["criterion"]: p for p in memo["per_criterion"]}
    assert per["problem_evidence"]["claim_ids"] == ["C1"] and "[C1]" in per["problem_evidence"]["explanation"]  # scorer [0] -> C1
    assert memo["next_steps"][0].startswith("Why stop:")
