"""Founder approval at every gate. Nothing moves on without an explicit decision.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from approval import record_decision
    decision = record_decision(run_id, gate_result, approved=True, outcome="go", note="")
    result = orchestrator.resume_run(run_id, decision)

gate_result is what the gate recommended: a GateResult, or the gate payload
dict that orchestrator.start_run / resume_run returns.

The founder either approves the recommendation or rejects it and picks
another outcome (PLAN.md section 4):
  - approved=True   -> outcome must equal the recommendation
  - approved=False  -> outcome must be a different one of go / repeat / pivot / stop

Anything else raises MissingDecisionError (no explicit True/False, an unknown
outcome) or InconsistentDecisionError (an "approval" that changes the outcome,
a "rejection" that keeps it), so the run cannot continue on an unclear answer.

record_decision only validates and builds the FounderDecision; it writes
nothing. The decision is logged once, by the gate node in orchestrator.py, at
the moment it takes effect (after checking it is for the gate the run is
waiting at): one decision_log.json entry "<gate>_founder_decision" with
approved_by="founder" (team decision, 16:00). A decision that is built but
never sent to the run therefore leaves no trace and moves nothing.
"""

from __future__ import annotations

from typing import Any, Union, get_args

from schemas import FounderDecision, GateResult, Outcome

STUBBED = False

OUTCOMES: tuple[str, ...] = get_args(Outcome)


class MissingDecisionError(ValueError):
    """Raised when there is no explicit founder decision to record."""


class InconsistentDecisionError(ValueError):
    """Raised when approved/outcome contradict each other."""


def _as_gate_result(gate_result: Union[GateResult, dict[str, Any]]) -> GateResult:
    if isinstance(gate_result, GateResult):
        return gate_result
    if isinstance(gate_result, dict):
        return GateResult(**gate_result)  # extra keys such as run_id / awaiting_founder are ignored
    raise TypeError("gate_result must be the GateResult the gate recommended")


def record_decision(
    run_id: str,
    gate_result: Union[GateResult, dict[str, Any]],
    approved: bool,
    outcome: str,
    note: str = "",
) -> FounderDecision:
    """Validate the founder's approve/reject at a gate and return the FounderDecision.

    Writes nothing: the gate node logs the decision when the run resumes with it.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    gate = _as_gate_result(gate_result)
    if approved is not True and approved is not False:
        raise MissingDecisionError("the founder must explicitly approve (True) or reject (False)")
    if outcome not in OUTCOMES:
        raise MissingDecisionError(f"the founder must choose an outcome from {OUTCOMES}, got {outcome!r}")
    if approved and outcome != gate.recommendation:
        raise InconsistentDecisionError(
            f"approving means accepting the recommendation {gate.recommendation!r}; "
            f"to choose {outcome!r} instead, reject it"
        )
    if not approved and outcome == gate.recommendation:
        raise InconsistentDecisionError(
            f"rejecting the recommendation {gate.recommendation!r} needs a different outcome"
        )

    return FounderDecision(
        phase=gate.phase,
        gate=gate.gate,
        approved=approved,
        outcome=outcome,  # type: ignore[arg-type]
        note=(note or "").strip(),
        overrides_recommendation=outcome != gate.recommendation,
    )


__all__ = ["record_decision", "MissingDecisionError", "InconsistentDecisionError", "OUTCOMES", "STUBBED"]
