"""Discovery conversation: Phase 1 starts here, before any research.

The founder sees "Here's what I understood" (a summary and five key assumptions: customer, problem,
current alternative, why now, how they'd pay) with questions, answers them (a second round only if
something is still vague, at most 2 rounds), then confirms with "Yes, that's my idea" or corrects it.
Only a confirmed understanding goes to research.

The understanding is built in Python from the founder's own data, so it is never empty and never
ignores an answer:
  - every assumption starts from the brief (customer <- target market, problem <- the idea);
  - every question carries the assumption "type" it asks about, and the founder's answer becomes
    that assumption's text;
  - the model's text replaces a default only when it is non-empty and not "Unclear";
  - corrections are appended to the summary and to the assumption they name;
  - "Unclear: not stated yet." only when neither the brief nor any answer covers that type.
normalize_discovery() accepts the reply shapes small local models return (seen with qwen3:4b).

Uses Hashish's agents/questions.py (discovery_summary, discovery_questions) when it is on main; until
then, one small fast-model call per round (prompts/discovery.md). Three nodes, because a node re-runs
from the top on resume:
  prepare_node  -> the model call for this round (no pause)
  ask_node      -> pause (kind "questions", stage "discovery") with the summary and questions
  confirm_node  -> pause (stage "discovery_confirm") with the two choices; writes the confirmed brief

Question format (shared with the app and Hashish): {id, text, why, suggestions, choices or null, type}.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from langgraph.types import interrupt

from agents import intake
from agents._common import ask_json, brief_for_model, cut, model_fields, text_violations
from logger import log_action, write_output

ASSUMPTION_TYPES = ("customer", "problem", "current_alternative", "why_now", "payment")
ASSUMPTION_LABELS = {"customer": "Customer", "problem": "Problem", "current_alternative": "What they use now",
                     "why_now": "Why now", "payment": "How they'd pay"}
UNCLEAR = "Unclear: not stated yet."
CONFIRM_YES, CONFIRM_NO = "Yes, that's my idea", "Not quite, let me correct it"
MAX_ROUNDS = 2  # question rounds; later passes only update the summary

# Fixed questions for founder fields the brief leaves out (feed founder fit and feasibility).
FIELD_CHOICES = {"has_team": ["No, just me", "Yes (list their skills)"]}

# Python questions for an assumption nothing covers yet: (text, why, suggestions).
TYPE_QUESTIONS = {
    "customer": ("Who exactly would use this first?", "Research looks for these people.",
                 ["Players", "Team captains", "Coaches"]),
    "problem": ("What goes wrong for them today, in their own words?", "Research looks for people saying this.", []),
    "current_alternative": ("What do they do about it today instead?", "Those are the competitors research looks for.",
                            ["Nothing", "A free app", "Do it by hand"]),
    "why_now": ("Why is now a good time for this?", "It shows whether the timing helps or hurts.", []),
    "payment": ("Who would pay for it, and how?", "Research looks for what people pay today.",
                ["Per use", "Monthly subscription", "One-time purchase", "Free with ads"]),
}

# Key names small models use, matched ignoring case, spaces, underscores and punctuation.
TYPE_ALIASES = {
    "customer": ("customer", "customers", "targetcustomer", "user", "users", "who", "targetuser", "audience"),
    "problem": ("problem", "pain", "painpoint", "need"),
    "current_alternative": ("currentalternative", "alternative", "alternatives", "currentsolution",
                            "whattheyusenow", "existingsolution", "competition"),
    "why_now": ("whynow", "timing", "now"),
    "payment": ("payment", "pricing", "price", "howtheydpay", "howtheywouldpay", "revenue", "businessmodel",
                "monetization", "monetisation", "whopays"),
}
SUMMARY_KEYS = ("summary", "understood", "heresWhatIUnderstood", "hereswhatiunderstood", "restatement",
                "understanding", "whatiunderstood")
REPLY_KEYS = ("summary", "assumptions", "keywords", "questions", "understood", "restatement", "understanding",
              "customer", "problem")


def _k(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower())


ALIAS_TO_TYPE = {_k(alias): t for t, aliases in TYPE_ALIASES.items() for alias in aliases}


def _text(value: Any) -> str:
    """A field's text: a string, or the first text-like value of a dict."""
    if isinstance(value, dict):
        for key in ("text", "assumption", "value", "description", "answer"):
            if str(value.get(key) or "").strip():
                return str(value[key]).strip()
        return ""
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def _prompt_text() -> str:
    from agents._common import load_prompt

    return " ".join(load_prompt("discovery").lower().split())


