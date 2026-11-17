"""Founder decisions at a gate: approval.record_decision."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from approval import InconsistentDecisionError, MissingDecisionError, record_decision  # noqa: E402
from logger import REQUIRED_KEYS  # noqa: E402
from schemas import FounderDecision, GateResult  # noqa: E402


def _gate(recommendation="stop"):
    return GateResult(phase=1, gate="gate_1", recommendation=recommendation, reasons=["r"], target="t")


def _entries(log):
    return json.loads(log.read_text(encoding="utf-8")) if log.exists() else []


def test_approval_is_logged_with_founder_and_all_required_keys(tmp_path):
    log = tmp_path / "decision_log.json"
    decision = record_decision("run-1", _gate("go"), approved=True, outcome="go", note=" looks fine ", log_path=log)
    assert isinstance(decision, FounderDecision)
    assert decision.approved and decision.outcome == "go" and not decision.overrides_recommendation
    assert decision.note == "looks fine"
    [entry] = _entries(log)
    for key in REQUIRED_KEYS:
        assert key in entry
    assert entry["approved_by"] == "founder" and entry["agent"] == "founder"
    assert entry["action"] == "approve_gate_1" and entry["outcome"] == "go"
    assert entry["run_id"] == "run-1" and entry["recommendation"] == "go"
    assert entry["model"] is None and entry["cost"] == 0 and entry["sources"] == []


def test_overriding_a_stop_is_recorded_as_such(tmp_path):
    log = tmp_path / "decision_log.json"
    decision = record_decision("run-1", _gate("stop"), approved=False, outcome="repeat", log_path=log)
    assert not decision.approved and decision.overrides_recommendation
    [entry] = _entries(log)
    assert entry["action"] == "reject_gate_1"
    assert entry["overrode_stop"] is True and entry["recommendation"] == "stop" and entry["outcome"] == "repeat"


def test_accepting_a_stop_is_not_an_override(tmp_path):
    log = tmp_path / "decision_log.json"
    record_decision("run-1", _gate("stop"), approved=True, outcome="stop", log_path=log)
    [entry] = _entries(log)
    assert entry["overrode_stop"] is False and entry["overrides_recommendation"] is False


def test_accepts_the_orchestrator_gate_payload_dict(tmp_path):
    payload = {**_gate("repeat").model_dump(), "run_id": "run-1", "awaiting_founder": True, "stubbed": True}
    decision = record_decision("run-1", payload, approved=True, outcome="repeat", log_path=tmp_path / "log.json")
    assert decision.gate == "gate_1" and decision.phase == 1


@pytest.mark.parametrize("approved", [None, "yes", 1, 0, "true"])
def test_refuses_without_an_explicit_approve_or_reject(tmp_path, approved):
    log = tmp_path / "decision_log.json"
    with pytest.raises(MissingDecisionError):
        record_decision("run-1", _gate("go"), approved=approved, outcome="go", log_path=log)
    assert _entries(log) == []  # nothing is logged, so nothing can move on


@pytest.mark.parametrize("outcome", [None, "", "continue", "GO"])
def test_refuses_without_a_valid_outcome(tmp_path, outcome):
    log = tmp_path / "decision_log.json"
    with pytest.raises(MissingDecisionError):
        record_decision("run-1", _gate("go"), approved=True, outcome=outcome, log_path=log)
    assert _entries(log) == []


def test_approve_must_keep_and_reject_must_change_the_outcome(tmp_path):
    log = tmp_path / "decision_log.json"
    with pytest.raises(InconsistentDecisionError):
        record_decision("run-1", _gate("stop"), approved=True, outcome="go", log_path=log)
    with pytest.raises(InconsistentDecisionError):
        record_decision("run-1", _gate("stop"), approved=False, outcome="stop", log_path=log)
    assert _entries(log) == []


@pytest.mark.parametrize("run_id", ["", "  ", None])
def test_refuses_without_a_run_id(tmp_path, run_id):
    with pytest.raises(ValueError):
        record_decision(run_id, _gate("go"), approved=True, outcome="go", log_path=tmp_path / "log.json")


def test_refuses_without_a_gate_result(tmp_path):
    with pytest.raises(TypeError):
        record_decision("run-1", None, approved=True, outcome="go", log_path=tmp_path / "log.json")
