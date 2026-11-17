"""Coach: after the founder picks repeat or pivot, propose the next attempt and ask the founder questions.

Two nodes, because a node re-runs from the top when the run resumes:
  node          -> one model call, logged, written to outputs (no pause)
  answers_node  -> pauses (interrupt) for the founder's answers and their
                   accept/reject of a revised idea, then starts the next round
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agents._common import ask_json, brief_for_model, cut, text_violations, write_interview_kit
from logger import log_action, write_output


def _strings(raw: Any, limit: int, size: int = 160) -> list[str]:
    return [cut(s, size) for s in (raw if isinstance(raw, list) else []) if str(s).strip()][:limit]


def node(state: dict[str, Any]) -> dict[str, Any]:
    decision = state["founder_decisions"][-1]
    gate = state["gate_results"][-1]
    outcome = decision["outcome"]
    payload = {
        "brief": brief_for_model(state["brief"]),
        "choice": outcome,
        "gate_reasons": gate.get("reasons", []),
        "scores": state.get("scores", {}),
        "score_reasons": state.get("score_notes", {}),
        "founder_note": decision.get("note", ""),
    }
    data, usage = ask_json("coach", payload, role="smart", max_tokens=700)
    idea = state["brief"].get("idea", "")
    revised = cut(data.get("revised_idea") or idea, 400) if outcome == "pivot" else idea
    audience = state["brief"].get("target_market") or revised
    kit = write_interview_kit(data.get("interview_questions"), f"{audience} (idea: {revised})", outcome)
    notes = {
        "outcome": outcome,
        "revised_idea": revised,
        "missing_evidence": _strings(data.get("missing_evidence"), 3),
        "queries": _strings(data.get("queries"), 3, 120),
        "questions": _strings(data.get("questions"), 3),
    }

    log_action(agent="coach", action=f"coach_{outcome}", model=usage["model"], cost=usage["cost"],
               tokens=usage["tokens"], round=state.get("round", 1))
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs) or "- _none_"  # noqa: E731
    write_output(1, 7, "coach", (
        f"# Phase 1, step 7: coach after Gate 1 ({outcome}, round {state.get('round', 1)})\n\n"
        f"## Idea for the next round\n\n{revised}\n\n## Missing evidence\n\n{bullets(notes['missing_evidence'])}\n\n"
        f"## New search queries\n\n{bullets(notes['queries'])}\n\n## Questions for the founder\n\n{bullets(notes['questions'])}\n"
    ))
    return {"coach_notes": notes, "interview_kit": kit, "tokens": usage["tokens"]}


def answers_node(state: dict[str, Any]) -> dict[str, Any]:
    notes = state["coach_notes"]
    questions = [{"field": f"coach_{i + 1}", "question": q} for i, q in enumerate(notes["questions"])]
    pivot = notes["outcome"] == "pivot"
    reply = interrupt({
        "kind": "questions", "stage": "coach", "outcome": notes["outcome"], "questions": questions,
        "revised_idea": notes["revised_idea"] if pivot else None,
        "needs_accept_revised_idea": pivot,
    }) or {}
    answers = {k: str(v).strip() for k, v in (reply.get("answers") or {}).items() if str(v).strip()}
    accepted = bool(pivot and reply.get("accept_revised_idea") is True)

    brief = dict(state["brief"])
    if accepted:
        brief["previous_ideas"] = [*brief.get("previous_ideas", []), brief.get("idea", "")]
        brief["idea"] = notes["revised_idea"]
    if answers:
        brief["coach_answers"] = [*brief.get("coach_answers", []),
                                  *(f"{q['question']} {answers[q['field']]}" for q in questions if q["field"] in answers)]

    next_round = state.get("round", 1) + 1
    violations = text_violations({f"founder answer: {k}": v for k, v in answers.items()}, False, next_round)
    log_action(
        agent="coach", action="start_next_round", model=None,
        approved_by="founder" if accepted else None, accepted_revised_idea=accepted,
        answered=sorted(answers), round=next_round, guardrail_violations=[v["rule"] for v in violations],
    )
    return {
        "text_violations": violations,
        "brief": brief,
        "founder_answers": {**(state.get("founder_answers") or {}), **answers},
        "round": next_round,
        # A pivot is a new idea: only evidence gathered from the next round on counts for it.
        "evidence_from_round": next_round if accepted else state.get("evidence_from_round", 1),
    }