def _useful(text: str) -> bool:
    """Non-empty, not "Unclear", and not copied from the prompt's example (qwen3:4b did both)."""
    if not text or re.match(r"^\s*(unclear|unknown|not stated|n/?a|none)\b", text, re.I):
        return False
    core = " ".join(re.sub(r"^\s*here'?s what i understood:\s*", "", text, flags=re.I).lower().split())
    return len(core) > 3 and core not in _prompt_text()


def normalize_discovery(data: Any) -> dict[str, Any]:
    """Accept the shapes small models return.

    -> {"summary": str, "assumptions": {type: text}, "questions": [{text, why, suggestions, type}],
        "keywords": dict, "missing": [fields not found]}
    """
    data = data if isinstance(data, dict) else {}
    flat = {_k(k): v for k, v in data.items()}
    summary = next((_text(flat[_k(k)]) for k in SUMMARY_KEYS if _text(flat.get(_k(k)))), "")

    assumptions: dict[str, str] = {}
    raw = flat.get("assumptions") or flat.get("keyassumptions")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                kind = ALIAS_TO_TYPE.get(_k(item.get("type") or item.get("name") or item.get("key") or item.get("category")))
                text = _text(item)
                if kind and text:
                    assumptions.setdefault(kind, text)
            elif isinstance(item, str) and ":" in item:  # "customer: amateur players"
                head, _, text = item.partition(":")
                if ALIAS_TO_TYPE.get(_k(head)) and text.strip():
                    assumptions.setdefault(ALIAS_TO_TYPE[_k(head)], text.strip())
    elif isinstance(raw, dict):
        for key, value in raw.items():
            if ALIAS_TO_TYPE.get(_k(key)) and _text(value):
                assumptions.setdefault(ALIAS_TO_TYPE[_k(key)], _text(value))
    for key, value in flat.items():  # assumptions as top-level keys
        if key in ALIAS_TO_TYPE and _text(value) and not isinstance(value, list):
            assumptions.setdefault(ALIAS_TO_TYPE[key], _text(value))

    questions = []
    for q in flat.get("questions") or []:
        if isinstance(q, str) and q.strip():
            questions.append({"text": q.strip(), "why": "", "suggestions": [], "type": None})
        elif isinstance(q, dict):
            text = str(q.get("text") or q.get("question") or "").strip()
            if text:
                questions.append({"text": text, "why": str(q.get("why") or ""),
                                  "suggestions": q.get("suggestions") if isinstance(q.get("suggestions"), list) else [],
                                  "type": ALIAS_TO_TYPE.get(_k(q.get("type") or q.get("about") or ""))})
    keywords = flat.get("keywords") if isinstance(flat.get("keywords"), dict) else {}
    missing = [f for f, ok in (("summary", summary), ("assumptions", assumptions), ("keywords", keywords)) if not ok]
    return {"summary": summary, "assumptions": assumptions, "questions": questions, "keywords": keywords,
            "missing": missing}


def question_type(text: str) -> Optional[str]:
    """Which assumption a question asks about, from its words (for model questions without a type)."""
    t = text.lower()
    if re.search(r"\b(pay|paid|price|pricing|cost|charge|subscription|free)\b", t):
        return "payment"
    if re.search(r"\b(problem|pain|frustrat|struggle|wrong|hard|difficult|face)\b", t):
        return "problem"
    if re.search(r"\bwhy\b.*\bnow\b|\bright time\b|\btiming\b|\bwhy (is )?this the\b", t):
        return "why_now"
    if re.search(r"\b(instead|currently|today|now|alternative|already use|do they do|how do they)\b", t):
        return "current_alternative"
    if re.search(r"\b(who|which (players|users|customers|people)|target|user|customer)\b", t):
        return "customer"
    return None


