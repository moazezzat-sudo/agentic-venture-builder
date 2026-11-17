"""Intake: ask the founder only for the brief fields that are missing, then pause (interrupt) for the answers.

No model is used: the questions are fixed, so every founder is asked the same
thing and nothing is invented. The founder's answers are their own claims;
the skeptic and scorer treat them as claims, not facts.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from logger import log_action, write_output

QUESTIONS: dict[str, str] = {
    "skills": "Which of your skills does this idea need (for example design, coding, sales, teaching)?",
    "budget": "How much money can you put into building the first version?",
    "time_available": "How many hours a week can you work on this?",
    "location": "Which country or city will your first customers be in?",
    "target_market": "Who exactly is your first customer (their role, situation and what they use today)?",
    "has_team": "Do you have teammates? If yes, list their skills; if not, answer no.",
}
LIST_FIELDS = ("skills", "learned", "values", "team_skills")


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and not value)


def missing_fields(brief: dict[str, Any]) -> list[str]:
    """The intake fields the brief does not answer yet."""
    return [f for f in QUESTIONS if _empty(brief.get(f))]


def questions_for(brief: dict[str, Any]) -> list[dict[str, str]]:
    return [{"field": f, "question": QUESTIONS[f]} for f in missing_fields(brief)]


def apply_answers(brief: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Merge the founder's answers into a copy of the brief. Blank answers are ignored."""
    out = dict(brief)
    for field, raw in (answers or {}).items():
        answer = str(raw).strip()
        if field not in QUESTIONS or not answer:
            continue
        if field == "has_team":
            no_team = answer.lower() in ("no", "n", "none", "solo", "just me", "false")
            out["has_team"] = not no_team
            if not no_team:
                out["team_skills"] = [s.strip() for s in answer.split(",") if s.strip() and s.strip().lower() != "yes"]
        elif field in LIST_FIELDS:
            out[field] = [s.strip() for s in answer.split(",") if s.strip()]
        else:
            out[field] = answer
    return out


def node(state: dict[str, Any]) -> dict[str, Any]:
    brief = state["brief"]
    questions = questions_for(brief)
    answers: dict[str, Any] = {}
    if questions:
        # Pauses the run. Nothing above this line has side effects, because the node re-runs on resume.
        reply = interrupt({"kind": "questions", "stage": "intake", "questions": questions})
        answers = dict((reply or {}).get("answers") or {})
    new_brief = apply_answers(brief, answers)

    log_action(
        agent="intake", action="follow_up_questions" if questions else "brief_complete", model=None,
        asked=[q["field"] for q in questions], answered=sorted(k for k, v in answers.items() if str(v).strip()),
        still_missing=missing_fields(new_brief),
    )
    lines = [f"- **{k}**: {v}" for k, v in new_brief.items() if not _empty(v)]
    asked = "\n".join(f"- {q['question']} → {answers.get(q['field']) or '_no answer_'}" for q in questions) or "_None: the brief was complete._"
    write_output(1, 1, "intake", (
        "# Phase 1, step 1: founder brief\n\n"
        "Everything below is the founder's own statement. It is checked by the skeptic, not taken as fact.\n\n"
        + "\n".join(lines) + f"\n\n## Follow-up questions\n\n{asked}\n"
    ))
    return {
        "brief": new_brief,
        "founder_answers": {**(state.get("founder_answers") or {}), **{k: str(v) for k, v in answers.items()}},
        "clarifying_questions": [q["question"] for q in questions],
    }
