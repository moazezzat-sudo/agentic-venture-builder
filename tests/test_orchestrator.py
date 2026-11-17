"""Phase 1 graph end to end with a fake model and fake search (no network, no tokens).

Checks the paths that matter: banned product stops before research, a weak
idea gets stop, a strong idea goes through both gates, the coach loop, and
that nothing moves past a gate without a FounderDecision.
"""

import functools
import json
import re
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
from agents import discovery  # noqa: E402
import tools.credibility  # noqa: E402
import tools.search  # noqa: E402
import tools.worldbank  # noqa: E402
from config import Settings  # noqa: E402
from logger import REQUIRED_KEYS  # noqa: E402
from schemas import FounderDecision  # noqa: E402

UNDERSTANDING = {
    "customer": "Freelance designers in Cairo with foreign clients",
    "problem": "Turning time logs into invoices takes hours and clients pay late",
    "current_alternative": "Spreadsheets and invoice templates",
    "why_now": "More Egyptian designers work for clients abroad",
    "payment": "A monthly subscription paid by the designer",
}
KEYWORDS = {"customer": "freelance designers", "problem": "late client invoices", "solution": "invoice from time logs",
            "activity": "invoicing", "arabic": []}
# A brief that arrives with a confirmed understanding (a re-run) skips the discovery conversation.
# Hashish's tests import FULL_BRIEF and expect start_run to reach Gate 1 directly.
FULL_BRIEF = {
    "idea": "A web app that turns freelance designers' time logs into client invoices",
    "skills": ["python", "design"], "budget": "300 USD", "time_available": "15 hours a week",
    "location": "Cairo, Egypt", "target_market": "freelance designers with foreign clients", "has_team": False,
    "confirmed_understanding": UNDERSTANDING, "keywords": KEYWORDS,
}
NEW_BRIEF = {k: v for k, v in FULL_BRIEF.items() if k not in ("confirmed_understanding", "keywords")}
CRITERIA = ["problem_evidence", "market", "competition", "founder_fit", "feasibility", "willingness_to_pay", "rules_risk"]


def later_phase_reply(agent, nth):
    """Replies for Hashish's Phase 2-6 agents, reused from his tests (imported here: his tests import this file)."""
    import test_phase_agents as t

    if agent == "phase3_build":  # three calls per build: format, product, docs
        return [t.FMT_MD, t.PRODUCT_MD, t.DOCS][(nth - 1) % 3]
    return {"phase2_lean_canvas": t.CANVAS, "phase3_build_plan": t.BUILD, "phase4_commercial": t.COMMERCIAL,
            "phase5_launch": t.LAUNCH, "phase6_memo": t.MEMO}.get(agent)


class FakeModel:
    def __init__(self, score=4):
        self.score = score
        self.calls = []
        self.kwargs = {}  # agent -> the call's settings (role, max_tokens, temperature)

    def __call__(self, agent, system, user, role="smart", max_tokens=500, **kwargs):
        self.calls.append(agent)
        self.kwargs[agent] = {"role": role, "max_tokens": max_tokens, **kwargs}
        later = later_phase_reply(agent, self.calls.count(agent))
        if later is not None:
            return json.dumps(later), 100, 0.0, "fake-model"
        sent = common.parse_json(user)  # the payload, framed as data by ask_json
        if agent == "discovery":
            return json.dumps(discovery_reply(sent.get("round", 1))), 100, 0.0, "fake-model"
        if agent == "evidence":
            return json.dumps(evidence_reply(sent)), 100, 0.0, "fake-model"
        if agent == "scorer":
            return json.dumps(scorer_reply(sent, self.score)), 100, 0.0, "fake-model"
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


def discovery_reply(round_no):
    return {
        "summary": "Here's what I understood: a web app for freelance designers in Cairo that turns time logs into invoices.",
        "assumptions": [{"type": t, "text": v} for t, v in UNDERSTANDING.items()],
        "keywords": KEYWORDS,
        "questions": [{"text": "Which designers exactly: UI, graphic or motion?", "why": "Narrows the customer.",
                       "suggestions": ["UI designers", "Graphic designers"]}] if round_no == 1 else [],
    }


EVIDENCE_TEXT = {
    "pain": "Designers complain that clients pay invoices late",
    "competitors": "InvoiceTool turns time logs into invoices for 10 USD a month",
    "pricing": "Invoicing apps for freelancers cost 10 USD a month",
    "regulation": "Invoices must follow the national tax rules",
}


