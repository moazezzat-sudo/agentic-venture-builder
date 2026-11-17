"""Founder approval at every gate. Nothing moves on without an explicit decision.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from approval import record_decision
    decision = record_decision(run_id, gate_result, approved=True, outcome="go", note="")
    result = orchestrator.resume_run(run_id, decision)

gate_result is the GateResult the gate recommended (a GateResult or the gate
payload dict that orchestrator.start_run / resume_run returns).
approved is the founder's answer to the recommendation: True accepts it,
False rejects it. outcome is what the founder chose (go / repeat / pivot /
stop). When outcome differs from the recommendation, overrides_recommendation
is set, so a founder overriding a stop is visible in the log and gate file.

The returned FounderDecision is appended to decision_log.json with
approved_by="founder". Anything other than an explicit True/False answer and
a valid outcome raises, so the run cannot continue without the founder.

STUBBED: the decision is validated and returned but not yet written to
decision_log.json.
"""

from __future__ import annotations

from typing import Any, Union, get_args

from schemas import FounderDecision, GateResult, Outcome

STUBBED = True  # set to False once decisions are logged to decision_log.json

OUTCOMES: tuple[str, ...] = get_args(Outcome)


class MissingDecisionError(ValueError):
    """Raised when there is no explicit founder decision to record."""


def record_decision(
    run_id: str,
    gate_result: Union[GateResult, dict[str, Any]],
    approved: bool,
    outcome: str,
    note: str = "",
) -> FounderDecision:
    """Record the founder's approve/reject at a gate and return the FounderDecision.

    Raises MissingDecisionError unless approved is exactly True or False and
    outcome is one of go / repeat / pivot / stop.

    STUBBED: does not write to decision_log.json yet.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if isinstance(gate_result, dict):
        gate_result = GateResult(**gate_result)
    if not isinstance(gate_result, GateResult):
        raise TypeError("gate_result must be the GateResult the gate recommended")
    if approved is not True and approved is not False:
        raise MissingDecisionError("the founder must explicitly approve (True) or reject (False)")
    if outcome not in OUTCOMES:
        raise MissingDecisionError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")

    return FounderDecision(
        phase=gate_result.phase,
        gate=gate_result.gate,
        approved=approved,
        outcome=outcome,  # type: ignore[arg-type]
        note=note or "",
        overrides_recommendation=outcome != gate_result.recommendation,
    )


__all__ = ["record_decision", "MissingDecisionError", "OUTCOMES", "STUBBED"]
