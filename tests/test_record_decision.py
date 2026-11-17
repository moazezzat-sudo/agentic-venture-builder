"""Founder decisions at a gate: approval.record_decision.

record_decision validates and returns a FounderDecision; it writes nothing.
The gate node logs the decision when the run resumes with it (team decision, 16:00).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logger  # noqa: E402
from approval import InconsistentDecisionError, MissingDecisionError, record_decision  # noqa: E402
from config import Settings  # noqa: E402
from schemas import FounderDecision, GateResult  # noqa: E402


def _gate(recommendation="stop"):
    return GateResult(phase=1, gate="gate_1", recommendation=recommendation, reasons=["r"], target="t")


@pytest.fixture(autouse=True)
def log_file(tmp_path, monkeypatch):
    """Point the decision log at a temp file, so a write by record_decision would show up here."""
    path = tmp_path / "decision_log.json"
    monkeypatch.setattr(logger, "settings", Settings(outputs_dir=tmp_path / "outputs", decision_log_path=path))
    yield path
    assert not path.exists(), "record_decision must not write to decision_log.json; the gate logs the decision"


def test_approval_returns_the_decision_for_the_gate():
    decision = record_decision("run-1", _gate("go"), approved=True, outcome="go", note=" looks fine ")
    assert isinstance(decision, FounderDecision)
    assert (decision.phase, decision.gate) == (1, "gate_1")
    assert decision.approved and decision.outcome == "go" and not decision.overrides_recommendation
    assert decision.note == "looks fine"


def test_overriding_a_stop_is_marked():
    decision = record_decision("run-1", _gate("stop"), approved=False, outcome="repeat")
    assert not decision.approved and decision.overrides_recommendation and decision.outcome == "repeat"


def test_accepting_a_stop_is_not_an_override():
    decision = record_decision("run-1", _gate("stop"), approved=True, outcome="stop")
    assert decision.overrides_recommendation is False


def test_accepts_the_orchestrator_gate_payload_dict():
    payload = {**_gate("repeat").model_dump(), "kind": "gate", "run_id": "run-1", "awaiting_founder": True}
    decision = record_decision("run-1", payload, approved=True, outcome="repeat")
    assert decision.gate == "gate_1" and decision.phase == 1


@pytest.mark.parametrize("approved", [None, "yes", 1, 0, "true"])
def test_refuses_without_an_explicit_approve_or_reject(approved):
    with pytest.raises(MissingDecisionError):
        record_decision("run-1", _gate("go"), approved=approved, outcome="go")


@pytest.mark.parametrize("outcome", [None, "", "continue", "GO"])
def test_refuses_without_a_valid_outcome(outcome):
    with pytest.raises(MissingDecisionError):
        record_decision("run-1", _gate("go"), approved=True, outcome=outcome)


def test_approve_must_keep_and_reject_must_change_the_outcome():
    with pytest.raises(InconsistentDecisionError):
        record_decision("run-1", _gate("stop"), approved=True, outcome="go")
    with pytest.raises(InconsistentDecisionError):
        record_decision("run-1", _gate("stop"), approved=False, outcome="stop")


@pytest.mark.parametrize("run_id", ["", "  ", None])
def test_refuses_without_a_run_id(run_id):
    with pytest.raises(ValueError):
        record_decision(run_id, _gate("go"), approved=True, outcome="go")


def test_refuses_without_a_gate_result():
    with pytest.raises(TypeError):
        record_decision("run-1", None, approved=True, outcome="go")