def evidence_reply(sent):
    text = EVIDENCE_TEXT.get(sent.get("evidence_type"), "A relevant result")
    results = [{"i": r["i"], "relevant": True, "claim": text} for r in sent.get("results", [])]
    if sent.get("evidence_type") == "pricing":  # a statement for a result that doesn't exist: must become ASSUMPTION
        results.append({"i": 99, "relevant": True, "claim": "Made-up statistic"})
    return {"results": results}


def scorer_reply(sent, score):
    """Scores every criterion at `score`, citing the claim ids of the matching evidence type from the payload."""
    by_type = {t: [c["id"] for c in cs] for t, cs in (sent.get("claims_by_type") or {}).items()}
    cite = {"problem_evidence": by_type.get("pain", []), "market": by_type.get("market", []),
            "competition": by_type.get("competitors", []), "willingness_to_pay": by_type.get("pricing", []),
            "founder_fit": [], "feasibility": []}
    return {"criteria": {c: {"score": score, "claim_ids": ids[:3], "reasoning": "fake reasoning"} for c, ids in cite.items()}}


def fake_search(query, max_results=3):
    n = abs(hash(query)) % 1000
    # Titles echo the query, like real results do, so the relevance filter keeps them;
    # a "site:" query returns pages from that site.
    site = re.search(r"site:(\S+)", query)
    base = (lambda i: f"https://{site.group(1)}/t/{n}-{i}") if site else (lambda i: f"https://site{n}-{i}.example.org/p")
    return [{"title": f"r{i}: {query}", "url": base(i), "snippet": "snippet " * 80} for i in range(max_results)]


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
    return FounderDecision(phase=result.get("phase", 1), gate=result["gate"],
                           approved=outcome == result["recommendation"] if approved is None else approved,
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


def answer_discovery(run_id, r, answers=None, confirm=True):
    """Answer the discovery rounds, then confirm (or correct) the summary; returns the next pause."""
    while r.get("kind") == "questions" and r.get("stage") == "discovery":
        r = orchestrator.resume_run(run_id, {"answers": answers or {}})
    assert r["stage"] == "discovery_confirm", r
    choice = discovery.CONFIRM_YES if confirm else discovery.CONFIRM_NO
    return orchestrator.resume_run(run_id, {"answers": {"confirm": choice, "correction": "" if confirm else "Only UI designers"}})


def test_discovery_conversation_comes_before_research(run):
    brief = {k: v for k, v in NEW_BRIEF.items() if k != "skills"}
    r = orchestrator.start_run(brief, "disc")
    assert r["kind"] == "questions" and r["stage"] == "discovery" and r["round"] == 1
    assert r["summary"]["text"].startswith("Here's what I understood")
    assert [a["type"] for a in r["summary"]["assumptions"]] == list(discovery.ASSUMPTION_TYPES)
    for q in r["questions"]:
        assert set(q) == {"id", "text", "why", "suggestions", "choices"}
    ids = [q["id"] for q in r["questions"]]
    assert "skills" in ids and "location" not in ids  # only missing founder fields are asked
    assert "evidence" not in run["model"].calls  # no research before confirmation

    r = orchestrator.resume_run("disc", {"answers": {ids[0]: "UI designers", "skills": "python, figma"}})
    # Round 2: the fake model finds nothing vague, so it goes straight to the confirmation.
    assert r["stage"] == "discovery_confirm"
    assert [q["choices"] for q in r["questions"]][0] == [discovery.CONFIRM_YES, discovery.CONFIRM_NO]
    r = orchestrator.resume_run("disc", {"answers": {"confirm": discovery.CONFIRM_NO, "correction": "Only UI designers"}})
    assert r["stage"] == "discovery_confirm" and "evidence" not in run["model"].calls  # corrected, not confirmed
    r = orchestrator.resume_run("disc", {"answers": {"confirm": discovery.CONFIRM_YES}})
    assert r["kind"] == "gate" and r["gate"] == "gate_1"
    state = orchestrator.get_state("disc")
    assert state["discovery"]["confirmed"] and state["brief"]["confirmed_understanding"]["customer"]
    assert state["discovery"]["corrections"] == ["Only UI designers"]
    assert state["brief"]["skills"] == ["python", "figma"]
    text = (run["out"] / "phase1_step1_discovery.md").read_text(encoding="utf-8")
    assert "Here's what I understood" in text and "Only UI designers" in text


def test_discovery_has_at_most_two_question_rounds(run, monkeypatch):
    model = run["model"]

    def always_vague(agent, *args, **kwargs):
        text, *rest = FakeModel.__call__(model, agent, *args, **kwargs)
        if agent == "discovery":
            data = json.loads(text)
            data["questions"] = [{"text": "Still unclear: who pays?", "why": "", "suggestions": []}]
            text = json.dumps(data)
        return (text, *rest)

    monkeypatch.setattr(common, "invoke_model", always_vague)
    r = orchestrator.start_run(NEW_BRIEF, "vague")
    rounds = []
    while r["stage"] == "discovery":
        rounds.append(r["round"])
        r = orchestrator.resume_run("vague", {"answers": {}})
    assert rounds == [1, 2] and r["stage"] == "discovery_confirm"


TARGETS = {"answers": {"waitlist_target": "100", "waitlist_count": "120", "paid_orders": "10"}}
LATER_GATES = ["gate_2", "gate_3_plan", "gate_3", "gate_4", "gate_5", "gate_6"]


def to_phase_2(run_id):
    """Start a strong run and approve go at Gate 1 and the niche gate; returns the Gate 2 questions."""
    r = orchestrator.start_run(FULL_BRIEF, run_id)
    assert r["kind"] == "gate" and r["recommendation"] == "go", r["reasons"]
    r = orchestrator.resume_run(run_id, decide(r, "go"))
    assert r["kind"] == "gate" and r["gate"] == "gate_1_niche"
    return orchestrator.resume_run(run_id, decide(r, "go"))


def test_strong_idea_goes_through_every_phase(run):
    r = to_phase_2("strong")
    assert r["kind"] == "questions" and r["stage"] == "gate_2_targets"
    r = orchestrator.resume_run("strong", TARGETS)
    seen = []
    while r["awaiting_founder"]:
        if r["kind"] == "questions" and r["stage"] == "build_options":
            assert r["questions"][0]["choices"] == orchestrator.BUILD_FORMATS
            r = orchestrator.resume_run("strong", {"answers": {"product_format": orchestrator.BUILD_FORMATS[0],
                                                               "must_include": "an invoice template"}})
            continue
        assert r["kind"] == "gate", r
        assert r["memo"]["verdict"] == r["recommendation"]
        seen.append((r["gate"], r["recommendation"]))
        if r["gate"] == "gate_6":  # MOCKED sales can't support persevere: repeat; the founder chooses go
            assert r["recommendation"] == "repeat"
            r = orchestrator.resume_run("strong", decide(r, "go", approved=False))
        else:
            assert r["recommendation"] == "go", (r["gate"], r["reasons"])
            r = orchestrator.resume_run("strong", decide(r, "go"))
    assert [g for g, _ in seen] == LATER_GATES
    assert r["current_phase"] == 6 and not r["stopped"]

    entries = log_entries(run)
    founder = [e for e in entries if e["action"].endswith("_founder_decision")]
    assert len(founder) == 8 and all(e["approved_by"] == "founder" for e in founder)
    for name in ["phase1_step1_discovery.md", "phase1_step2_search_plan.md", "phase1_step3_research.md",
                 "phase1_step6_scores.md",
                 "phase1_gate_decision.md", "phase1_step9_interview_kit.md", "phase2_step1_lean_canvas.md",
                 "phase2_gate_decision.md", "phase3_gate_plan_decision.md", "phase3_step2_landing.html",
                 "phase3_step4_user_docs.md", "phase3_gate_decision.md", "phase4_gate_decision.md",
                 "payment_test_log.md", "phase5_gate_decision.md", "phase6_step1_memo.md", "phase6_gate_decision.md",
                 "phase6_step9_result.md"]:
        assert (run["out"] / name).exists(), name
    assert list(run["out"].glob("phase3_step3_product_*"))
    assert "All six phases finished" in (run["out"] / "phase6_step9_result.md").read_text(encoding="utf-8")
    assert sum(e.get("tokens", 0) for e in entries) <= orchestrator.TOKEN_BUDGET
    assert all(e.get("run_id") == "strong" for e in entries if e["agent"] in ("gate", "orchestrator"))


def test_gate_2_without_a_real_count_repeats_and_asks_again(run):
    to_phase_2("no-count")
    r = orchestrator.resume_run("no-count", {"answers": {"waitlist_target": "100"}})
    assert r["gate"] == "gate_2" and r["recommendation"] == "repeat"
    assert any("no real sign-up count" in x for x in r["reasons"])
    r = orchestrator.resume_run("no-count", decide(r, "repeat"))
    assert r["kind"] == "questions" and r["stage"] == "gate_2_targets"  # asks again, no new canvas
    r = orchestrator.resume_run("no-count", {"answers": {"waitlist_count": "12"}})
    assert r["recommendation"] == "stop"  # 12 of 100: far below the target


def test_stop_at_a_later_gate_ends_the_run(run):
    to_phase_2("later-stop")
    r = orchestrator.resume_run("later-stop", TARGETS)
    r = orchestrator.resume_run("later-stop", decide(r, "stop", approved=False))
    assert r["awaiting_founder"] is False and r["stopped"] and r["current_phase"] == 2
    assert "Stopped in Phase 2" in (run["out"] / "phase2_step9_result.md").read_text(encoding="utf-8")


def test_repeat_at_a_phase_gate_reruns_the_phase_and_is_capped(run):
    to_phase_2("loop")
    r = orchestrator.resume_run("loop", TARGETS)
    r = orchestrator.resume_run("loop", decide(r, "go"))  # gate_2 -> build plan
    for _ in range(orchestrator.MAX_PHASE_REPEATS + 1):
        assert r["gate"] == "gate_3_plan"
        r = orchestrator.resume_run("loop", decide(r, "repeat", approved=False))
    assert r["awaiting_founder"] is False and r["stopped"] and "repeat chosen more than" in r["stop_reason"]
    assert run["model"].calls.count("phase3_build_plan") == orchestrator.MAX_PHASE_REPEATS + 1


def test_weak_idea_recommends_stop(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "weak")
    assert r["recommendation"] == "stop"
    r = orchestrator.resume_run("weak", decide(r, "stop"))
    assert r["stopped"] is True and r["awaiting_founder"] is False
    assert "Founder chose **STOP**" in (run["out"] / "phase1_gate_decision.md").read_text(encoding="utf-8")


def test_no_search_results_at_all_means_repeat_not_stop(run, monkeypatch):
    # search() returns [] only when every engine failed: an outage, not evidence against the idea.
    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: [])
    r = orchestrator.start_run(FULL_BRIEF, "empty")
    assert r["recommendation"] == "repeat"
    assert any("problem_evidence scored 0" in reason for reason in r["reasons"])  # the scores still say why
    assert any("could not be gathered" in reason for reason in r["reasons"])
    assert "researcher" not in run["model"].calls


