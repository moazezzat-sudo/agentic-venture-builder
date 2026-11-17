"""Founder web app: app.py helpers, and a click-through with a fake orchestrator (no model, no network)."""

import json
import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import app  # noqa: E402
import logger  # noqa: E402
from config import Settings  # noqa: E402
from logger import log_action  # noqa: E402


# ---------------------------------------------------------------- helpers

def test_brief_from_form_drops_blanks_and_splits_lists():
    brief = app.brief_from_form({
        "idea": "  invoices for designers ", "skills": "python, design ,", "budget": "",
        "location": "Egypt", "has_team": None, "team_skills": " ",
    })
    assert brief == {"idea": "invoices for designers", "skills": ["python", "design"], "location": "Egypt"}
    assert app.brief_from_form({"idea": "x", "has_team": False})["has_team"] is False


def test_every_shown_source_has_its_url_and_tier():
    line = app.claim_line({"text": "Pain is common", "support": "url", "url": "https://www.reddit.com/r/x", "tier": "D"})
    assert "https://www.reddit.com/r/x" in line and "tier D" in line and "community signal" in line
    assumption = app.claim_line({"text": "Market is big", "support": "ASSUMPTION", "tier": "NONE"})
    assert "ASSUMPTION" in assumption and "](" not in assumption


def test_run_usage_counts_only_this_runs_entries(tmp_path):
    log = tmp_path / "log.json"
    log_action(agent="orchestrator", action="start_run", run_id="old", log_path=log)
    log_action(agent="researcher", action="research_area", model="m", tokens=999, cost=0.5, log_path=log)
    log_action(agent="orchestrator", action="start_run", run_id="new", log_path=log)
    log_action(agent="weigher", action="weigh", model="fast", tokens=100, cost=0.01, log_path=log)
    log_action(agent="scorer", action="score", model="smart", tokens=250, cost=0.02, log_path=log)
    entries = app.read_log(log)
    usage = app.run_usage(app.run_entries(entries, "new"))
    assert usage == {"tokens": 350, "cost": 0.03, "models": ["fast", "smart"], "entries": 3}
    assert app.run_usage(app.run_entries(entries, "old"))["tokens"] == 999
    assert app.run_entries(entries, "missing") == []


