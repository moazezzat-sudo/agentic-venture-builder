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
    assert "No source found" in assumption and "](" not in assumption


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
    "memo": {
        "verdict": "stop", "headline": "Only one forum post shows the pain, and nobody pays yet.",
        "why": [{"text": "One community signal of the pain", "claim_ids": ["C1"]},
                {"text": "No market size found", "claim_ids": ["C2"]}],
        "per_criterion": [{"criterion": "problem_evidence", "score": 1, "explanation": "One forum post.",
                           "claim_ids": ["C1"], "counter_evidence": "Designers already use spreadsheets.",
                           "what_would_change": "Three independent sources showing the pain."}],
        "unknowns": ["Whether designers would pay"], "next_steps": ["Interview five freelance designers"],
    },
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
                "summary": {"text": "You want an invoice app for freelance designers in Egypt.",
                            "assumptions": ["You will build it yourself"]},
                "questions": [
                    {"id": "budget", "text": "What is your budget?", "why": "Feasibility depends on it.",
                     "suggestions": ["100 USD", "300 USD"], "choices": None},
                    {"id": "team", "text": "Do you have a team?", "why": "Founder fit.", "suggestions": [],
                     "choices": ["Solo", "With a team"]},
                ]}

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


def ready_settings(tmp_path, **kw):
    """Test settings with a hosted provider, so the app counts the model as ready without any network."""
    values = dict(llm_provider="groq", groq_api_key="test-placeholder-not-a-key",
                  outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json")
    values.update(kw)
    return Settings(**values)


def use_settings(monkeypatch, test_settings):
    import config

    # AppTest runs app.py as a new script that imports config.settings itself.
    for module in (config, logger, app):
        monkeypatch.setattr(module, "settings", test_settings)


@pytest.fixture
def at(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    test_settings = ready_settings(tmp_path)
    use_settings(monkeypatch, test_settings)
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
    assert any("Before I research" in s.value for s in at.subheader)
    page = " ".join(m.value for m in at.markdown)
    assert "Here's what I understood" in page and "You will build it yourself" in page
    assert any("Why I ask: Feasibility depends on it." in c.value for c in at.caption)

    # Questions -> resume_run with answers
    by_label(at.button, "300 USD").click().run()  # a suggestion chip fills the answer
    assert by_label(at.text_area, "What is your budget?").value == "300 USD"
    by_label(at.radio, "Do you have a team?").set_value("Solo").run()
    by_label(at.button, "Send and start the research").click().run()
    assert at.calls[1][1] == {"answers": {"budget": "300 USD", "team": "Solo"}}
    assert not at.exception

    # Gate card: evidence with links and tiers, then the decision button is disabled until a choice is made
    page = " ".join(m.value for m in at.markdown)
    assert "https://www.reddit.com/r/design/1" in page and "tier D" in page and "No source found" in page
    assert by_label(at.button, "Record my decision").disabled

    # The evaluation: verdict, headline, cited why, a criterion card, unknowns and next steps
    page = " ".join(m.value for m in at.markdown)
    assert "Only one forum post shows the pain" in page
    assert "[[C1]](https://www.reddit.com/r/design/1" in page  # the citation opens its source
    assert "[C2: no source found]" in page  # an ASSUMPTION is never dressed up as a source
    assert "Problem evidence" in page and "Designers already use spreadsheets." in page
    assert "Whether designers would pay" in page and "Interview five freelance designers" in page

    # Request changes needs a note before it can be sent
    at.radio[0].set_value("changes").run()
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
    assert any("We stopped here" in e.value and "Gate 1" in e.value for e in at.error)


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

    use_settings(monkeypatch, ready_settings(tmp_path))
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


# ---------------------------------------------------------------- the app never waits for the model

class FakeResponse:
    def __init__(self, models):
        self.models = models

    def raise_for_status(self):
        pass

    def json(self):
        return {"models": [{"name": m} for m in self.models]}


def local_settings(tmp_path, base="http://ollama:11434", model="qwen3:8b", fast=""):
    return ready_settings(tmp_path, llm_provider="ollama", groq_api_key="", ollama_base_url=base,
                          ollama_model=model, ollama_fast_model=fast)


def test_model_status_hosted_provider_is_ready_without_a_request(tmp_path):
    def no_network(*a, **k):
        raise AssertionError("no request expected for a hosted provider")

    assert app.model_status(ready_settings(tmp_path), get=no_network)["state"] == "ready"


def test_model_status_ready_when_ollama_has_the_model(tmp_path):
    cfg = local_settings(tmp_path)
    assert app.model_status(cfg, get=lambda url, timeout: FakeResponse(["qwen3:8b"]))["state"] == "ready"
    # an untagged model name matches Ollama's "name:latest"
    cfg = local_settings(tmp_path, model="mymodel")
    assert app.model_status(cfg, get=lambda url, timeout: FakeResponse(["mymodel:latest"]))["state"] == "ready"


def test_model_status_downloading_names_the_model_size_and_the_log_command(tmp_path):
    cfg = local_settings(tmp_path, fast="qwen3:4b")
    status = app.model_status(cfg, get=lambda url, timeout: FakeResponse(["qwen3:4b"]))
    assert status["state"] == "downloading" and status["missing"] == ["qwen3:8b"]
    assert "still downloading" in status["message"] and "about 5 GB" in status["message"]
    assert "docker compose logs -f model-pull" in status["message"] and "GROQ_API_KEY" in status["message"]


def test_model_status_native_ollama_without_the_model_says_ollama_pull(tmp_path):
    cfg = local_settings(tmp_path, base="http://host.docker.internal:11434", model="qwen3:4b")
    status = app.model_status(cfg, get=lambda url, timeout: FakeResponse([]))
    assert status["state"] == "downloading" and "ollama pull qwen3:4b" in status["message"]


def test_model_status_unreachable_when_nothing_answers(tmp_path):
    # A real request to a closed local port: refused at once, like a stopped ollama service.
    status = app.model_status(local_settings(tmp_path, base="http://127.0.0.1:9"))
    assert status["state"] == "unreachable" and "No Ollama is answering" in status["message"]


def test_model_hint_for_a_model_that_is_not_pulled_yet():
    hint = app.model_hint(RuntimeError('model "qwen3:8b" not found, try pulling it first (status code: 404)'))
    assert "not downloaded yet" in hint and "Retry" in hint


@pytest.mark.parametrize("state", ["stopped", "downloading"])
def test_app_opens_at_once_with_a_clear_message_when_the_model_is_not_ready(tmp_path, monkeypatch, state):
    import requests
    from streamlit.testing.v1 import AppTest

    use_settings(monkeypatch, local_settings(tmp_path))
    calls = []
    monkeypatch.setitem(sys.modules, "orchestrator", fake_orchestrator(calls))
    replies = {"downloading": [FakeResponse([]), FakeResponse(["qwen3:8b"])]}

    def fake_get(url, timeout):
        if state == "stopped":
            raise requests.ConnectionError("ollama service stopped")
        return replies["downloading"][0]

    monkeypatch.setattr(requests, "get", fake_get)
    at = AppTest.from_file(str(ROOT_DIR / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    message = " ".join(w.value for w in at.warning)
    if state == "stopped":
        assert "not answering" in message and "docker compose up -d ollama model-pull" in message
    else:
        assert "still downloading" in message and "docker compose logs -f model-pull" in message
    # the brief can be written, but the run can't start yet; nothing was sent to the orchestrator
    assert by_label(at.button, "Start Phase 1").disabled and not calls

    # Retry checks again; once the model is there the message goes and Start turns on
    if state == "downloading":
        replies["downloading"].pop(0)
        by_label(at.button, "Retry").click().run()
        assert not at.warning and not by_label(at.button, "Start Phase 1").disabled


def test_model_status_is_cached_briefly_per_session():
    calls = []

    def check():
        calls.append(1)
        return {"state": "unreachable", "message": "m", "missing": []}

    store = {}
    app.cached_model_status(store, max_age=60, check=check)
    app.cached_model_status(store, max_age=60, check=check)
    assert len(calls) == 1
    app.cached_model_status(store, max_age=0, check=check)
    assert len(calls) == 2


# ---------------------------------------------------------------- Phases 2-6, sale to cash, finished screen

PHASE2_DRAFT = {
    "status": "STUBBED", "violations": [],
    "claims": [{"text": "Tutors pay for templates", "support": "url", "url": "https://www.etsy.com/x", "tier": "B"},
               {"text": "Price 5 USD", "support": "ASSUMPTION", "tier": "NONE"}],
}


def test_drafts_by_phase_groups_agents_by_their_phase_number():
    state = {"drafts": {"phase3_build": {"status": "Working"}, "phase2_lean_canvas": PHASE2_DRAFT,
                        "phase3_build_plan": {"status": "STUBBED"}, "not_a_phase": {}}}
    grouped = app.drafts_by_phase(state)
    assert list(grouped) == [2, 3]
    assert [a for a, _ in grouped[3]] == ["phase3_build", "phase3_build_plan"]
    assert app.status_badge("MOCKED") == ":violet-badge[MOCKED]" and app.status_badge(None) == ":orange-badge[STUBBED]"


def test_decision_rows_pair_each_gate_with_the_founders_answer():
    state = {
        "gate_results": [{"gate": "gate_1", "phase": 1, "recommendation": "stop", "score": 1.9},
                         {"gate": "gate_1", "phase": 1, "recommendation": "go", "score": 3.0},
                         {"gate": "gate_2", "phase": 2, "recommendation": "repeat", "score": None}],
        "founder_decisions": [{"gate": "gate_1", "approved": False, "outcome": "repeat", "note": "one more round"},
                              {"gate": "gate_1", "approved": True, "outcome": "go"}],
    }
    rows = app.decision_rows(state)
    assert [r["recommendation"] for r in rows] == ["stop", "go", "repeat"]
    assert rows[0]["founder"] == {"approved": False, "outcome": "repeat", "note": "one more round", "overrides": True}
    assert rows[1]["founder"]["overrides"] is False
    assert rows[2]["founder"] is None  # still waiting for the founder


def test_run_output_files_leaves_out_files_from_before_the_run(tmp_path):
    import os
    import time

    old, new = tmp_path / "phase1_step1_old.md", tmp_path / "phase1_step1_new.md"
    old.write_text("old"), new.write_text("new")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    entries = [{"action": "start_run", "run_id": "r", "timestamp": started}]
    assert [p.name for p in app.run_output_files(entries, tmp_path)] == ["phase1_step1_new.md"]
    assert len(app.run_output_files([], tmp_path)) == 2  # no start entry: show everything


def finished_orchestrator(calls, state):
    mod = fake_orchestrator(calls)
    mod.get_state = lambda run_id: dict(state, run_id=run_id, awaiting_founder=False, pending=None)
    return mod


def test_finished_screen_phase_panels_and_mocked_sale_to_cash(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    test_settings = ready_settings(tmp_path)
    use_settings(monkeypatch, test_settings)  # payments.py reads config.settings: outputs/ stays untouched
    state = {**STATE, "stopped": True, "stop_reason": "Founder chose stop at gate_2.", "current_phase": 2,
             "gate_results": [GATE, {**GATE, "gate": "gate_2", "phase": 2, "recommendation": "repeat", "score": None}],
             "founder_decisions": [{"gate": "gate_1", "approved": False, "outcome": "go", "note": "40 interviews"},
                                   {"gate": "gate_2", "approved": False, "outcome": "stop"}],
             "drafts": {"phase2_lean_canvas": PHASE2_DRAFT}}
    calls = []
    monkeypatch.setitem(sys.modules, "orchestrator", finished_orchestrator(calls, state))
    log_action(agent="orchestrator", action="start_run", run_id="done")
    log_action(agent="scorer", action="score", run_id="done", model="m", tokens=1234, cost=0)
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "phase2_step1_lean_canvas.md").write_text("> **STUBBED**\n\n## Lean Canvas", encoding="utf-8")

    at = AppTest.from_file(str(ROOT_DIR / "app.py"), default_timeout=30)
    at.session_state["run_id"] = "done"
    at.session_state["result"] = {**state, "run_id": "done", "awaiting_founder": False}
    at.run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    # every gate decision, with the override and the note
    assert "| Gate 1 | **STOP**" in page and "rejected → **GO** (override)" in page and "40 interviews" in page
    assert "| Gate 2 | **REPEAT**" in page
    assert any(m.label.startswith("Model tokens") and m.value == "1,234" for m in at.metric)
    # the run's output files and the Phase 2 draft with the status its agent set
    assert any("phase2_step1_lean_canvas.md" in e.label for e in at.expander)
    assert any("Validate" in e.label and "STUBBED" in e.label and "draft ready" in e.label for e in at.expander)
    assert "https://www.etsy.com/x" in page
    # the MOCKED sale to cash runs payments.py and shows its log
    assert "Sale to cash** :violet-badge[MOCKED]" in page
    by_label(at.button, "Run the mocked sale to cash").click().run()
    assert not at.exception and (out / "payment_test_log.md").exists()
    assert any("MOCKED payment test log" in e.label for e in at.expander)



# ---------------------------------------------------------------- founder actions and demo limit

def test_founder_actions_map_to_a_decision():
    assert app.founder_decision("approve", "stop") == (True, "stop")
    assert app.founder_decision("reject", "stop", "repeat") == (False, "repeat")
    assert app.founder_decision("changes", "go") == (False, "repeat")  # request changes = repeat + note
    assert app.founder_decision("changes", "repeat") == (True, "repeat")


def test_demo_limit_blocks_go_into_the_next_phase_only():
    niche = {"gate": "gate_1_niche", "phase": 1}
    assert app.blocked_by_demo_limit(niche, "go", stop_after=1)
    assert not app.blocked_by_demo_limit({"gate": "gate_1", "phase": 1}, "go", stop_after=1)  # go -> niche, still Phase 1
    assert not app.blocked_by_demo_limit(niche, "stop", stop_after=1)
    assert not app.blocked_by_demo_limit(niche, "go", stop_after=6)
    assert app.blocked_by_demo_limit({"gate": "gate_3", "phase": 3}, "go", stop_after=3)


def test_questions_old_and_new_shapes_and_citations():
    old = app.normalize_question({"field": "budget", "question": "Budget?"})
    assert old == {"id": "budget", "text": "Budget?", "why": "", "suggestions": [], "choices": None}
    new = app.normalize_question({"id": "q1", "text": "Who?", "why": "fit", "suggestions": ["me"], "choices": ["a", "b"]})
    assert new["choices"] == ["a", "b"] and new["suggestions"] == ["me"]
    index = app.claim_index(STATE)
    assert set(index) == {"C1", "C2"}
    assert app.cite(["C1"], index).startswith("[[C1]](https://www.reddit.com/r/design/1")
    assert app.cite(["C9"], index) == "[C9: no source found]"


def test_search_plan_groups_searches_by_evidence_type():
    state = {"areas": [{"name": "pain", "query": "football pitch booking problems", "evidence_type": "problem"},
                       {"name": "rivals", "query": "pitch booking apps egypt", "evidence_type": "competitors"},
                       {"name": "pain2", "query": "5-a-side players complain", "evidence_type": "problem"}]}
    plan = app.search_plan(state)
    assert [g["evidence_type"] for g in plan] == ["problem", "competitors"]
    assert [s["name"] for s in plan[0]["searches"]] == ["pain", "pain2"]
    assert app.search_plan({"areas": [{"name": "x", "query": "q"}]})[0]["evidence_type"] == "Other evidence"
