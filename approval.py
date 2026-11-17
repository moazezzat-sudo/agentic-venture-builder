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

Every decision is appended to decision_log.json with approved_by="founder",
the recommendation, the founder's outcome and note. A founder overriding a
stop is recorded with overrode_stop=True so the app and the gate file can
show it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union, get_args

from logger import log_action
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
    log_path: Optional[Path] = None,
) -> FounderDecision:
    """Validate the founder's approve/reject at a gate, log it, and return the FounderDecision.

    log_path overrides decision_log.json (for tests).
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

    overrides = outcome != gate.recommendation
    decision = FounderDecision(
        phase=gate.phase,
        gate=gate.gate,
        approved=approved,
        outcome=outcome,  # type: ignore[arg-type]
        note=(note or "").strip(),
        overrides_recommendation=overrides,
    )
    log_action(
        agent="founder",
        action=f"{'approve' if approved else 'reject'}_{gate.gate}",
        sources=[],
        model=None,
        cost=0,
        approved_by="founder",
        log_path=log_path,
        run_id=run_id.strip(),
        phase=gate.phase,
        gate=gate.gate,
        recommendation=gate.recommendation,
        outcome=decision.outcome,
        overrides_recommendation=overrides,
        overrode_stop=gate.recommendation == "stop" and outcome != "stop",
        note=decision.note,
    )
    return decision


__all__ = ["record_decision", "MissingDecisionError", "InconsistentDecisionError", "OUTCOMES", "STUBBED"]