def test_search_that_works_but_finds_no_pain_still_stops(run, monkeypatch):
    # Web search answers, but the model judges nothing it finds to show the pain: problem evidence 0 -> stop.
    model = run["model"]

    def no_pain(agent, *args, **kwargs):
        text, *rest = FakeModel.__call__(model, agent, *args, **kwargs)
        if agent == "evidence" and '"evidence_type":"pain"' in args[1]:
            text = json.dumps({"results": []})
        return (text, *rest)

    monkeypatch.setattr(common, "invoke_model", no_pain)
    r = orchestrator.start_run(FULL_BRIEF, "no-pain")
    assert r["recommendation"] == "stop" and any("problem_evidence scored 0" in x for x in r["reasons"])


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
    brief = {k: v for k, v in NEW_BRIEF.items() if k != "target_market"}
    r = orchestrator.start_run(brief, "founder-text")
    r = answer_discovery("founder-text", r, {"target_market": "guaranteed income of 5000 a month"})
    assert r["recommendation"] == "stop"
    assert any("income_promise" in reason and "founder answer" in reason for reason in r["reasons"])


def test_draft_violation_recommends_repeat(run, monkeypatch):
    model = run["model"]

    def with_bad_reason(agent, *args, **kwargs):
        text, *rest = FakeModel.__call__(model, agent, *args, **kwargs)
        if agent == "scorer":
            data = json.loads(text)
            data["criteria"]["feasibility"]["reasoning"] = "You will earn $5000 per month"
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

    zero = {c: {"score": 3, "claim_ids": []} for c in CRITERIA if c != "rules_risk"} | {"competition": {"score": 0}}
    scores, notes, _, _ = clean_scores(zero, [])
    assert scores["competition"] == 1 and "raised to 1" in notes["competition"]
    claim = {"id": "C1", "kind": "competitors", "text": "Free tool X does this", "support": "url",
             "url": "https://x.example.com", "tier": "B", "area": "competition"}
    assert clean_scores(zero, [claim])[0]["competition"] == 0
    # Paid tools, or a free trial, are competition but not "a free tool already solves it".
    for text in ["Plutio converts time logs into invoices", "Tool Y offers a free trial, then 12 USD a month"]:
        assert clean_scores(zero, [{**claim, "text": text}])[0]["competition"] == 1


