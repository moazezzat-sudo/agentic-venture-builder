"""Helpers shared by the Phase 1 agents: prompts, one capped model call, JSON parsing, claim rendering.

    data, usage = ask_json("weigher", payload, role="fast", max_tokens=400)
    usage -> {"tokens": int, "cost": float, "model": str}

Every model call goes through invoke_model(), so tests can replace that one
function with a fake model.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

from config import ROOT_DIR, settings

PROMPTS_DIR = ROOT_DIR / "prompts"
SNIPPET_CHARS = 300


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


DEFAULT_MAX_TOKENS = 600
RETRY_NOTE = "Your last reply was not valid JSON. Reply again with valid JSON only, in exactly the shape given. No prose."


def _llm(role: str, max_tokens: int, temperature: Optional[float] = None):
    """The model client with a token cap, JSON mode where the provider has it, and an optional temperature."""
    from llm import get_llm

    extra: dict[str, Any] = {}
    if temperature is not None:
        extra["temperature"] = temperature
    if settings.provider == "ollama":
        # num_predict is Ollama's max_tokens; format="json" makes Ollama return JSON only.
        # Thinking off for qwen3; gpt-oss can't turn it off, so keep it at "low" (it counts against num_predict).
        think: Any = "low" if "gpt-oss" in settings.model_name(role) else False
        return get_llm(role=role, num_predict=max_tokens, reasoning=think, format="json", **extra)
    extra["max_tokens"] = max_tokens
    if "gpt-oss" in settings.model_name(role):
        extra["reasoning_effort"] = "low"  # reasoning tokens count against max_tokens
    return get_llm(role=role, **extra)


def invoke_model(
    agent: str, system: str, user: str, role: str = "smart", max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: Optional[float] = None,
) -> tuple[str, int, float, str]:
    """One model call. Returns (text, total_tokens, cost_usd, model_name)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from llm import usage_cost

    if user.lstrip().startswith("{"):
        user = frame(user)  # small local models in JSON mode echo a bare JSON message back
    reply = _llm(role, max_tokens, temperature).invoke([SystemMessage(content=system), HumanMessage(content=user)])
    tokens, cost = usage_cost(reply)
    text = reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
    return text, tokens, cost, settings.model_name(role)


def parse_json(text: str) -> dict[str, Any]:
    """Take the first JSON object out of a model reply. Returns {} if there is none."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    # qwen3 sometimes leaves a lone closing tag (thinking cut off) or echoes its switch.
    text = text.split("</think>")[-1].replace("/no_think", "").replace("/think", "")
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                        return value if isinstance(value, dict) else {}
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return {}


def frame(user_json: str, expect: Iterable[str] = ()) -> str:
    """The payload framed as data, with the reply's keys named. qwen3:4b in JSON mode echoes a bare
    JSON message back instead of answering it (seen in the real-model check)."""
    keys = list(expect)
    return ("Input data (do not repeat it):\n" + user_json + "\n\nReply with only the JSON object your instructions "
            "describe" + (f", with its keys: {', '.join(keys)}." if keys else "."))


def ask_json(
    agent: str, payload: dict[str, Any], role: str = "smart", max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: Optional[float] = None, expect: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send the agent's prompt plus a compact JSON payload; return (parsed_reply, usage).

    `expect` names the reply's top-level keys: a reply with none of them (for example the input
    echoed back) counts as not parsed. If the reply is not a valid JSON object, ask once more with a
    short "valid JSON only" note. If that fails too, return {} with usage["parsed"] = False: every
    caller then uses its safe default. Tokens and cost cover both calls.
    """
    expect = tuple(expect)
    system = load_prompt(agent)
    user = frame(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), expect)

    def valid(data: dict[str, Any]) -> dict[str, Any]:
        return data if data and (not expect or any(k in data for k in expect)) else {}

    text, tokens, cost, model = invoke_model(agent, system, user, role=role, max_tokens=max_tokens, temperature=temperature)
    data = valid(parse_json(text))
    retried = False
    if not data:
        retried = True
        text, t2, c2, model = invoke_model(agent, system, f"{user}\n\n{RETRY_NOTE}", role=role,
                                           max_tokens=max_tokens, temperature=temperature)
        tokens, cost = tokens + t2, cost + c2
        data = valid(parse_json(text))
    return data, {"tokens": tokens, "cost": cost, "model": model, "parsed": bool(data), "retried": retried,
                  "raw": cut(text, 300)}  # the start of the last reply, for logging when a field is missing


