"""Discovery conversation: what the system understood, the riskiest assumptions, and the questions to ask.

    from agents.questions import discovery_summary, discovery_questions, intake_questions, coach_questions
    discovery_summary(briefcase)        -> {"summary": str, "assumptions": [{"id", "text", "type"}], "source": "model" | "fallback"}
    discovery_questions(briefcase, 1)   -> [question, ...]  (3-5)
    intake_questions(brief)             -> [question, ...]  fixed questions for missing brief fields
    coach_questions(briefcase)          -> [question, ...]  after repeat/pivot: the missing evidence and the lowest criteria

A question is {"id", "text", "why", "suggestions": [2-3 strings], "choices": [..] or None}.

Model calls are small (local model): JSON mode and temperature 0 through agents._common.invoke_model,
one filled-in example per prompt, the reply shape repeated at the end of the user message (small
models otherwise echo the input), "</think>" stripped, one retry when required keys are missing,
and every text checked with guardrails.check_text. Questions follow The Mom Test: past behaviour,
never "would you use it". If the model fails, fixed fallbacks are used, and "source" says so.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import agents._common as common

# The same five types as agents/discovery.py, which maps assumptions by type.
ASSUMPTION_TYPES = ("customer", "problem", "current_alternative", "why_now", "payment")
HYPOTHETICAL = re.compile(r"\b(would|will|could) you\b|\bif (we|you|there) (built|made|had|offered)\b|\bwould .{0,20}\b(use|pay|buy)\b", re.I)

SUMMARY_SYSTEM = """You restate a founder's idea plainly, then list its riskiest assumptions. No praise, no promises, no invented numbers.
Reply with JSON only. Example for a different idea:
{"summary":"Small bakeries in Alexandria lose orders when customers can't reach them by phone. Today they take orders on WhatsApp by hand. The founder proposes a simple order form that sends each order to WhatsApp. Bakeries would pay a monthly fee.","assumptions":[{"text":"Owners of small bakeries in Alexandria","type":"customer"},{"text":"They lose orders when nobody answers the phone","type":"problem"},{"text":"Orders taken by hand on WhatsApp","type":"current_alternative"},{"text":"More customers now order by message than by phone","type":"why_now"},{"text":"A monthly fee per bakery","type":"payment"}],"keywords":{"customer":"bakery owners","problem":"lost phone orders","solution":"online order form","activity":"bakery","arabic":["مخبز","طلبات"]}}
summary: 3-4 sentences: who has what problem, what they do today, what the founder proposes, how they would pay. Say "not stated" for anything the brief doesn't say.
assumptions: one per type: customer, problem, current_alternative, why_now, payment. Write "Unclear: not stated yet." when the brief doesn't say.
keywords: short search words for the customer, the problem, the solution and the activity (e.g. "football" for a football idea), plus up to 5 Arabic search words."""

QUESTIONS_SYSTEM = """You write the founder's next discovery questions, in the style of The Mom Test: ask about past behaviour and facts, never "would you use it" or "would you pay".
Target what is vague or missing in the brief and the riskiest assumptions. Make each question specific to this idea and location.
Reply with JSON only. Example for a different idea:
{"questions":[{"text":"When did a bakery you know last lose an order because nobody answered the phone?","why":"Tests whether the problem happens often enough to matter.","suggestions":["Last week, during the Friday rush","I don't know of a case yet"],"choices":null}]}
Write 3-5 questions. Each has "why" (one sentence) and 2-3 short "suggestions" the founder can click as answers. "choices" is a short list only when the answer is one of a few options, else null."""

FALLBACK_QUESTIONS = [
    {"text": "When did someone in your target group last run into this problem? What happened?",
     "why": "Shows whether the problem is real and recent, not hypothetical.",
     "suggestions": ["This week", "I haven't seen it happen myself yet"]},
    {"text": "What do they use or do about it today, and what does that cost them in time or money?",
     "why": "The current workaround is your real competition and the base for any price.",
     "suggestions": ["They do it by hand", "They use a free app", "They pay someone"]},
    {"text": "Who have you already talked to about this problem, and what did they say?",
     "why": "Past conversations are evidence; opinions about a future product are not.",
     "suggestions": ["Nobody yet", "A few friends", "Five or more people in the target group"]},
    {"text": "Have any of them paid for something to solve this before? What and how much?",
     "why": "Past spending is the best sign of willingness to pay.",
     "suggestions": ["Yes, a paid tool", "No, nothing paid", "I don't know"]},
]

EVIDENCE_QUESTIONS = {
    "problem_evidence": ("Where do people in your target group talk about this problem (forums, groups, reviews)? Paste a link if you have one.",
                         "Problem evidence scored low: independent sources showing the pain would raise it.",
                         ["A Facebook group", "A Reddit thread", "I haven't looked yet"]),
    "market": ("How many people or businesses in your location have this problem? Where does that number come from?",
               "Market scored low: only official or primary numbers count.", ["A government statistic", "I don't know yet"]),
    "competition": ("What do people use today instead of your product? Name the tools or services.",
                    "Competition scored low or had no evidence: we need the real alternatives.", ["A free app", "Spreadsheets or WhatsApp", "Nothing"]),
    "willingness_to_pay": ("What have people in your target group paid for a similar solution? Link a price page if you can.",
                           "Willingness to pay scored low: real prices are the evidence.", ["A competitor's price page", "Nobody pays for this today"]),
    "founder_fit": ("Which skills does building this need that you or your team don't have yet?",
                    "Founder fit scored low: the gap decides who you need.", ["Coding", "Design", "Sales"]),
    "feasibility": ("What is the smallest version you could build in the time and budget you have?",
                    "Feasibility scored low: a smaller first version may fit.", ["A landing page and a form", "A spreadsheet template"]),
    "rules_risk": ("Is there any rule, licence or consent you'd need in your location for this? Where would you check?",
                   "Rules and risk scored low: it needs an official source.", ["A government website", "I don't know yet"]),
}


# --------------------------------------------------------------------------- model call


def _strip(text: str) -> str:
    text = str(text or "")
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text


def ask(agent: str, system: str, payload: dict[str, Any], shape: str, required: tuple[str, ...],
        max_tokens: int = 600) -> tuple[dict[str, Any], dict[str, Any]]:
    """One small JSON call; one retry if the reply is not JSON or lacks a required key."""
    user = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + f"\n\nReply now with JSON only, in this shape: {shape}. Do not repeat the input.")
    tokens, cost, model, data = 0, 0.0, None, {}
    for attempt in range(2):
        note = "" if attempt == 0 else f"\n\n{common.RETRY_NOTE}"
        try:
            text, t, c, model = common.invoke_model(agent, system, user + note, role="fast", max_tokens=max_tokens, temperature=0)
        except Exception as exc:  # the model is down or failed: the caller's fixed fallback takes over
            return {}, {"tokens": tokens, "cost": cost, "model": model, "parsed": False, "retried": attempt > 0,
                        "error": type(exc).__name__}
        tokens, cost = tokens + t, cost + c
        data = common.parse_json(_strip(text))
        if data and all(k in data for k in required):
            return data, {"tokens": tokens, "cost": cost, "model": model, "parsed": True, "retried": attempt > 0}
    return {}, {"tokens": tokens, "cost": cost, "model": model, "parsed": False, "retried": True}


def _clean(text: Any, limit: int = 300) -> str:
    return common.cut(str(text or "").strip(), limit)


def _ok(text: str) -> bool:
    from guardrails import check_text

    return bool(text) and not check_text(text)


def _payload(state: dict[str, Any]) -> dict[str, Any]:
    disc = state.get("discovery") or {}
    return {"brief": common.brief_for_model(state.get("brief") or {}),
            "founder_answers": state.get("founder_answers") or {},
            "answers": disc.get("answers") or [], "corrections": disc.get("corrections") or [],
            "feedback": state.get("feedback") or None}


# --------------------------------------------------------------------------- summary


def _fallback_summary(state: dict[str, Any]) -> dict[str, Any]:
    b = state.get("brief") or {}
    who = b.get("target_market") or "the target customer (not stated)"
    where = b.get("location") or "a location not stated"
    summary = (f"{who} in {where} has the problem this idea addresses; the brief doesn't say how often or how costly it is. "
               "What they do about it today is not stated. "
               f"The founder proposes: {_clean(b.get('idea'), 200)}. How customers would pay is not stated.")
    assumptions = [
        {"text": f"{who} in {where}", "type": "customer"},
        {"text": f"{who} has this problem often enough to look for a solution", "type": "problem"},
        {"text": "Unclear: not stated yet.", "type": "current_alternative"},
        {"text": "Unclear: not stated yet.", "type": "why_now"},
        {"text": "Unclear: not stated yet.", "type": "payment"},
    ]
    stop = {"from", "with", "that", "this", "their", "for"}
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", str(b.get("idea", ""))) if w.lower() not in stop]
    keywords = {"customer": common.cut(b.get("target_market") or "", 60), "problem": "", "solution": " ".join(words[:5]),
                "activity": " ".join(words[:2]), "arabic": []}
    return {"summary": summary, "assumptions": [{"id": f"A{i}", **a} for i, a in enumerate(assumptions, 1)],
            "keywords": keywords, "source": "fallback"}


def discovery_summary(state: dict[str, Any]) -> dict[str, Any]:
    """3-4 plain sentences and the 4-6 riskiest assumptions. Falls back to a template."""
    data, usage = ask("discovery", SUMMARY_SYSTEM, _payload(state),
                      '{"summary":"...","assumptions":[{"text":"...","type":"customer"}],'
                      '"keywords":{"customer":"...","problem":"...","solution":"...","activity":"...","arabic":[]}}',
                      ("summary", "assumptions"))
    summary = _clean(data.get("summary"), 700)
    assumptions = []
    for a in data.get("assumptions") if isinstance(data.get("assumptions"), list) else []:
        text = _clean(a.get("text") if isinstance(a, dict) else a, 200)
        kind = a.get("type") if isinstance(a, dict) else None
        if kind in ASSUMPTION_TYPES and _ok(text) and kind not in [x["type"] for x in assumptions]:
            assumptions.append({"id": f"A{len(assumptions) + 1}", "text": text, "type": kind})
    kw = data.get("keywords") if isinstance(data.get("keywords"), dict) else {}
    keywords = {k: _clean(kw.get(k), 60) for k in ("customer", "problem", "solution", "activity")}
    arabic = kw.get("arabic") if isinstance(kw.get("arabic"), list) else []
    keywords["arabic"] = [_clean(w, 40) for w in arabic if str(w).strip()][:5]
    if not _ok(summary) or len(assumptions) < 4:
        result = _fallback_summary(state)
    else:
        result = {"summary": summary, "assumptions": assumptions, "keywords": keywords, "source": "model"}
    result["usage"] = usage
    return result


# --------------------------------------------------------------------------- questions


def _question(qid: str, text: Any, why: Any, suggestions: Any, choices: Any = None) -> Optional[dict[str, Any]]:
    text, why = _clean(text, 240), _clean(why, 200)
    sugg = [_clean(s, 80) for s in (suggestions if isinstance(suggestions, list) else []) if str(s or "").strip()][:3]
    opts = [_clean(c, 60) for c in choices if str(c or "").strip()] if isinstance(choices, list) and choices else None
    if not text or not why or HYPOTHETICAL.search(text):
        return None
    if not all(_ok(t) for t in [text, why, *sugg, *(opts or [])]):
        return None
    return {"id": qid, "text": text, "why": why, "suggestions": sugg, "choices": opts}


def _fill(questions: list[dict[str, Any]], pool: list[dict[str, Any]], prefix: str, minimum: int = 3) -> list[dict[str, Any]]:
    for q in pool:
        if len(questions) >= minimum:
            break
        made = _question(f"{prefix}{len(questions) + 1}", q["text"], q["why"], q["suggestions"], q.get("choices"))
        if made and all(made["text"] != x["text"] for x in questions):
            questions.append(made)
    return questions


def discovery_questions(state: dict[str, Any], round_no: int = 1) -> list[dict[str, Any]]:
    """3-5 Mom Test questions for this idea; hypothetical or unsafe ones are dropped; fallbacks fill the gap."""
    summary = state.get("discovery") or {}
    payload = {**_payload(state), "round": round_no, "assumptions": [a.get("text") for a in summary.get("assumptions") or []]}
    data, _ = ask("discovery", QUESTIONS_SYSTEM, payload,
                  '{"questions":[{"text":"...","why":"...","suggestions":["...","..."],"choices":null}]}', ("questions",))
    prefix = f"Q{round_no}_"
    questions: list[dict[str, Any]] = []
    for q in data.get("questions") if isinstance(data.get("questions"), list) else []:
        if not isinstance(q, dict):
            continue
        made = _question(f"{prefix}{len(questions) + 1}", q.get("text"), q.get("why"), q.get("suggestions"), q.get("choices"))
        if made:
            questions.append(made)
        if len(questions) == 5:
            break
    # After round 1, a valid reply with no questions means there is nothing left to ask: the
    # conversation moves on to confirmation. Fallbacks fill in only in round 1 or when the call failed.
    if data and round_no > 1 and not questions:
        return []
    return _fill(questions, FALLBACK_QUESTIONS, prefix)


def intake_questions(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """The fixed intake questions (agents/intake.py) for the brief fields that are missing, in the shared shape."""
    from agents.intake import QUESTIONS, missing_fields

    suggestions = {"has_team": ["No, I'm alone", "Yes: a developer", "Yes: a designer"],
                   "time_available": ["5 hours a week", "15 hours a week", "Full time"],
                   "budget": ["Nothing", "Under 300 USD", "Under 1,000 USD"]}
    return [{"id": field, "text": QUESTIONS[field], "why": "The brief doesn't say this yet; it feeds founder fit and feasibility.",
             "suggestions": suggestions.get(field, []), "choices": None} for field in missing_fields(brief)]


def coach_questions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """After repeat or pivot: one question per lowest criterion, aimed at the missing evidence type (no model)."""
    scores = state.get("scores") or {}
    lowest = sorted((k for k in scores if k in EVIDENCE_QUESTIONS), key=lambda k: scores[k])[:3]
    questions = []
    for criterion in lowest or ["problem_evidence", "competition", "willingness_to_pay"]:
        text, why, sugg = EVIDENCE_QUESTIONS[criterion]
        score = scores.get(criterion)
        why = f"{why} (score {score:g} of 4)" if isinstance(score, (int, float)) else why
        questions.append({"id": f"coach_{criterion}", "text": text, "why": why, "suggestions": sugg, "choices": None})
    return questions


__all__ = ["discovery_summary", "discovery_questions", "intake_questions", "coach_questions", "ask"]
