"""Nothing goes out without the founder: approval.record_decision and the real gate pause.

Runs the real Phase 1 graph offline, with the fake model and fake search from
tests/test_orchestrator.py, and checks what exists before and after the founder answers.
"""

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

import orchestrator  # noqa: E402
from approval import MissingDecisionError, record_decision  # noqa: E402
from schemas import GateResult  # noqa: E402
from test_orchestrator import FULL_BRIEF, run  # noqa: E402,F401  (run is a pytest fixture)

GATE = GateResult(phase=1, gate="gate_1", recommendation="stop", reasons=["weak"], target="t")


# --------------------------------------------------------------------------- record_decision


@pytest.mark.parametrize("approved", [None, "yes", 1, 0, "true"])
def test_only_an_explicit_true_or_false_counts(approved):
    with pytest.raises(MissingDecisionError):
        record_decision("r1", GATE, approved=approved, outcome="go")  # type: ignore[arg-type]


@pytest.mark.parametrize("outcome", ["", "proceed", "GO", None])
def test_outcome_must_be_go_repeat_pivot_or_stop(outcome):
    with pytest.raises(MissingDecisionError):
        record_decision("r1", GATE, approved=True, outcome=outcome)  # type: ignore[arg-type]


def test_decision_needs_a_run_and_a_gate():
    with pytest.raises(ValueError):
        record_decision(" ", GATE, approved=True, outcome="stop")
    with pytest.raises(TypeError):
        record_decision("r1", "gate_1", approved=True, outcome="stop")  # type: ignore[arg-type]


def test_overriding_a_stop_is_marked():
    decision = record_decision("r1", GATE.model_dump(), approved=False, outcome="go", note="I have 40 interviews")
    assert decision.overrides_recommendation is True and decision.outcome == "go"
    assert record_decision("r1", GATE, approved=True, outcome="stop").overrides_recommendation is False


# --------------------------------------------------------------------------- the real gate


def _log(run_fixture):
    path = run_fixture["log"]
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _outputs(run_fixture):
    folder = run_fixture["out"]
    return sorted(p.name for p in folder.glob("*")) if folder.exists() else []


def test_paused_gate_sends_nothing_until_the_founder_answers(run):
    r = orchestrator.start_run(dict(FULL_BRIEF), "approval-1")
    assert r["awaiting_founder"] is True and r["kind"] == "gate"

    # While paused: no founder approval logged, the gate file shows only the recommendation,
    # and nothing from a later phase exists.
    gate_file = run["out"] / "phase1_gate_decision.md"
    assert not [e for e in _log(run) if e.get("approved_by") == "founder"]
    assert "_Waiting for the founder._" in gate_file.read_text(encoding="utf-8")
    assert "approved_by: founder" not in gate_file.read_text(encoding="utf-8")
    assert not [n for n in _outputs(run) if not n.startswith("phase1_")]

    decision = record_decision("approval-1", r, approved=True, outcome=r["recommendation"])
    orchestrator.resume_run("approval-1", decision)

    founder_entries = [e for e in _log(run) if e.get("approved_by") == "founder"]
    assert len(founder_entries) == 1 and founder_entries[0]["action"] == "gate_1_founder_decision"
    text = gate_file.read_text(encoding="utf-8")
    assert "approved_by: founder" in text and "Waiting for the founder" not in text


def test_anything_but_a_founder_decision_leaves_the_run_paused(run):
    r = orchestrator.start_run(dict(FULL_BRIEF), "approval-2")
    for bad in ({"approved": True}, {"answers": {}}, "approve", None):
        with pytest.raises((TypeError, ValueError)):
            orchestrator.resume_run("approval-2", bad)  # type: ignore[arg-type]
    still = orchestrator.pending("approval-2")
    assert still is not None and still["kind"] == "gate" and still["gate"] == r["gate"]
    assert not [e for e in _log(run) if e.get("approved_by") == "founder"]


def test_every_logged_approval_is_by_the_founder(run):
    r = orchestrator.start_run(dict(FULL_BRIEF), "approval-3")
    # Approving keeps the recommendation; to choose stop instead of go the founder rejects it.
    with pytest.raises(ValueError):
        orchestrator.resume_run("approval-3", record_decision("approval-3", r, approved=True, outcome="stop"))
    assert orchestrator.pending("approval-3") is not None  # still paused
    orchestrator.resume_run("approval-3", record_decision("approval-3", r, approved=False, outcome="stop"))
    for entry in _log(run):
        assert entry["approved_by"] in (None, "founder")
        if entry["action"].endswith("founder_decision"):
            assert entry["approved_by"] == "founder"