def question(qid: str, text: str, why: str = "", suggestions: Optional[list[str]] = None,
             choices: Optional[list[str]] = None, qtype: Optional[str] = None) -> dict[str, Any]:
    return {"id": qid, "text": cut(text, 240), "why": cut(why, 200),
            "suggestions": [cut(s, 80) for s in (suggestions or []) if str(s).strip()][:4], "choices": choices,
            "type": qtype}


def has_confirmed_understanding(brief: dict[str, Any]) -> bool:
    """A brief that already carries a confirmed understanding (a re-run) skips the conversation."""
    understood = brief.get("confirmed_understanding") or {}
    return isinstance(understood, dict) and all(str(understood.get(t, "")).strip() for t in ASSUMPTION_TYPES)


# --------------------------------------------------------------------------- the Python base

SOLUTION_PREFIX = re.compile(
    r"^\s*(an?|the)?\s*((mobile|web|simple|small|online|ai)\s+)*(app|application|website|site|platform|tool|"
    r"service|marketplace|bot|extension|saas|software)\s+(that|which|to|for)?\s*(lets|helps|allows|enables)?\s*", re.I)


def brief_defaults(brief: dict[str, Any]) -> dict[str, str]:
    """Assumption defaults from the brief alone."""
    idea = " ".join(str(brief.get("idea") or "").split()).rstrip(".")
    customer = str(brief.get("target_market") or "").strip()
    if not customer:
        m = re.search(r"\b(?:for|lets|helps|allows)\s+(.+?)(?:\s+(?:to|in|who|that|with|and)\b|$)", idea, re.I)
        customer = m.group(1) if m else ""
    problem = SOLUTION_PREFIX.sub("", idea)
    out = {"customer": cut(customer, 200), "problem": cut(f"The idea addresses: {problem}" if problem else "", 240)}
    return {t: out.get(t, "") for t in ASSUMPTION_TYPES}


def correction_type(text: str) -> str:
    """The assumption a correction names, or "problem"."""
    for t in ("payment", "current_alternative", "why_now", "customer", "problem"):
        if question_type(text) == t or re.search(rf"\b{t.replace('_', ' ')}\b", text, re.I):
            return t
    return "problem"