def test_scorer_must_cite_claims_of_the_right_type():
    from agents.scorer import clean_scores

    pain = {"id": "C1", "kind": "pain", "text": "Designers complain", "support": "url", "url": "https://a.org/x",
            "tier": "B", "area": "problem_evidence"}
    comp = {"id": "C2", "kind": "competitors", "text": "Tool Z exists", "support": "url", "url": "https://z.com",
            "tier": "B", "area": "competition"}
    raw = {"problem_evidence": {"score": 2, "claim_ids": ["C2"], "reasoning": "cites a competitor"},  # wrong type
           "competition": {"score": 2, "claim_ids": ["C2", "C99"], "reasoning": "Z"},  # C99 doesn't exist
           "market": {"score": 3, "claim_ids": [], "reasoning": "big"},
           "founder_fit": {"score": 3, "claim_ids": [], "reasoning": "skills"},
           "feasibility": {"score": 3, "claim_ids": [], "reasoning": "small"},
           "willingness_to_pay": {"score": 2, "claim_ids": ["C2"], "reasoning": "no price stated"}}
    scores, notes, cited, incomplete = clean_scores(raw, [pain, comp])
    assert scores["problem_evidence"] == 1 and notes["problem_evidence"].startswith("no evidence")
    assert scores["competition"] == 2 and cited["competition"] == ["C2"]
    assert scores["market"] == 1 and scores["willingness_to_pay"] == 1  # nothing of the right type cited
    assert scores["rules_risk"] == 4 and incomplete == []  # rules and risk is set in Python