def test_read_log_survives_missing_or_broken_file(tmp_path):
    assert app.read_log(tmp_path / "none.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert app.read_log(broken) == []


def test_model_hint_only_for_unreachable_model():
    hint = app.model_hint(ConnectionRefusedError("[WinError 10061] actively refused it"))
    assert "GROQ_API_KEY" in hint or "not reachable" in hint
    assert app.model_hint(ValueError("brief must have an idea")) == ""


def test_later_phases_are_labelled_mocked_or_stubbed():
    for number, _name, status, _note in app.PHASES:
        if number > 1:
            assert status in ("MOCKED", "STUBBED")


# ---------------------------------------------------------------- click-through

GATE = {
    "kind": "gate", "phase": 1, "gate": "gate_1", "recommendation": "stop", "reasons": ["Mostly ASSUMPTIONs"],
    "target": "At least 3 independent source URLs", "evidence_summary": "1 of 4 claims sourced", "score": 1.4,
}
STATE = {
    "round": 1, "evidence_from_round": 1, "gate_results": [GATE],
    "claims": [
        {"text": "Designers complain about invoicing", "support": "url", "url": "https://www.reddit.com/r/design/1", "tier": "D", "area": "problem_evidence", "round": 1},
        {"text": "Market is huge", "support": "ASSUMPTION", "tier": "NONE", "area": "market", "round": 1},
    ],
    "scores": {"problem_evidence": 1, "market": 0},
    "score_notes": {"problem_evidence": "one forum post", "market": "no tier A/B source"},
}


def fake_orchestrator(calls):
    mod = types.ModuleType("orchestrator")
    mod.TOKEN_BUDGET = 15_000

    class Graph:
        def get_state(self, config):
            return types.SimpleNamespace(values=dict(STATE) if calls else {})

    mod.get_graph = lambda: Graph()
    mod.stubbed_parts = lambda: []
    mod.pending = lambda run_id: None

    def start_run(brief, run_id):
        calls.append(("start", brief, run_id))
        log_action(agent="orchestrator", action="start_run", run_id=run_id)
        return {"kind": "questions", "stage": "intake", "run_id": run_id, "awaiting_founder": True,
                "stubbed": False, "stubbed_parts": [],
                "questions": [{"field": "budget", "question": "What is your budget?"}]}

    def resume_run(run_id, reply):
        calls.append(("resume", reply, run_id))
        if isinstance(reply, dict) and "answers" in reply:
            return {**GATE, "run_id": run_id, "awaiting_founder": True, "stubbed": False, "stubbed_parts": []}
        return {**STATE, "stopped": True, "stop_reason": "Founder chose stop at gate_1.", "run_id": run_id,
                "awaiting_founder": False, "stubbed": False, "stubbed_parts": []}

    mod.start_run, mod.resume_run = start_run, resume_run
    return mod


def by_label(widgets, prefix):
    matches = [w for w in widgets if str(w.label).startswith(prefix)]
    assert len(matches) == 1, f"{prefix!r}: {[w.label for w in widgets]}"
    return matches[0]


@pytest.fixture
def at(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    test_settings = Settings(outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json")
    monkeypatch.setattr(logger, "settings", test_settings)
    monkeypatch.setattr(app, "settings", test_settings)
    calls = []
    monkeypatch.setitem(sys.modules, "orchestrator", fake_orchestrator(calls))
    test = AppTest.from_file(str(ROOT_DIR / "app.py"), default_timeout=30)
    test.calls, test.log = calls, tmp_path / "log.json"
    return test


def test_brief_questions_gate_and_founder_decision(at):
    at.run()
    assert not at.exception
    labels = " ".join(m.value for m in at.markdown)  # the phase strip at the top of the page
    assert "STUBBED" in labels and "MOCKED" in labels

    # Brief form -> start_run
    by_label(at.text_area, "Your idea").input("Invoice app for freelance designers")
    by_label(at.text_input, "Location").input("Egypt")
    by_label(at.button, "Start Phase 1").click().run()
    assert at.calls[0][0] == "start" and at.calls[0][1] == {"idea": "Invoice app for freelance designers", "location": "Egypt"}
    assert any("A few questions before the research" in s.value for s in at.subheader)

    # Questions -> resume_run with answers
    by_label(at.text_area, "What is your budget?").input("300 USD")
    by_label(at.button, "Send answers").click().run()
    assert at.calls[1][1] == {"answers": {"budget": "300 USD"}}
    assert not at.exception

    # Gate card: evidence with links and tiers, then the decision button is disabled until a choice is made
    page = " ".join(m.value for m in at.markdown)
    assert "https://www.reddit.com/r/design/1" in page and "tier D" in page and "ASSUMPTION" in page
    assert by_label(at.button, "Record my decision").disabled

    at.radio[0].set_value("approve").run()
    record = by_label(at.button, "Record my decision")
    assert not record.disabled
    record.click().run()
    assert not at.exception

    # The run resumed with the founder's decision (the real gate node logs it), and shows it stopped.
    # It is sent as a dict so a module reload in Streamlit can't make resume_run refuse it.
    # The app itself writes no founder entry: one decision, one log entry.
    from schemas import FounderDecision

    kind, sent, _ = at.calls[2]
    decision = FounderDecision(**sent)
    assert kind == "resume" and isinstance(sent, dict) and "answers" not in sent
    assert decision.gate == "gate_1" and decision.outcome == "stop" and decision.approved is True
    entries = json.loads(at.log.read_text(encoding="utf-8"))
    assert not [e for e in entries if e.get("approved_by") == "founder"]
    assert any("Run stopped" in e.value and "Gate 1" in e.value for e in at.error)


# ---------------------------------------------------------------- a step fails mid-run

def failing_orchestrator(calls, with_retry):
    """start_run fails on the model after the run exists; retry_run (if present) then reaches the gate."""
    mod = fake_orchestrator(calls)
    interrupted = {"run_id": "r", "round": 1, "current_phase": 1, "stopped": False, "claims": [],
                   "awaiting_founder": False, "pending": None}

    def start_run(brief, run_id):
        calls.append(("start", brief, run_id))
        raise ConnectionError("[WinError 10061] the target machine actively refused it")

    mod.start_run = start_run
    mod.get_state = lambda run_id: dict(interrupted, run_id=run_id)
    if with_retry:
        def retry_run(run_id):
            calls.append(("retry", run_id))
            return {**GATE, "run_id": run_id, "awaiting_founder": True, "stubbed": False, "stubbed_parts": []}

        mod.retry_run = retry_run
    return mod


@pytest.mark.parametrize("with_retry", [True, False])
def test_model_error_shows_the_reason_and_retry_only_when_available(tmp_path, monkeypatch, with_retry):
    from streamlit.testing.v1 import AppTest

    test_settings = Settings(outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json")
    monkeypatch.setattr(logger, "settings", test_settings)
    monkeypatch.setattr(app, "settings", test_settings)
    calls = []
    monkeypatch.setitem(sys.modules, "orchestrator", failing_orchestrator(calls, with_retry))
    at = AppTest.from_file(str(ROOT_DIR / "app.py"), default_timeout=30)
    at.run()
    by_label(at.text_area, "Your idea").input("Invoice app")
    by_label(at.button, "Start Phase 1").click().run()
    assert not at.exception
    assert any("failed" in e.value and "not reachable" in e.value for e in at.error)
    assert any("stopped part-way" in w.value for w in at.warning)  # no stale form, an honest state
    retry = [b for b in at.button if b.label == "Retry the failed step"]
    if not with_retry:
        assert not retry
        return
    retry[0].click().run()
    assert calls[-1][0] == "retry" and not at.exception
    assert by_label(at.button, "Record my decision").disabled  # back at the gate, waiting for the founder


# ---------------------------------------------------------------- small helpers

def test_progress_label_follows_the_latest_step():
    e = lambda agent, action: {"agent": agent, "action": action, "run_id": "r"}  # noqa: E731
    assert "brief" in app.progress_label([e("orchestrator", "start_run")])
    steps = [e("orchestrator", "start_run"), e("weigher", "split_areas"), e("researcher", "research_area"),
             e("researcher", "research_area")]
    assert "(2 done)" in app.progress_label(steps)
    assert "rubric" in app.progress_label(steps + [e("skeptic", "check_founder_claims")])
    assert app.progress_label([]).startswith("Starting")


def test_run_entries_uses_run_id_on_every_entry():
    entries = [
        {"action": "start_run", "run_id": "a"}, {"action": "start_run", "run_id": "b"},
        {"action": "split_areas", "run_id": "a", "tokens": 5}, {"action": "split_areas", "run_id": "b", "tokens": 7},
    ]
    assert [e["tokens"] for e in app.run_entries(entries, "a") if "tokens" in e] == [5]


def test_run_interrupted_and_gate_labels():
    assert app.run_interrupted({"awaiting_founder": False, "stopped": False, "current_phase": 1})
    assert not app.run_interrupted({"awaiting_founder": True})
    assert not app.run_interrupted({"stopped": True, "current_phase": 1})
    assert not app.run_interrupted({"current_phase": 2})
    assert app.gate_label("gate_1") == "Gate 1" and app.gate_label("gate_1_niche") == "Gate 1 (niche)"
    assert app.friendly("Founder chose stop at gate_1_niche.") == "Founder chose stop at Gate 1 (niche)."
