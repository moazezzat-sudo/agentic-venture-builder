"""Coach: after the founder picks repeat or pivot, propose the next attempt and ask the founder questions.

Two nodes, because a node re-runs from the top when the run resumes:
  node          -> one model call, logged, written to outputs (no pause)
  answers_node  -> pauses (interrupt) for the founder's answers and their
                   accept/reject of a revised idea, then starts the next round
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agents._common import ask_json, brief_for_model, cut, model_fields, text_violations, write_interview_kit
from logger import log_action, write_output


def _strings(raw: Any, limit: int, size: int = 160) -> list[str]:
    return [cut(s, size) for s in (raw if isinstance(raw, list) else []) if str(s).strip()][:limit]


# One question per evidence type the research left weak: the founder may know where that evidence is.
MISSING_QUESTIONS = {
    "pain": ("Who have you heard describe this problem, and in what words? Name the groups, forums or people.",
             "Problem evidence is thin: real people describing the pain would raise it."),
    "competitors": ("What do your customers use today instead, and what does it cost them?",
                    "No clear competitor evidence was found."),
    "pricing": ("Has anyone paid, or offered to pay, for something like this? How much?",
                "There is no evidence yet that people pay for this kind of product."),
    "market": ("How many of your customers are there where you will launch, and where does that number come from?",
               "No official figure sizes the market yet."),
}


def missing_evidence_types(state: dict[str, Any]) -> list[str]:
    """Evidence types the gate found weak: score 1 or less, no claim cited, or search unreachable."""
    from agents.scorer import CITABLE

    scores, cited = state.get("scores") or {}, state.get("score_claims") or {}
    missing = [CITABLE[c][0] for c in CITABLE if scores.get(c, 0) <= 1 or not cited.get(c)]
    gaps = [g.get("focus") for g in state.get("search_gaps") or [] if g.get("round") == state.get("round", 1)]
    return [t for t in dict.fromkeys(missing + gaps) if t in MISSING_QUESTIONS]


def _question(qid: str, text: str, why: str = "", choices: Any = None) -> dict[str, Any]:
    return {"id": qid, "text": cut(text, 240), "why": cut(why, 200), "suggestions": [], "choices": choices}


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
        "missing_evidence_types": missing_evidence_types(state),
    }
    data, usage = ask_json("coach", payload, role="smart", max_tokens=700)
    idea = state["brief"].get("idea", "")
    revised = cut(data.get("revised_idea") or idea, 400) if outcome == "pivot" else idea
    audience = state["brief"].get("target_market") or revised
    kit = write_interview_kit(data.get("interview_questions"), f"{audience} (idea: {revised})", outcome)
    missing = payload["missing_evidence_types"]
    questions = [_question(f"coach_{t}", *MISSING_QUESTIONS[t]) for t in missing[:3]]
    questions += [_question(f"coach_{i + 1}", q) for i, q in enumerate(_strings(data.get("questions"), 2))]
    first = missing[0] if missing and missing[0] != "market" else "pain"
    notes = {
        "outcome": outcome,
        "revised_idea": revised,
        "missing_evidence": _strings(data.get("missing_evidence"), 3),
        "missing_evidence_types": missing,
        "queries": _strings(data.get("queries"), 3, 120),
        # The coach's queries join the next search plan, aimed at the first missing evidence type.
        "search": [{"evidence_type": first, "query": q} for q in _strings(data.get("queries"), 3, 120)],
        "questions": [q["text"] for q in questions],
        "question_items": questions[:4],
    }

    log_action(agent="coach", action=f"coach_{outcome}", run_id=state.get("run_id"), round=state.get("round", 1),
               missing_evidence_types=missing, **model_fields(usage))
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs) or "- _none_"  # noqa: E731
    write_output(1, 7, "coach", (
        f"# Phase 1, step 7: coach after Gate 1 ({outcome}, round {state.get('round', 1)})\n\n"
        f"## Idea for the next round\n\n{revised}\n\n"
        f"## Missing evidence\n\nWeak evidence types: {', '.join(missing) or 'none'}.\n\n{bullets(notes['missing_evidence'])}\n\n"
        f"## New search queries\n\n{bullets(notes['queries'])}\n\n## Questions for the founder\n\n{bullets(notes['questions'])}\n"
    ))
    return {"coach_notes": notes, "interview_kit": kit, "tokens": usage["tokens"]}


def answers_node(state: dict[str, Any]) -> dict[str, Any]:
    notes = state["coach_notes"]
    questions = notes.get("question_items") or [_question(f"coach_{i + 1}", q) for i, q in enumerate(notes["questions"])]
    pivot = notes["outcome"] == "pivot"
    reply = interrupt({
        "kind": "questions", "stage": "coach", "outcome": notes["outcome"], "questions": questions,
        "missing_evidence_types": notes.get("missing_evidence_types", []),
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
                                  *(f"{q['text']} {answers[q['id']]}" for q in questions if q["id"] in answers)]

    next_round = state.get("round", 1) + 1
    violations = text_violations({f"founder answer: {k}": v for k, v in answers.items()}, False, next_round)
    log_action(
        agent="coach", action="start_next_round", model=None, run_id=state.get("run_id"),
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