def test_missing_criteria_mean_incomplete_scoring_and_repeat(run, monkeypatch):
    from agents.scorer import clean_scores

    _, _, _, incomplete = clean_scores({"problem_evidence": {"score": 2, "claim_ids": []}}, [])
    assert incomplete == ["market", "competition", "founder_fit", "feasibility", "willingness_to_pay"]

    model = run["model"]

    def partial(agent, *args, **kwargs):
        text, *rest = FakeModel.__call__(model, agent, *args, **kwargs)
        if agent == "scorer":
            data = json.loads(text)
            del data["criteria"]["market"]
            text = json.dumps(data)
        return (text, *rest)

    monkeypatch.setattr(common, "invoke_model", partial)
    r = orchestrator.start_run(FULL_BRIEF, "incomplete")
    assert r["recommendation"] == "repeat" and "Scoring incomplete" in r["reasons"][0]
    assert "market" not in orchestrator.get_state("incomplete")["scores"]  # never turned into a 0


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
        {"title": "Xero invoicing pricing", "url": "https://www.xero.com/pricing", "snippet": "Plans from 15 USD"},
    ])
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    sources = researcher.find_sources("invoicing tools")
    assert [s["url"] for s in sources] == ["https://www.xero.com/pricing"] and sources[0]["i"] == 0


def test_unrelated_and_off_forum_results_are_dropped(monkeypatch):
    from agents import researcher

    def search(q, max_results=3):
        if "site:reddit.com" in q:  # a fallback engine that ignores site: returns encyclopedia pages
            return [{"title": "Amazon (company)", "url": "https://en.wikipedia.org/wiki/Amazon", "snippet": "students"},
                    {"title": "PDF to Word for students?", "url": "https://www.reddit.com/r/college/x", "snippet": ""}]
        return [{"title": "Camel case", "url": "https://en.wikipedia.org/wiki/Camel_case", "snippet": "naming"},
                {"title": "Convert PDF to Word free", "url": "https://www.ilovepdf.com/pdf_to_word", "snippet": ""}]

    monkeypatch.setattr(tools.search, "search", search)
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    area = {"name": "a", "query": "students converting PDF to Word", "forum_query": "students converting PDF to Word site:reddit.com"}
    urls = [s["url"] for s in researcher.gather_sources(area)]
    assert urls == ["https://www.ilovepdf.com/pdf_to_word", "https://www.reddit.com/r/college/x"]