def build_understanding(brief: dict[str, Any], disc: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Summary and assumptions from the brief, the founder's answers, the model's text and corrections.

    Precedence per assumption: the founder's own answer > the model's useful text > the brief default
    > "Unclear: not stated yet.". Corrections are appended last. Never returns an empty summary.
    """
    texts = brief_defaults(brief)
    for t, v in (disc.get("model_assumptions") or {}).items():
        if t in texts and _useful(v):
            texts[t] = cut(v, 240)
    for a in disc.get("answers", []):  # later answers win
        if a.get("type") in texts and str(a.get("answer", "")).strip():
            texts[a["type"]] = cut(a["answer"], 240)
    for c in disc.get("corrections", []):
        t = correction_type(c)
        texts[t] = cut(f"{texts[t]} Correction: {c}" if _useful(texts[t]) else c, 300)

    idea = " ".join(str(brief.get("idea") or "your idea").split()).rstrip(".")
    base = f"You want to build {idea[0].lower() + idea[1:] if idea[:2] in ('A ', 'An') else idea}"
    if brief.get("target_market"):
        base += f" for {brief['target_market']}"
    if brief.get("location"):
        base += f" in {brief['location']}"
    base += "."
    model_summary = str(disc.get("model_summary") or "")
    summary = model_summary if _useful(model_summary) and len(model_summary) > 20 else base
    told = [f"{a['answer'].rstrip('.')} ({ASSUMPTION_LABELS.get(a.get('type'), 'you said').lower()})."
            for a in disc.get("answers", []) if str(a.get("answer", "")).strip()]
    if told:
        summary += " You told me: " + " ".join(told)
    if disc.get("corrections"):
        summary += " Correction: " + " ".join(c.rstrip(".") + "." for c in disc["corrections"])
    assumptions = [{"id": f"A{i + 1}", "type": t, "text": texts[t] if _useful(texts[t]) else UNCLEAR}
                   for i, t in enumerate(ASSUMPTION_TYPES)]
    return cut(summary, 900), assumptions


def build_keywords(brief: dict[str, Any], assumptions: list[dict[str, str]], model_kw: Any) -> dict[str, Any]:
    """Search keywords: the model's when useful, otherwise the founder's own words (search_plan.words)."""
    from agents.search_plan import words

    model_kw = model_kw if isinstance(model_kw, dict) else {}
    understood = {a["type"]: (a["text"] if _useful(a["text"]) else "") for a in assumptions}
    place = brief.get("location") or ""
    idea = str(brief.get("idea") or "")
    customer = words(understood.get("customer") or brief.get("target_market"), 4, place)
    python = {
        "customer": customer,
        "problem": words(re.sub(r"^The idea addresses:\s*", "", understood.get("problem", "")), 5, f"{customer} {place}"),
        "solution": words(SOLUTION_PREFIX.sub("", idea), 4, f"{customer} {place}"),
    }
    python["activity"] = " ".join(python["solution"].split()[:2])
    out = {k: cut(str(model_kw.get(k) or ""), 60) if _useful(str(model_kw.get(k) or "")) else python[k]
           for k in ("customer", "problem", "solution", "activity")}
    out["arabic"] = [cut(w, 40) for w in (model_kw.get("arabic") or []) if str(w).strip()][:5]
    return out


# --------------------------------------------------------------------------- model rounds


def _model_round(state: dict[str, Any], round_no: int) -> tuple[dict[str, Any], dict[str, Any]]:
    disc = state.get("discovery") or {}
    payload = {"brief": brief_for_model(state["brief"]), "round": round_no,
               "answers": disc.get("answers", []), "corrections": disc.get("corrections", [])}
    data, usage = ask_json("discovery", payload, role="fast", max_tokens=900, temperature=0, expect=REPLY_KEYS)
    return normalize_discovery(data), usage


def _hashish_round(module, state: dict[str, Any], round_no: int) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = module.discovery_summary(state) or {}
    questions = module.discovery_questions(state, round_no) if round_no <= MAX_ROUNDS else []
    result = normalize_discovery({**summary, "questions": questions or []})
    usage = {"tokens": int(summary.get("tokens", 0) or 0), "cost": 0, "model": "agents.questions", "parsed": True,
             "raw": cut(json.dumps(summary, ensure_ascii=False), 300)}
    return result, usage


def prepare_node(state: dict[str, Any]) -> dict[str, Any]:
    disc = dict(state.get("discovery") or {"round": 0, "answers": [], "corrections": []})
    round_no = int(disc.get("round", 0)) + 1
    module = _hashish()
    result, usage = _hashish_round(module, state, round_no) if module else _model_round(state, round_no)
    if result["summary"]:
        disc["model_summary"] = result["summary"]
    # A later "Unclear" never replaces earlier useful text from the model.
    disc["model_assumptions"] = {**(disc.get("model_assumptions") or {}),
                                 **{t: v for t, v in result["assumptions"].items() if _useful(v)}}
    summary, assumptions = build_understanding(state["brief"], disc)
    unclear = [a["type"] for a in assumptions if a["text"] == UNCLEAR]

    questions: list[dict[str, Any]] = []
    if round_no <= MAX_ROUNDS:
        seen: set = set()
        for i, q in enumerate(result["questions"]):
            qtype = q.get("type") or question_type(q["text"])
            if qtype in seen:
                continue  # one question per assumption
            seen.add(qtype)
            questions.append(question(f"r{round_no}q{i + 1}", q["text"], q.get("why", ""), q.get("suggestions"),
                                      qtype=qtype))
        questions = questions[:3]
        asked = {q["type"] for q in questions}
        # Every assumption nobody has covered yet gets a question (round 1, and round 2 if still vague).
        questions += [question(f"r{round_no}_{t}", *TYPE_QUESTIONS[t], qtype=t) for t in unclear if t not in asked]
        if round_no == 1:
            questions += [question(f, intake.QUESTIONS[f], "Feeds the founder-fit and feasibility scores.",
                                   choices=FIELD_CHOICES.get(f)) for f in intake.missing_fields(state["brief"])]
    disc.update(round=round_no, summary=summary, assumptions=assumptions, questions=questions,
                keywords=build_keywords(state["brief"], assumptions, result["keywords"]))
    log_action(agent="discovery", action=f"discovery_round_{round_no}", run_id=state.get("run_id"),
               source="agents.questions" if module else "fallback", questions=len(questions),
               unclear=unclear, missing_fields=result["missing"],
               raw_reply=usage.get("raw", "") if result["missing"] else None, **model_fields(usage))
    return {"discovery": disc, "tokens": usage.get("tokens", 0)}


def _hashish():
    # Eyad's discovery path is the one built and tested against qwen3:4b (founder answers always kept).
    # agents/questions.py stays available but is not used in the live run.
    return None
    try:
        from agents import questions  # Hashish's module, when it lands
    except ImportError:
        return None
    ok = hasattr(questions, "discovery_summary") and hasattr(questions, "discovery_questions")
    return questions if ok else None


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
    asked = {q["id"]: q for q in disc["questions"]}
    disc["answers"] = [*disc.get("answers", []),
                       *({"question": (asked.get(k) or {}).get("text", k), "answer": v,
                          "type": (asked.get(k) or {}).get("type")} for k, v in answers.items())]
    brief = intake.apply_answers(state["brief"], {k: v for k, v in answers.items() if k in intake.QUESTIONS})
    if answers.get("has_team", "").lower().startswith("no"):
        brief["has_team"] = False
    # The answers go into the understanding now, in Python, whatever the model does next.
    disc["summary"], disc["assumptions"] = build_understanding(brief, disc)
    violations = text_violations({f"founder answer: {k}": v for k, v in answers.items()}, False, state.get("round", 1))
    log_action(agent="discovery", action=f"discovery_answers_round_{disc['round']}", model=None,
               run_id=state.get("run_id"), answered=sorted(answers), guardrail_violations=[v["rule"] for v in violations])
    return {"discovery": disc, "brief": brief, "text_violations": violations,
            "founder_answers": {**(state.get("founder_answers") or {}), **answers}}


def confirm_node(state: dict[str, Any]) -> dict[str, Any]:
    disc = dict(state["discovery"])
    if not str(disc.get("summary", "")).strip():  # fail safe: never an empty summary on the confirm screen
        disc["summary"], disc["assumptions"] = build_understanding(state["brief"], disc)
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
        disc["summary"], disc["assumptions"] = build_understanding(state["brief"], disc)
        log_action(agent="discovery", action="discovery_corrected", model=None, run_id=state.get("run_id"),
                   approved_by="founder", applies_to=correction_type(correction))
        return {"discovery": disc}

    disc["confirmed"] = True
    disc["keywords"] = build_keywords(state["brief"], disc.get("assumptions", []), disc.get("keywords"))
    understood = {a["type"]: a["text"] for a in disc.get("assumptions", [])}
    brief = {**state["brief"], "confirmed_understanding": understood, "keywords": disc["keywords"],
             "discovery_summary": disc.get("summary", ""),
             "discovery_answers": [f"{a['question']} {a['answer']}" for a in disc.get("answers", [])]}
    if not brief.get("target_market") and _useful(understood.get("customer", "")):
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
    if not disc["summary"]:
        disc["summary"], _ = build_understanding(state["brief"], {"model_assumptions": understood})
    write_discovery(disc, state["brief"])
    return {"discovery": disc}