def model_fields(usage: dict[str, Any]) -> dict[str, Any]:
    """The log fields of one model call (ask_json usage), so every such entry has tokens and parsed."""
    return {"model": usage.get("model"), "cost": usage.get("cost", 0), "tokens": usage.get("tokens", 0),
            "parsed": usage.get("parsed"), "retried": usage.get("retried", False)}


def cut(text: Any, limit: int = SNIPPET_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def brief_for_model(brief: dict[str, Any]) -> dict[str, Any]:
    """The brief without empty fields, each value cut short, to save tokens."""
    return {k: (cut(v, 400) if isinstance(v, str) else v) for k, v in brief.items() if v not in (None, "", [], {})}


def text_violations(texts: dict[str, Any], rewritable: bool, round_no: int) -> list[dict[str, Any]]:
    """Run guardrails.check_text on each text. Returns one record per violation.

    rewritable=False for the founder's own words (the gate recommends stop);
    True for drafts our agents wrote (the gate recommends repeat, to rewrite them).
    """
    from guardrails import check_text

    found = []
    for source, text in texts.items():
        if not str(text or "").strip():
            continue
        for v in check_text(str(text)):
            found.append({"source": source, "rule": v.get("rule"), "reason": v.get("reason"),
                          "excerpt": cut(v.get("excerpt"), 120), "rewritable": rewritable, "round": round_no})
    return found


def describe_violation(v: dict[str, Any]) -> str:
    return f"{v['rule']} in {v['source']}: \"{v['excerpt']}\". {v['reason']}"


# Used only when the model gives fewer than 5 questions. Past behaviour, never "would you buy".
TEMPLATE_INTERVIEW_QUESTIONS = [
    "When did this problem last come up for you? Walk me through what happened.",
    "What did you do about it that time?",
    "What tools or services do you use for this today, and what do they cost you?",
    "What have you already tried that didn't work, and why did you stop?",
    "Who else is involved when this comes up?",
]


def write_interview_kit(raw_questions: Any, audience: str, outcome: str) -> list[str]:
    """Write outputs/phase1_step9_interview_kit.md (The Mom Test style) and return the questions.

    Written after go, repeat and pivot; never after stop.
    """
    from logger import write_output

    kit = [cut(q, 200) for q in (raw_questions if isinstance(raw_questions, list) else []) if str(q).strip()][:7]
    source = "model"
    if len(kit) < 5:
        kit, source = list(TEMPLATE_INTERVIEW_QUESTIONS), "fixed template"
    write_output(1, 9, "interview kit", (
        f"# Phase 1, step 9: customer interview kit (The Mom Test style), after {outcome}\n\n"
        f"For: {audience}\n\nAsk about past behaviour; don't describe the idea or ask whether they would buy it. "
        f"Questions from: {source}.\n\n" + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(kit)) + "\n"
    ))
    return kit


def claims_markdown(claims: Iterable[dict[str, Any]]) -> str:
    """One line per claim with its support: URL and tier, our evidence, or ASSUMPTION."""
    lines = []
    for i, c in enumerate(claims):
        if c.get("support") == "url":
            tag = f"tier {c.get('tier', 'NONE')}, [{c['url']}]({c['url']}), read {c.get('accessed_at', '')}"
        elif c.get("support") == "evidence":
            tag = f"our evidence: {c.get('evidence_ref')}"
        else:
            tag = "ASSUMPTION"
        label = f"[{c['id']}{' · ' + c['kind'] if c.get('kind') else ''}] " if c.get("id") else ""
        lines.append(f"{i}. {label}{c['text']} ({c.get('area') or 'general'}; {tag})")
    return "\n".join(lines) if lines else "_No claims._"