def test_encyclopedia_results_must_match_in_their_title():
    from agents.researcher import relevant

    q = "independent restaurants online booking complaints"
    assert not relevant(q, {"title": "McDonald's", "url": "https://en.wikipedia.org/wiki/McDonald%27s",
                            "snippet": "fast food restaurants worldwide"})
    assert relevant(q, {"title": "Online restaurant booking", "url": "https://en.wikipedia.org/wiki/Booking",
                        "snippet": ""})


def test_empty_search_is_retried_without_the_place(monkeypatch):
    from agents import researcher

    seen = []

    def search(q, max_results=3):
        seen.append(q)
        return [] if "Alexandria" in q else [{"title": f"r: {q}", "url": "https://a.example.org/x", "snippet": ""}]

    monkeypatch.setattr(tools.search, "search", search)
    monkeypatch.setattr(tools.credibility, "rate", lambda url: "B")
    sources = researcher.gather_sources({"name": "a", "query": "restaurant booking widget Alexandria, Egypt"},
                                        "Alexandria, Egypt")
    assert seen == ["restaurant booking widget Alexandria, Egypt", "restaurant booking widget"] and len(sources) == 1


def test_problem_queries_leave_out_the_location():
    from agents.weigher import clean_areas

    raw = [{"name": "pain", "focus": "problem", "weight": 1, "query": "freelancers late invoices Cairo Egypt"},
           {"name": "tools", "focus": "competitors", "weight": 1, "query": "invoicing tools Egypt"}]
    areas = clean_areas(raw, FULL_BRIEF)
    assert areas[0]["query"] == "freelancers late invoices" and areas[1]["query"] == "invoicing tools Egypt"


def test_problem_evidence_caps_follow_the_independent_sources():
    from agents.scorer import evidence_caps

    def pain(url, tier):
        return {"text": "pain", "support": "url", "url": url, "tier": tier, "area": "problem_evidence"}

    threads = [pain(f"https://www.reddit.com/r/jobs/comments/{i}/t/", "D") for i in "abc"]
    assert evidence_caps(threads[:2])["problem_evidence"][0] == 2  # 2 independent sources
    assert evidence_caps(threads)["problem_evidence"][0] == 2       # 3, but only tier D
    assert "problem_evidence" not in evidence_caps(threads + [pain("https://www.bls.gov/x", "A")])


def test_criterion_synonyms_map_to_the_rubric():
    from agents.researcher import build_claims

    sources = [{"url": "https://resos.example.com/cost", "tier": "B"}]
    raw = [{"text": "Systems cost from free to 500 USD a month", "source": 0, "criterion": "pricing"},
           {"text": "Tool X does this", "source": 0, "criterion": "Competitors"}]
    assert [c["area"] for c in build_claims(raw, sources, 1)] == ["willingness_to_pay", "competition"]


def test_search_outage_gives_repeat_not_stop(run, monkeypatch):
    # Every web engine fails; only the encyclopedia fallback answers, with unrelated pages.
    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: [
        {"title": "Tesla, Inc.", "url": "https://en.wikipedia.org/wiki/Tesla", "snippet": "", "engine": "wikipedia"}])
    r = orchestrator.start_run(FULL_BRIEF, "outage")
    assert r["recommendation"] == "repeat"
    assert any("could not be gathered" in reason for reason in r["reasons"])
    entries = [e for e in log_entries(run) if e["action"] == "judge_relevance"]
    assert entries and all(e["web_search_ok"] is False for e in entries)


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
    assert "## Claims" in text and "[C1 · " in text and "| Claims |" in text
    research = (run["out"] / "phase1_step3_research.md").read_text(encoding="utf-8")
    assert "| pain |" in research and "[C" in research


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
    model = FlakyModel(broken={"skeptic", "scorer"})
    monkeypatch.setattr(common, "invoke_model", model)
    r = orchestrator.start_run(FULL_BRIEF, "retry")
    assert r["recommendation"] == "go"
    assert model.calls.count("skeptic") == 2 and model.calls.count("scorer") == 2
    entries = {e["action"]: e for e in log_entries(run)}
    assert entries["check_founder_claims"]["parsed"] is True and entries["check_founder_claims"]["retried"] is True
    assert entries["check_founder_claims"]["tokens"] == 200  # both calls are counted


