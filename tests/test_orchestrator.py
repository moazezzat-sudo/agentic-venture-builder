"""Phase 1 graph end to end with a fake model and fake search (no network, no tokens).

Checks the paths that matter: banned product stops before research, a weak
idea gets stop, a strong idea goes through both gates, the coach loop, and
that nothing moves past a gate without a FounderDecision.
"""

import functools
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

import agents._common as common  # noqa: E402
import guardrails  # noqa: E402
import logger  # noqa: E402
import orchestrator  # noqa: E402
import tools.credibility  # noqa: E402
import tools.search  # noqa: E402
from config import Settings  # noqa: E402
from logger import REQUIRED_KEYS  # noqa: E402
from schemas import FounderDecision  # noqa: E402

FULL_BRIEF = {
    "idea": "A web app that turns freelance designers' time logs into client invoices",
    "skills": ["python", "design"], "budget": "300 USD", "time_available": "15 hours a week",
    "location": "Cairo, Egypt", "target_market": "freelance designers with foreign clients", "has_team": False,
}
CRITERIA = ["problem_evidence", "market", "competition", "founder_fit", "feasibility", "willingness_to_pay", "rules_risk"]


class FakeModel:
    def __init__(self, score=4):
        self.score = score
        self.calls = []

    def __call__(self, agent, system, user, role="smart", max_tokens=500):
        self.calls.append(agent)
        reply = {
            "weigher": {"areas": [{"name": "invoicing pain", "weight": 2, "query": "freelancer invoicing problems"},
                                  {"name": "competitors", "weight": 1, "query": "freelance invoicing tools"}],
                        "innovation_type": "better_product"},
            "researcher": {"claims": [
                {"text": "Freelancers complain invoices take hours", "source": 0, "criterion": "problem_evidence"},
                {"text": "Late payment is common", "source": 1, "criterion": "problem_evidence"},
                {"text": "An invoicing tool exists for this", "source": 2, "criterion": "competition"},
                {"text": "Made-up statistic", "source": 9, "criterion": "market"},
            ]},
            "skeptic": {"checks": [{"statement": "designers need this", "verdict": "supported", "evidence": [0], "why": "forum posts"}]},
            "scorer": {"scores": {c: self.score for c in CRITERIA}, "reasons": {c: "[0]" for c in CRITERIA}},
            "coach": {"revised_idea": "Invoice templates for Cairo photographers", "missing_evidence": ["prices"],
                      "queries": ["photographer invoicing egypt"], "questions": ["Who can you interview this week?"]},
            "subdomain": {"niche": "Cairo freelance designers billing in USD", "competitor_query": "invoice app egypt freelancers",
                          "interview_questions": ["When did you last send an invoice?"]},
        }[agent]
        return json.dumps(reply), 100, 0.0, "fake-model"


