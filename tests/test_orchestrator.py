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
import tools.worldbank  # noqa: E402
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
        self.kwargs = {}  # agent -> the call's settings (role, max_tokens, temperature)

    def __call__(self, agent, system, user, role="smart", max_tokens=500, **kwargs):
        self.calls.append(agent)
        self.kwargs[agent] = {"role": role, "max_tokens": max_tokens, **kwargs}
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


def fake_indicator(country, code):
    """Fixed World Bank figures, no network. The URL is the real API URL for that country and code."""
    return {"value": 1_000_000.0, "year": 2023, "source_url": tools.worldbank.source_url(country, code)}


def no_indicator(country, code):
    return {"value": None, "year": None, "source_url": tools.worldbank.source_url(country, code)}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(logger, "settings", Settings(outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json"))
    model = FakeModel()
    monkeypatch.setattr(common, "invoke_model", model)
    monkeypatch.setattr(tools.search, "search", fake_search)
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    monkeypatch.setattr(tools.worldbank, "indicator", fake_indicator)
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
    # World Bank figures are sourced, but they don't show the pain: problem evidence is 0 -> stop.
    assert r["recommendation"] == "stop"
    assert any("problem_evidence scored 0" in reason for reason in r["reasons"])
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
    # A pivot keeps the pain: sourced problem evidence from round 1 still counts; nothing else does.
    old = [c for c in orchestrator.current_claims(state) if c["round"] == 1]
    assert old and all(c["area"] == "problem_evidence" and c["support"] == "url" for c in old)
    assert any(c["round"] == 2 for c in orchestrator.current_claims(state))
    assert not [c for c in state["claims"] if c["round"] == 1 and c["area"] == "competition"
                and c in orchestrator.current_claims(state)]


def test_interview_kit_on_go_repeat_pivot_not_on_stop(run):
    kit = run["out"] / "phase1_step9_interview_kit.md"
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "kit-stop")
    orchestrator.resume_run("kit-stop", decide(r, "stop"))
    assert not kit.exists()
    run["model"].score = 4
    r = orchestrator.start_run(FULL_BRIEF, "kit-repeat")
    orchestrator.resume_run("kit-repeat", decide(r, "repeat", approved=False))
    assert "after repeat" in kit.read_text(encoding="utf-8")


def test_founder_answer_violation_stops_with_violation_shown(run):
    brief = {k: v for k, v in FULL_BRIEF.items() if k != "target_market"}
    orchestrator.start_run(brief, "founder-text")
    r = orchestrator.resume_run("founder-text", {"answers": {"target_market": "guaranteed income of 5000 a month"}})
    assert r["recommendation"] == "stop"
    assert any("income_promise" in reason and "founder answer" in reason for reason in r["reasons"])


def test_draft_violation_recommends_repeat(run, monkeypatch):
    model = run["model"]

    def with_bad_reason(agent, *args, **kwargs):
        text, *rest = FakeModel.__call__(model, agent, *args, **kwargs)
        if agent == "scorer":
            data = json.loads(text)
            data["reasons"]["feasibility"] = "You will earn $5000 per month"
            text = json.dumps(data)
        return (text, *rest)

    monkeypatch.setattr(common, "invoke_model", with_bad_reason)
    r = orchestrator.start_run(FULL_BRIEF, "draft-text")
    assert r["recommendation"] == "repeat"
    assert any("Guardrail (draft): income_promise" in reason for reason in r["reasons"])


def test_approve_must_keep_and_reject_must_change_the_recommendation(run):
    r = orchestrator.start_run(FULL_BRIEF, "approval-rule")
    assert r["recommendation"] == "go"
    with pytest.raises(ValueError):
        orchestrator.resume_run("approval-rule", decide(r, "stop", approved=True))
    with pytest.raises(ValueError):
        orchestrator.resume_run("approval-rule", decide(r, "go", approved=False))
    assert orchestrator.pending("approval-rule")["gate"] == "gate_1"


def test_run_total_is_the_sum_of_log_tokens(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "tokens")
    orchestrator.resume_run("tokens", decide(r, "stop"))
    entries = log_entries(run)
    start = max(i for i, e in enumerate(entries) if e["action"] == "start_run" and e.get("run_id") == "tokens")
    total = sum(e.get("tokens") or 0 for e in entries[start:])
    assert total > 0 and orchestrator.run_tokens("tokens") == total
    assert f"Model tokens used: {total}," in (run["out"] / "phase1_step10_result.md").read_text(encoding="utf-8")
    model_calls = [e for e in entries if e["model"] is not None]
    assert model_calls and all("tokens" in e for e in model_calls)


def test_regulation_and_market_claims_need_tier_a_or_b():
    from agents.researcher import build_claims

    sources = [{"url": "https://forum.example.org/t", "tier": "D"}, {"url": "https://agency.example.gov/rule", "tier": "A"}]
    raw = [{"text": "A licence is required", "source": 0, "criterion": "rules_risk"},
           {"text": "A licence is required", "source": 1, "criterion": "rules_risk"},
           {"text": "The market is big", "source": 0, "criterion": "market"}]
    weak_reg, strong_reg, weak_market = build_claims(raw, sources, 1)
    assert weak_reg["area"] is None and "not usable as evidence on regulation" in weak_reg["text"]
    assert strong_reg["area"] == "rules_risk"
    assert weak_market["area"] is None


def test_competition_zero_needs_a_sourced_competitor_claim():
    from agents.scorer import clean_scores

    zero = {c: 3 for c in CRITERIA} | {"competition": 0}
    scores, notes = clean_scores(zero, {}, [])
    assert scores["competition"] == 1 and "raised to 1" in notes["competition"]
    claim = {"text": "Free tool X does this", "support": "url", "url": "https://x.example.com", "tier": "B", "area": "competition"}
    assert clean_scores(zero, {}, [claim])[0]["competition"] == 0
    # Paid tools, or a free trial, are competition but not "a free tool already solves it".
    for text in ["Plutio converts time logs into invoices", "Tool Y offers a free trial, then 12 USD a month"]:
        assert clean_scores(zero, {}, [{**claim, "text": text}])[0]["competition"] == 1


def test_world_bank_figures_become_tier_a_market_claims(run):
    orchestrator.start_run(FULL_BRIEF, "worldbank")
    state = orchestrator.get_graph().get_state(orchestrator._config("worldbank")).values
    wb = [c for c in state["claims"] if (c.get("url") or "").startswith("https://api.worldbank.org/v2/country/EG/")]
    assert len(wb) == 2  # population and internet users, from the first area only
    assert all(c["tier"] == "A" and c["area"] == "market" and c["support"] == "url" for c in wb)
    # A tier A market source lifts the evidence cap on market.
    assert state["scores"]["market"] > 1


def test_no_world_bank_value_means_no_claim(run, monkeypatch):
    monkeypatch.setattr(tools.worldbank, "indicator", no_indicator)
    orchestrator.start_run(FULL_BRIEF, "worldbank-empty")
    state = orchestrator.get_graph().get_state(orchestrator._config("worldbank-empty")).values
    assert not [c for c in state["claims"] if "worldbank" in (c.get("url") or "")]


def test_weigher_always_researches_problem_and_competitors():
    from agents.weigher import clean_areas

    # Model gave only founder-task areas with no focus: both required focuses are added.
    areas = clean_areas([{"name": "Product Development", "weight": 0.6, "query": "python web app"}], FULL_BRIEF)
    assert [a["focus"] for a in areas] == ["problem", "competitors"]
    assert "python" not in areas[1]["query"].lower() and "Egypt" in areas[1]["query"]
    # Three areas, none for competitors: one spare area is replaced, not appended.
    three = [{"name": n, "focus": f, "weight": 1, "query": n} for n, f in
             [("pain", "problem"), ("prices", "pricing"), ("more pain", "problem")]]
    focuses = [a["focus"] for a in clean_areas(three, FULL_BRIEF)]
    assert len(focuses) == 3 and "problem" in focuses and "competitors" in focuses
    assert sum(a["weight"] for a in clean_areas(three, FULL_BRIEF)) == pytest.approx(1.0, abs=0.02)
    # Nothing usable from the model still gives both.
    assert [a["focus"] for a in clean_areas(None, FULL_BRIEF)] == ["problem", "competitors"]


def test_ad_and_redirect_links_are_not_sources(monkeypatch):
    from agents import researcher

    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: [
        {"title": "ad", "url": "https://www.bing.com/aclick?ld=abc&u=xyz", "snippet": "Try Xero"},
        {"title": "ad", "url": "https://www.googleadservices.com/pagead/aclk?sa=L", "snippet": "ad"},
        {"title": "real", "url": "https://www.xero.com/pricing", "snippet": "Plans from 15 USD"},
    ])
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    sources = researcher.find_sources("invoicing tools")
    assert [s["url"] for s in sources] == ["https://www.xero.com/pricing"] and sources[0]["i"] == 0