def test_json_failing_twice_falls_back_safely(run, monkeypatch):
    monkeypatch.setattr(common, "invoke_model", FlakyModel(always={"scorer"}))
    r = orchestrator.start_run(FULL_BRIEF, "no-json")
    scored = [e for e in log_entries(run) if e["action"].startswith("score_rubric")][0]
    assert scored["parsed"] is False and scored["retried"] is True
    # No scores at all: scoring incomplete -> repeat (never a 0 for what the model did not return).
    assert r["recommendation"] == "repeat" and "Scoring incomplete" in r["reasons"][0]
    assert "**missing**" in (run["out"] / "phase1_step6_scores.md").read_text(encoding="utf-8")


def test_deterministic_steps_run_at_temperature_zero(run):
    orchestrator.start_run(NEW_BRIEF, "temperature")
    orchestrator.resume_run("temperature", {"answers": {}})
    orchestrator.resume_run("temperature", {"answers": {"confirm": discovery.CONFIRM_YES}})
    for agent in ("discovery", "evidence", "skeptic", "scorer"):
        assert run["model"].kwargs[agent]["temperature"] == 0, agent
    assert run["model"].kwargs["evidence"]["role"] == "fast" and run["model"].kwargs["discovery"]["role"] == "fast"
    assert all(k["max_tokens"] <= 1000 for k in run["model"].kwargs.values())


def test_local_model_gets_json_mode_and_a_token_cap(monkeypatch):
    import llm

    for model_name, think in [("qwen3:8b", False), ("gpt-oss:20b", "low")]:
        cfg = Settings(llm_provider="ollama", ollama_model=model_name)
        monkeypatch.setattr(common, "settings", cfg)
        monkeypatch.setattr(llm, "default_settings", cfg)
        client = common._llm("fast", 600, temperature=0)
        assert client.format == "json" and client.num_predict == 600 and client.temperature == 0
        assert client.reasoning == think


def test_search_plan_per_evidence_type():
    from agents.search_plan import MAX_QUERIES, build_search_plan

    plan = build_search_plan({"brief": FULL_BRIEF})
    types = [p["evidence_type"] for p in plan]
    assert {"pain", "competitors", "pricing", "market"} <= set(types) and len(plan) <= MAX_QUERIES
    queries = {p["evidence_type"]: [x["query"] for x in plan if x["evidence_type"] == p["evidence_type"]] for p in plan}
    assert any(q.endswith("site:reddit.com") for q in queries["pain"])
    assert any(q.endswith("site:play.google.com") for q in queries["competitors"])
    assert any("price" in q and "Egypt" in q for q in queries["pricing"])
    assert all(p["why"] for p in plan)
    assert "regulation" in types  # invoicing touches tax rules: a regulated area
    habit = {"idea": "A habit tracker for novelists", "location": "Cairo, Egypt",
             "keywords": {"customer": "novelists", "problem": "writing habit", "solution": "habit tracker",
                          "activity": "writing"}}
    assert "regulation" not in [p["evidence_type"] for p in build_search_plan({"brief": habit})]
    football = {**FULL_BRIEF, "idea": "An app that films amateur football matches on a phone",
                "keywords": {**KEYWORDS, "activity": "video recording", "arabic": ["تصوير مباريات", "كرة قدم"]}}
    plan = build_search_plan({"brief": football})
    assert any(p["evidence_type"] == "regulation" and p["query"].endswith("site:gov.eg") for p in plan)
    assert any(p["query"] == "تصوير مباريات كرة قدم" for p in plan)  # Arabic keywords for Egypt


def test_research_keeps_relevant_results_and_logs_the_rest(run, monkeypatch):
    def search(q, max_results=3):
        site = re.search(r"site:(\S+)", q)
        if site:
            return [{"title": f"{q} thread", "url": f"https://{site.group(1)}/r/x/comments/{abs(hash(q)) % 97}/t/",
                     "snippet": "", "engine": "ddgs:duckduckgo"}]
        return [{"title": "Freelance designers late client invoices", "url": "https://a.example.org/1", "snippet": "",
                 "engine": "ddgs:duckduckgo"},
                {"title": "Celebrity gossip", "url": "https://b.example.org/2", "snippet": "", "engine": "ddgs:duckduckgo"}]

    monkeypatch.setattr(tools.search, "search", search)
    orchestrator.start_run(FULL_BRIEF, "relevance")
    state = orchestrator.get_state("relevance")
    assert [p["evidence_type"] for p in state["search_plan"]][:3] == ["pain", "pain", "pain"]
    kinds = {c.get("kind") for c in state["claims"]}
    assert {"pain", "competitors", "pricing", "market"} <= kinds
    assert all(c["id"].startswith("C") for c in state["claims"])
    assert len({c["id"] for c in state["claims"]}) == len(state["claims"])  # unique ids across parallel researchers
    queries = [e for e in log_entries(run) if e["action"] == "search_query"]
    dropped = [d for e in queries for d in e["dropped"]]
    assert any("keyword score" in d["reason"] and "b.example.org" in d["url"] for d in dropped)