def fake_search(query, max_results=3):
    n = abs(hash(query)) % 1000
    return [{"title": f"r{i}", "url": f"https://site{n}-{i}.example.org/p", "snippet": "snippet " * 80} for i in range(max_results)]


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(logger, "settings", Settings(outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json"))
    model = FakeModel()
    monkeypatch.setattr(common, "invoke_model", model)
    monkeypatch.setattr(tools.search, "search", fake_search)
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    # Keyword rules only: no model call from the category check.
    monkeypatch.setattr(guardrails, "check_category", functools.partial(guardrails.check_category, use_model=False))
    orchestrator.set_graph(orchestrator.build_graph(InMemorySaver()))
    yield {"model": model, "out": tmp_path / "outputs", "log": tmp_path / "log.json"}
    orchestrator.set_graph(None)


def decide(result, outcome, approved=None):
    return FounderDecision(phase=1, gate=result["gate"], approved=outcome == result["recommendation"] if approved is None else approved,
                           outcome=outcome)


def log_entries(run):
    entries = json.loads(run["log"].read_text())
    for e in entries:
        assert all(k in e for k in REQUIRED_KEYS), e
    return entries


def test_banned_product_stops_before_research(run):
    r = orchestrator.start_run({**FULL_BRIEF, "idea": "A crypto trading signals app"}, "banned")
    assert r["awaiting_founder"] is False and r["stopped"] is True
    assert run["model"].calls == []
    assert "STOP" in (run["out"] / "phase1_gate_decision.md").read_text(encoding="utf-8")


def test_intake_asks_only_missing_fields_then_continues(run):
    r = orchestrator.start_run({"idea": FULL_BRIEF["idea"], "skills": ["python"]}, "intake")
    assert r["awaiting_founder"] and r["kind"] == "questions"
    fields = [q["field"] for q in r["questions"]]
    assert "skills" not in fields and "location" in fields
    r = orchestrator.resume_run("intake", {"answers": {"location": "Egypt", "has_team": "no"}})
    assert r["kind"] == "gate" and r["gate"] == "gate_1"


def test_strong_idea_goes_through_both_gates(run):
    r = orchestrator.start_run(FULL_BRIEF, "strong")
    assert r["kind"] == "gate" and r["recommendation"] == "go", r["reasons"]
    r = orchestrator.resume_run("strong", decide(r, "go"))
    assert r["kind"] == "gate" and r["gate"] == "gate_1_niche"
    r = orchestrator.resume_run("strong", decide(r, "go"))
    assert r["awaiting_founder"] is False and r["current_phase"] == 2 and not r["stopped"]

    entries = log_entries(run)
    founder = [e for e in entries if e["action"].endswith("_founder_decision")]
    assert len(founder) == 2 and all(e["approved_by"] == "founder" for e in founder)
    for name in ["phase1_step1_intake.md", "phase1_step3_areas.md", "phase1_step6_scores.md",
                 "phase1_gate_decision.md", "phase1_step9_interview_kit.md", "phase1_step10_result.md"]:
        assert (run["out"] / name).exists(), name
    assert sum(e.get("tokens", 0) for e in entries) <= orchestrator.TOKEN_BUDGET


def test_weak_idea_recommends_stop(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "weak")
    assert r["recommendation"] == "stop"
    r = orchestrator.resume_run("weak", decide(r, "stop"))
    assert r["stopped"] is True and r["awaiting_founder"] is False
    assert "Founder chose **STOP**" in (run["out"] / "phase1_gate_decision.md").read_text(encoding="utf-8")


def test_no_search_results_means_stop(run, monkeypatch):
    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: [])
    r = orchestrator.start_run(FULL_BRIEF, "empty")
    assert r["recommendation"] == "stop"
    assert "researcher" not in run["model"].calls


def test_gate_refuses_anything_but_a_founder_decision(run):
    r = orchestrator.start_run(FULL_BRIEF, "guarded")
    with pytest.raises((TypeError, ValueError)):
        orchestrator.resume_run("guarded", {"answers": {}})
    with pytest.raises(ValueError):
        orchestrator.resume_run("guarded", FounderDecision(phase=1, gate="gate_1_niche", approved=True, outcome="go"))
    with pytest.raises(ValueError):
        orchestrator.resume_run("never-started", decide(r, "go"))
    assert orchestrator.pending("guarded")["gate"] == "gate_1"  # still paused


def test_founder_override_is_recorded(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "override")
    orchestrator.resume_run("override", decide(r, "go", approved=False))
    entry = [e for e in log_entries(run) if e["action"] == "gate_1_founder_decision"][0]
    assert entry["overrides_recommendation"] is True and entry["approved_by"] == "founder"


def test_pivot_loops_through_coach(run):
    r = orchestrator.start_run(FULL_BRIEF, "pivot")
    r = orchestrator.resume_run("pivot", decide(r, "pivot"))
    assert r["kind"] == "questions" and r["stage"] == "coach" and r["needs_accept_revised_idea"]
    r = orchestrator.resume_run("pivot", {"answers": {"coach_1": "five photographers"}, "accept_revised_idea": True})
    assert r["kind"] == "gate" and r["gate"] == "gate_1"
    state = orchestrator.get_graph().get_state(orchestrator._config("pivot")).values
    assert state["round"] == 2 and state["brief"]["idea"].startswith("Invoice templates")
    assert all(c["round"] == 2 for c in orchestrator.current_claims(state))


def test_model_cannot_invent_sources(run):
    orchestrator.start_run(FULL_BRIEF, "sources")
    state = orchestrator.get_graph().get_state(orchestrator._config("sources")).values
    invented = [c for c in state["claims"] if c["text"].startswith("Made-up")]
    assert invented and all(c["support"] == "ASSUMPTION" and c["url"] is None for c in invented)
    # Market stays capped at 1 without a tier A/B market source.
    assert state["scores"]["market"] <= 1