def test_competitor_price_counts_as_willingness_to_pay_evidence():
    from agents.scorer import evidence_caps

    base = {"support": "url", "url": "https://x.example.com", "tier": "B", "area": "competition"}
    assert "willingness_to_pay" in evidence_caps([{**base, "text": "Plutio converts time logs to invoices"}])
    for text in ["Plans cost $15-60/mo", "Studio Designer charges 49 USD per month"]:
        assert "willingness_to_pay" not in evidence_caps([{**base, "text": text}])


def test_skeptic_skips_restating_the_idea():
    from agents.skeptic import clean_checks

    claims = [{"text": "t", "support": "url", "url": "https://a.example.org"}]
    raw = [{"statement": FULL_BRIEF["idea"], "verdict": "supported", "evidence": [0]},
           {"statement": "Target market: freelance designers with foreign clients", "verdict": "supported", "evidence": [0]},
           {"statement": "Designers lose hours each month writing invoices", "verdict": "supported", "evidence": [0]}]
    checks = clean_checks(raw, claims, FULL_BRIEF)
    assert [c["statement"] for c in checks] == ["Designers lose hours each month writing invoices"]


def test_scores_file_lists_the_claims_the_reasons_cite(run):
    orchestrator.start_run(FULL_BRIEF, "numbering")
    text = (run["out"] / "phase1_step6_scores.md").read_text(encoding="utf-8")
    assert "## Claims the scorer saw" in text and "\n0. " in text