def test_research_counts_a_source_once(run, monkeypatch):
    from agents import researcher

    monkeypatch.setattr(tools.search, "search", lambda q, max_results=3: [
        {"title": "Invoice from time logs app", "url": "https://tool.example.com/", "snippet": "", "engine": "ddgs:yahoo"}])
    out = researcher.evidence_node({"evidence_type": "competitors", "brief": FULL_BRIEF, "round": 1, "run_id": "dedupe",
                                    "items": [{"query": "invoice from time logs app"}, {"query": "invoice time logs tool"}]})
    assert len(out["claims"]) == 1 and out["claims"][0]["kind"] == "competitors"
    queries = [e for e in log_entries(run) if e["action"] == "search_query"]
    assert [d["reason"] for e in queries for d in e["dropped"]] == ["same source already kept"]


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




def test_gate_payload_carries_the_evaluation_memo(run):
    r = orchestrator.start_run(FULL_BRIEF, "memo")
    memo = r["memo"]
    assert {"verdict", "headline", "why", "per_criterion", "unknowns", "next_steps"} <= set(memo)
    assert memo["verdict"] == r["recommendation"] and memo["source"] == "fallback"
    ids = {c["id"] for c in orchestrator.get_state("memo")["claims"]}
    cited = [i for p in memo["per_criterion"] for i in p["claim_ids"]]
    assert cited and set(cited) <= ids
    assert "## Evaluation memo" in (run["out"] / "phase1_gate_decision.md").read_text(encoding="utf-8")


def test_coach_asks_about_the_missing_evidence_types(run):
    run["model"].score = 1
    r = orchestrator.start_run(FULL_BRIEF, "coach-gaps")
    r = orchestrator.resume_run("coach-gaps", decide(r, "repeat", approved=False))
    assert r["stage"] == "coach" and set(r["missing_evidence_types"]) >= {"pain", "pricing"}
    ids = [q["id"] for q in r["questions"]]
    assert "coach_pain" in ids and "coach_pricing" in ids
    assert all(set(q) == {"id", "text", "why", "suggestions", "choices"} for q in r["questions"])


def test_request_changes_reruns_the_phase_with_the_note(run):
    to_phase_2("changes")
    r = orchestrator.resume_run("changes", TARGETS)
    r = orchestrator.resume_run("changes", decide(r, "go"))  # gate_2
    assert r["gate"] == "gate_3_plan"
    r = orchestrator.resume_run("changes", FounderDecision(phase=3, gate="gate_3_plan", approved=False, outcome="repeat",
                                                           note="Use SQLite only, no cloud database"))
    assert r["gate"] == "gate_3_plan"  # the plan was redrafted
    assert run["model"].calls.count("phase3_build_plan") == 2
    assert orchestrator.get_state("changes")["brief"]["change_request"] == "Use SQLite only, no cloud database"
    r = orchestrator.resume_run("changes", decide(r, "go"))
    assert r["stage"] == "build_options"  # the founder chooses the format before anything is built


def test_an_echoed_input_counts_as_not_parsed_and_is_retried(monkeypatch):
    # qwen3:4b in JSON mode echoed the input back: valid JSON, but none of the reply's keys.
    replies = iter([json.dumps({"brief": {"idea": "x"}, "round": 1}), json.dumps({"summary": "ok", "questions": []})])
    seen = []

    def echo_then_answer(agent, system, user, **kwargs):
        seen.append(user)
        return next(replies), 50, 0.0, "fake-model"

    monkeypatch.setattr(common, "invoke_model", echo_then_answer)
    data, usage = common.ask_json("discovery", {"brief": {"idea": "x"}}, expect=("summary", "questions"))
    assert data == {"summary": "ok", "questions": []} and usage["retried"] and usage["tokens"] == 100
    assert seen[0].startswith("Input data (do not repeat it):") and "with its keys: summary, questions." in seen[0]
