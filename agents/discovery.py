"""Discovery conversation: Phase 1 starts here, before any research.

The founder sees "Here's what I understood" (a summary and five key assumptions: customer, problem,
current alternative, why now, how they'd pay) with questions, answers them (a second round only if
something is still vague, at most 2 rounds), then confirms with "Yes, that's my idea" or corrects it.
Only a confirmed understanding goes to research.

Uses Hashish's agents/questions.py (discovery_summary, discovery_questions) when it is on main; until
then, one small fast-model call per round (prompts/discovery.md). Three nodes, because a node re-runs
from the top on resume:
  prepare_node  -> the model call for this round (no pause)
  ask_node      -> pause (kind "questions", stage "discovery") with the summary and questions
  confirm_node  -> pause (stage "discovery_confirm") with the two choices; writes the confirmed brief

Question format (shared with the app and Hashish): {id, text, why, suggestions, choices or null}.
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.types import interrupt

from agents import intake
from agents._common import ask_json, brief_for_model, cut, model_fields, text_violations
from logger import log_action, write_output

ASSUMPTION_TYPES = ("customer", "problem", "current_alternative", "why_now", "payment")
ASSUMPTION_LABELS = {"customer": "Customer", "problem": "Problem", "current_alternative": "What they use now",
                     "why_now": "Why now", "payment": "How they'd pay"}
CONFIRM_YES, CONFIRM_NO = "Yes, that's my idea", "Not quite, let me correct it"
MAX_ROUNDS = 2  # question rounds; later passes only update the summary

# Fixed questions for founder fields the brief leaves out (feed founder fit and feasibility).
FIELD_CHOICES = {"has_team": ["No, just me", "Yes (list their skills)"]}


def _hashish():
    try:
        from agents import questions  # Hashish's module, when it lands
    except ImportError:
        return None
    ok = hasattr(questions, "discovery_summary") and hasattr(questions, "discovery_questions")
    return questions if ok else None


def question(qid: str, text: str, why: str = "", suggestions: Optional[list[str]] = None,
             choices: Optional[list[str]] = None) -> dict[str, Any]:
    return {"id": qid, "text": cut(text, 240), "why": cut(why, 200),
            "suggestions": [cut(s, 80) for s in (suggestions or []) if str(s).strip()][:3], "choices": choices}


def has_confirmed_understanding(brief: dict[str, Any]) -> bool:
    """A brief that already carries a confirmed understanding (a re-run) skips the conversation."""
    understood = brief.get("confirmed_understanding") or {}
    return isinstance(understood, dict) and all(str(understood.get(t, "")).strip() for t in ASSUMPTION_TYPES)


def _clean_assumptions(raw: Any) -> list[dict[str, str]]:
    by_type = {a.get("type"): a for a in (raw if isinstance(raw, list) else []) if isinstance(a, dict)}
    return [{"id": f"A{i + 1}", "type": t, "text": cut((by_type.get(t) or {}).get("text") or "Unclear: not stated yet.", 240)}
            for i, t in enumerate(ASSUMPTION_TYPES)]


def _clean_keywords(raw: Any, brief: dict[str, Any]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out = {k: cut(raw.get(k) or "", 60) for k in ("customer", "problem", "solution", "activity")}
    out["arabic"] = [cut(w, 40) for w in (raw.get("arabic") or []) if str(w).strip()][:5]
    if not out["customer"]:
        out["customer"] = cut(brief.get("target_market") or "", 60)
    return out


def _model_round(state: dict[str, Any], round_no: int) -> tuple[dict[str, Any], dict[str, Any]]:
    disc = state.get("discovery") or {}
    payload = {"brief": brief_for_model(state["brief"]), "round": round_no,
               "answers": disc.get("answers", []), "corrections": disc.get("corrections", [])}
    data, usage = ask_json("discovery", payload, role="fast", max_tokens=900, temperature=0,
                          expect=("summary", "assumptions", "keywords", "questions"))
    questions = []
    if round_no <= MAX_ROUNDS:
        for i, q in enumerate(data.get("questions") or []):
            if isinstance(q, dict) and str(q.get("text", "")).strip():
                questions.append(question(f"r{round_no}q{i + 1}", q["text"], q.get("why", ""), q.get("suggestions")))
    return {"summary": cut(data.get("summary") or "", 600), "assumptions": _clean_assumptions(data.get("assumptions")),
            "keywords": _clean_keywords(data.get("keywords"), state["brief"]), "questions": questions[:4]}, usage


def _hashish_round(module, state: dict[str, Any], round_no: int) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = module.discovery_summary(state) or {}
    questions = module.discovery_questions(state, round_no) if round_no <= MAX_ROUNDS else []
    usage = {"tokens": int(summary.get("tokens", 0) or 0), "cost": 0, "model": "agents.questions", "parsed": True}
    return {"summary": cut(summary.get("summary") or "", 600),
            "assumptions": _clean_assumptions(summary.get("assumptions")),
            "keywords": _clean_keywords(summary.get("keywords"), state["brief"]),
            "questions": [q for q in (questions or []) if isinstance(q, dict) and q.get("text")][:4]}, usage


def prepare_node(state: dict[str, Any]) -> dict[str, Any]:
    disc = dict(state.get("discovery") or {"round": 0, "answers": [], "corrections": []})
    round_no = int(disc.get("round", 0)) + 1
    module = _hashish()
    result, usage = _hashish_round(module, state, round_no) if module else _model_round(state, round_no)
    if round_no == 1:
        # Founder fields the brief leaves out, with fixed wording (they feed founder fit and feasibility).
        result["questions"] += [question(f, intake.QUESTIONS[f], "Feeds the founder-fit and feasibility scores.",
                                         choices=FIELD_CHOICES.get(f)) for f in intake.missing_fields(state["brief"])]
        if not result["questions"]:  # the model gave none and the brief is complete: ask about the weakest assumption
            weakest = next((a for a in result["assumptions"] if a["text"].startswith("Unclear")), result["assumptions"][1])
            result["questions"] = [question("r1q1", f"{ASSUMPTION_LABELS[weakest['type']]}: is this right? {weakest['text']}",
                                            "Research starts from this.")]
    disc.update(result, round=round_no)
    log_action(agent="discovery", action=f"discovery_round_{round_no}", run_id=state.get("run_id"),
               source="agents.questions" if module else "fallback", questions=len(result["questions"]),
               **model_fields(usage))
    return {"discovery": disc, "tokens": usage.get("tokens", 0)}


def after_prepare(state: dict[str, Any]) -> str:
    disc = state.get("discovery") or {}
    return "discovery_ask" if disc.get("questions") and disc.get("round", 1) <= MAX_ROUNDS else "discovery_confirm"


def _summary_payload(disc: dict[str, Any]) -> dict[str, Any]:
    return {"text": disc.get("summary", ""), "assumptions": disc.get("assumptions", [])}


def ask_node(state: dict[str, Any]) -> dict[str, Any]:
    disc = dict(state["discovery"])
    reply = interrupt({"kind": "questions", "stage": "discovery", "round": disc["round"],
                       "summary": _summary_payload(disc), "questions": disc["questions"]}) or {}
    answers = {k: str(v).strip() for k, v in (reply.get("answers") or {}).items() if str(v).strip()}
    asked = {q["id"]: q["text"] for q in disc["questions"]}
    disc["answers"] = [*disc.get("answers", []), *({"question": asked.get(k, k), "answer": v} for k, v in answers.items())]
    brief = intake.apply_answers(state["brief"], {k: v for k, v in answers.items() if k in intake.QUESTIONS})
    if answers.get("has_team", "").lower().startswith("no"):
        brief["has_team"] = False
    violations = text_violations({f"founder answer: {k}": v for k, v in answers.items()}, False, state.get("round", 1))
    log_action(agent="discovery", action=f"discovery_answers_round_{disc['round']}", model=None,
               run_id=state.get("run_id"), answered=sorted(answers), guardrail_violations=[v["rule"] for v in violations])
    return {"discovery": disc, "brief": brief, "text_violations": violations,
            "founder_answers": {**(state.get("founder_answers") or {}), **answers}}


def confirm_node(state: dict[str, Any]) -> dict[str, Any]:
    disc = dict(state["discovery"])
    questions = [question("confirm", "Is this your idea?", "Only a confirmed understanding goes to research.",
                          choices=[CONFIRM_YES, CONFIRM_NO]),
                 question("correction", "If not, what should change?", "Your correction updates the summary.")]
    reply = interrupt({"kind": "questions", "stage": "discovery_confirm", "round": disc["round"],
                       "summary": _summary_payload(disc), "questions": questions}) or {}
    answers = reply.get("answers") or {}
    confirmed = str(answers.get("confirm", "")).strip() == CONFIRM_YES
    correction = str(answers.get("correction", "")).strip()
    if not confirmed:
        disc["corrections"] = [*disc.get("corrections", []), correction or "The founder said the summary is not quite right."]
        disc["confirmed"] = False
        log_action(agent="discovery", action="discovery_corrected", model=None, run_id=state.get("run_id"),
                   approved_by="founder")
        return {"discovery": disc}

    disc["confirmed"] = True
    understood = {a["type"]: a["text"] for a in disc.get("assumptions", [])}
    brief = {**state["brief"], "confirmed_understanding": understood, "keywords": disc.get("keywords", {}),
             "discovery_summary": disc.get("summary", ""),
             "discovery_answers": [f"{a['question']} {a['answer']}" for a in disc.get("answers", [])]}
    if not brief.get("target_market") and understood.get("customer"):
        brief["target_market"] = understood["customer"]
    log_action(agent="discovery", action="discovery_confirmed", model=None, run_id=state.get("run_id"),
               approved_by="founder", rounds=disc.get("round"))
    write_discovery(disc, brief)
    return {"discovery": disc, "brief": brief}


def after_confirm(state: dict[str, Any]) -> str:
    return "category_recheck" if (state.get("discovery") or {}).get("confirmed") else "discovery_prepare"


def write_discovery(disc: dict[str, Any], brief: dict[str, Any]) -> None:
    rows = "\n".join(f"| {ASSUMPTION_LABELS[a['type']]} | {a['text']} |" for a in disc.get("assumptions", []))
    qa = "\n".join(f"- {a['question']} → {a['answer']}" for a in disc.get("answers", [])) or "_No answers given._"
    corrections = "\n".join(f"- {c}" for c in disc.get("corrections", [])) or "_None._"
    kw = disc.get("keywords", {})
    keywords = ", ".join(f"{k}: {v}" for k, v in kw.items() if k != "arabic" and v)
    arabic = ", ".join(kw.get("arabic") or []) or "none"
    write_output(1, 1, "discovery", (
        "# Phase 1, step 1: discovery (confirmed by the founder)\n\n"
        "Everything below is the founder's own statement, as understood and confirmed. It is checked against "
        "research, not taken as fact.\n\n"
        f"## Here's what I understood\n\n{disc.get('summary', '')}\n\n"
        f"## Key assumptions (all ASSUMPTION until research)\n\n| | |\n|---|---|\n{rows}\n\n"
        f"## Questions and answers ({disc.get('round', 1)} round(s))\n\n{qa}\n\n## Corrections\n\n{corrections}\n\n"
        f"## Search keywords\n\n{keywords}\n\nArabic: {arabic}\n"
    ))


def skip_node(state: dict[str, Any]) -> dict[str, Any]:
    """The brief arrived with a confirmed understanding (a re-run): no conversation."""
    log_action(agent="discovery", action="discovery_already_confirmed", model=None, run_id=state.get("run_id"))
    understood = state["brief"]["confirmed_understanding"]
    disc = {"round": 0, "confirmed": True, "summary": state["brief"].get("discovery_summary", ""),
            "assumptions": [{"id": f"A{i + 1}", "type": t, "text": understood[t]} for i, t in enumerate(ASSUMPTION_TYPES)],
            "keywords": state["brief"].get("keywords", {}), "answers": [], "corrections": []}
    write_discovery(disc, state["brief"])
    return {"discovery": disc}