class FlakyModel(FakeModel):
    """Breaks JSON on the first call to each agent in `broken`; `always` breaks every call."""

    def __init__(self, broken=(), always=()):
        super().__init__()
        self.broken, self.always, self.seen = set(broken), set(always), set()

    def __call__(self, agent, system, user, role="smart", max_tokens=500, **kwargs):
        text, tokens, cost, model = super().__call__(agent, system, user, role, max_tokens, **kwargs)
        first = agent not in self.seen
        self.seen.add(agent)
        if agent in self.always or (agent in self.broken and first):
            return "Sure! Here is my analysis of the idea, which looks", tokens, cost, model
        return text, tokens, cost, model


def test_broken_json_is_retried_once(run, monkeypatch):
    model = FlakyModel(broken={"weigher", "scorer"})
    monkeypatch.setattr(common, "invoke_model", model)
    r = orchestrator.start_run(FULL_BRIEF, "retry")
    assert r["recommendation"] == "go"
    assert model.calls.count("weigher") == 2 and model.calls.count("scorer") == 2
    entries = {e["action"]: e for e in log_entries(run)}
    assert entries["split_areas"]["parsed"] is True and entries["split_areas"]["retried"] is True
    assert entries["split_areas"]["tokens"] == 200  # both calls are counted


def test_json_failing_twice_falls_back_safely(run, monkeypatch):
    monkeypatch.setattr(common, "invoke_model", FlakyModel(always={"scorer"}))
    r = orchestrator.start_run(FULL_BRIEF, "no-json")
    scored = [e for e in log_entries(run) if e["action"].startswith("score_rubric")][0]
    assert scored["parsed"] is False and scored["retried"] is True
    assert r["recommendation"] == "stop"  # every score falls back to 0, with the reason said
    assert "the model gave no valid score" in (run["out"] / "phase1_step6_scores.md").read_text(encoding="utf-8")


def test_deterministic_steps_run_at_temperature_zero(run):
    orchestrator.start_run(FULL_BRIEF, "temperature")
    for agent in ("weigher", "researcher", "skeptic", "scorer"):
        assert run["model"].kwargs[agent]["temperature"] == 0, agent
    assert run["model"].kwargs["weigher"]["role"] == "fast"
    assert all(k["max_tokens"] <= 700 for k in run["model"].kwargs.values())


def test_local_model_gets_json_mode_and_a_token_cap(monkeypatch):
    import llm

    for model_name, think in [("qwen3:8b", False), ("gpt-oss:20b", "low")]:
        cfg = Settings(llm_provider="ollama", ollama_model=model_name)
        monkeypatch.setattr(common, "settings", cfg)
        monkeypatch.setattr(llm, "default_settings", cfg)
        client = common._llm("fast", 600, temperature=0)
        assert client.format == "json" and client.num_predict == 600 and client.temperature == 0
        assert client.reasoning == think


