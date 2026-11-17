"""Runs the pipeline as a LangGraph graph and pauses at every gate for the founder.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from orchestrator import start_run, resume_run
    result = start_run(brief, run_id)                 # runs until the first gate
    result = resume_run(run_id, founder_decision)     # continues after the founder answers

Both return a dict. Check result["awaiting_founder"]:
  - True:  the run is paused at a gate. The dict is a GateResult (phase, gate,
           recommendation, reasons, target, evidence_summary, score) plus
           run_id and awaiting_founder. Show it, then call resume_run() with
           the founder's FounderDecision (approval.record_decision makes one).
  - False: the run has ended (stopped, or the phase is finished). The dict is
           the Briefcase state plus awaiting_founder.

Every result also carries "stubbed": True while this module is STUBBED.

STUBBED: the graph is not wired yet. start_run() and resume_run() return
placeholder values so the app can be built against the interface. They call
no model, do no research, and write nothing to outputs/ or decision_log.json.
"""

from __future__ import annotations

from typing import Any, Union

from schemas import Briefcase, FounderDecision, GateResult

STUBBED = True  # set to False once the real graph replaces the placeholder bodies

GATE_1 = "gate_1"
GATE_1_TARGET = (
    "At least 3 independent source URLs showing the pain; at least 50% of claims sourced; "
    "founder fit acceptable"
)


def _placeholder_gate(run_id: str, round_no: int = 1) -> dict[str, Any]:
    """A fake Gate 1 recommendation. STUBBED: nothing here comes from research."""
    gate = GateResult(
        phase=1,
        gate=GATE_1,
        recommendation="repeat",
        reasons=[
            "STUBBED: placeholder recommendation; no research or scoring has run.",
            f"STUBBED: coach round {round_no}.",
        ],
        target=GATE_1_TARGET,
        evidence_summary="STUBBED: no evidence collected.",
        score=None,
    )
    return {**gate.model_dump(), "run_id": run_id, "awaiting_founder": True, "stubbed": STUBBED}


def _placeholder_state(run_id: str, brief: dict[str, Any], **fields: Any) -> dict[str, Any]:
    state: Briefcase = {
        "run_id": run_id,
        "brief": brief,
        "claims": [],
        "gate_results": [],
        "founder_decisions": [],
        "current_phase": 1,
        "stopped": False,
    }
    state.update(fields)  # type: ignore[typeddict-item]
    return {**state, "awaiting_founder": False, "stubbed": STUBBED}


def _check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    return run_id.strip()


def start_run(brief: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Start a run from the founder's brief and run it until the first gate.

    Returns the gate payload (GateResult as a dict) when the run pauses for the
    founder, or the final state if the run ends before a gate (for example a
    banned product category).

    STUBBED: returns a placeholder Gate 1 payload.
    """
    run_id = _check_run_id(run_id)
    if not isinstance(brief, dict) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a dict with a non-empty 'idea'")
    return _placeholder_gate(run_id)


def resume_run(run_id: str, decision: Union[FounderDecision, dict[str, Any]]) -> dict[str, Any]:
    """Continue a paused run with the founder's decision at the current gate.

    The run never continues without a FounderDecision: anything else raises.
    Returns the next gate payload, or the final state when the run ends.

    STUBBED behaviour, so every app path can be exercised:
      - outcome "stop"            -> final state with stopped=True
      - outcome "repeat"/"pivot"  -> another placeholder Gate 1 payload (coach loop)
      - outcome "go"              -> final state with current_phase=2
    """
    run_id = _check_run_id(run_id)
    if isinstance(decision, dict):
        decision = FounderDecision(**decision)
    if not isinstance(decision, FounderDecision):
        raise TypeError("resume_run needs the founder's FounderDecision; the run cannot continue without it")

    decided = decision.model_dump()
    if decision.outcome == "stop":
        return _placeholder_state(run_id, {}, founder_decisions=[decided], stopped=True)
    if decision.outcome in ("repeat", "pivot"):
        return _placeholder_gate(run_id, round_no=2)
    return _placeholder_state(run_id, {}, founder_decisions=[decided], current_phase=2)


__all__ = ["start_run", "resume_run", "STUBBED"]