def test_each_area_searches_a_forum(run, monkeypatch):
    queries = []
    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: queries.append(q) or fake_search(q, max_results))
    orchestrator.start_run(FULL_BRIEF, "forums")
    state = orchestrator.get_state("forums")
    forum = [a["forum_query"] for a in state["areas"]]
    assert forum[0].endswith("site:reddit.com") and forum[1].endswith("site:news.ycombinator.com")
    assert all(q in queries for q in forum)
    research_file = next(run["out"].glob("phase1_step4_research_*.md")).read_text(encoding="utf-8")
    assert "(forum)" in research_file and "Forum query:" in research_file


def test_every_log_entry_has_the_run_id(run):
    r = orchestrator.start_run(FULL_BRIEF, "ids")
    orchestrator.resume_run("ids", decide(r, "go"))
    entries = log_entries(run)
    assert entries and all(e.get("run_id") == "ids" for e in entries), [e["action"] for e in entries if e.get("run_id") != "ids"]


def test_gate_log_has_note_approved_and_overrode_stop(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "gate-log")
    orchestrator.resume_run("gate-log", FounderDecision(phase=1, gate="gate_1", approved=False, outcome="repeat",
                                                        note="I have five interviews booked"))
    entry = [e for e in log_entries(run) if e["action"] == "gate_1_founder_decision"][0]
    assert entry["note"] == "I have five interviews booked" and entry["approved"] is False
    assert entry["overrode_stop"] is True and entry["run_id"] == "gate-log"


def test_get_state_is_read_only_and_public(run):
    assert orchestrator.get_state("nobody") is None
    orchestrator.start_run(FULL_BRIEF, "public")
    state = orchestrator.get_state("public")
    assert state["awaiting_founder"] and state["pending"]["gate"] == "gate_1"
    assert state["scores"] and state["claims"] and state["run_id"] == "public"
    assert orchestrator.get_state("public")["pending"] == state["pending"]  # reading twice changes nothing


class TimeoutOnce(FakeModel):
    """Raises a timeout on the first call to one agent, like a slow local model."""

    def __init__(self, agent):
        super().__init__()
        self.fail_agent, self.failed = agent, False

    def __call__(self, agent, *args, **kwargs):
        if agent == self.fail_agent and not self.failed:
            self.failed = True
            raise TimeoutError("model timed out")
        return super().__call__(agent, *args, **kwargs)


def test_retry_run_reruns_only_the_failed_step(run, monkeypatch):
    model = TimeoutOnce("scorer")
    monkeypatch.setattr(common, "invoke_model", model)
    with pytest.raises(TimeoutError):
        orchestrator.start_run(FULL_BRIEF, "retry-me")
    failed = orchestrator.failed_step("retry-me")
    assert failed["node"] == "scorer" and "timed out" in failed["error"]
    before = list(model.calls)

    r = orchestrator.retry_run("retry-me")
    assert r["awaiting_founder"] and r["kind"] == "gate" and r["recommendation"] == "go"
    assert model.calls[len(before):] == ["scorer"]  # weigher, researchers and skeptic are not run again
    assert orchestrator.failed_step("retry-me") is None
    assert any(e["action"] == "retry_run" and e["node"] == "scorer" for e in log_entries(run))


def test_retry_run_refuses_runs_that_did_not_fail(run):
    with pytest.raises(ValueError):
        orchestrator.retry_run("never-started")
    orchestrator.start_run(FULL_BRIEF, "paused")
    with pytest.raises(ValueError):
        orchestrator.retry_run("paused")  # waiting for the founder: resume_run, not retry


def test_model_cannot_invent_sources(run, monkeypatch):
    monkeypatch.setattr(tools.worldbank, "indicator", no_indicator)  # no tier A/B market source in this run
    orchestrator.start_run(FULL_BRIEF, "sources")
    state = orchestrator.get_graph().get_state(orchestrator._config("sources")).values
    invented = [c for c in state["claims"] if c["text"].startswith("Made-up")]
    assert invented and all(c["support"] == "ASSUMPTION" and c["url"] is None for c in invented)
    # Market stays capped at 1 without a tier A/B market source.
    assert state["scores"]["market"] <= 1
