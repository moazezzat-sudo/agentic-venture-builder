"""Runs Phase 1 (Discover) as a LangGraph graph and pauses at every gate for the founder.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from orchestrator import start_run, resume_run
    result = start_run(brief, run_id)          # runs until the first pause
    result = resume_run(run_id, reply)         # continues after the founder answers

Both return a dict. Check result["awaiting_founder"]:
  - False: the run has ended (stopped, or Phase 1 is finished). The dict is the
           Briefcase state (see schemas.py) plus awaiting_founder.
  - True:  the run is paused. result["kind"] says why:
      "gate"      A gate recommendation: the dict is a GateResult (phase, gate,
                  recommendation, reasons, target, evidence_summary, score).
                  Resume with the founder's FounderDecision
                  (approval.record_decision makes one). Nothing else is accepted.
      "questions" Follow-up questions: result["questions"] is a list of
                  {field, question}. Resume with {"answers": {field: text}}.
                  When result["needs_accept_revised_idea"] is true (coach, after a
                  pivot), also send "accept_revised_idea": True or False.
Every result carries run_id, "stubbed" (True while any tool it depends on is
STUBBED) and "stubbed_parts" (which ones).

Graph (PLAN.md section 3):

    intake -> category_check -> weigher -> researcher x N (Send) -> skeptic -> scorer
      -> gate_1 -> founder: stop -> finish
                            repeat/pivot -> coach -> founder answers -> weigher (next round)
                            go -> subdomain -> rescore -> gate_1_niche -> founder
                                  go -> finish (Phase 2 next); repeat/pivot -> coach; stop -> finish

The outcome at every gate comes from gates.py (plain Python), never the model.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Union

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agents import coach, intake, researcher, scorer, skeptic, subdomain, weigher
from agents.scorer import current_claims
from gates import evaluate_gate_1, load_rubric
from logger import log_action, write_gate, write_output
from schemas import Briefcase, FounderDecision, GateResult

GATE_1 = "gate_1"
GATE_1_NICHE = "gate_1_niche"
MAX_ROUNDS = 3  # coach loops allowed before a repeat/pivot ends the run
TOKEN_BUDGET = 15_000


# ---------------------------------------------------------------- stubs we depend on

def stubbed_parts() -> list[str]:
    parts = list(researcher._stubbed_tools())
    if _guardrails() is None:
        parts.append("guardrails (category_check fallback)")
    return parts


def _guardrails():
    """Hashish's guardrails module, once its check_category is real (not STUBBED)."""
    try:
        import guardrails

        if hasattr(guardrails, "check_category") and not getattr(guardrails, "STUBBED", False):
            return guardrails
    except ImportError:
        pass
    return None


# STUBBED: used only while guardrails.check_category is STUBBED or missing. A small
# keyword list, so a clearly banned product still stops before research.
_FALLBACK_BANNED = {
    "physical_goods": r"\b(physical product|hardware device|t-?shirts?|merch(andise)?|furniture|jewel(le)?ry|cosmetics)\b",
    "financial_investment_crypto": r"\b(crypto|bitcoin|token sale|nft|trading signals?|forex|stock tips?|investment advice|loans?)\b",
    "health_advice": r"\b(diagnos\w*|medical advice|treatment plans?|supplements?|therapy|symptom checker)\b",
    "legal_advice": r"\b(legal advice|lawyer|contract review for clients)\b",
}


def check_category(brief: dict[str, Any]) -> tuple[bool, str, str, bool]:
    """(allowed, category, reason, stubbed)."""
    module = _guardrails()
    if module is not None:
        allowed, category, reason = module.check_category(brief)
        return bool(allowed), category, reason, False
    text = f"{brief.get('idea', '')} {brief.get('target_market', '')}".lower()
    for category, pattern in _FALLBACK_BANNED.items():
        if re.search(pattern, text):
            return False, category, f"STUBBED keyword check: the idea looks like {category.replace('_', ' ')}, which is not allowed", True
    return True, "digital", "STUBBED keyword check found no banned category", True


# ---------------------------------------------------------------- nodes

def category_check_node(state: Briefcase) -> dict[str, Any]:
    allowed, category, reason, stubbed = check_category(state["brief"])
    log_action(agent="guardrails", action="category_check", model=None, allowed=allowed, category=category, stubbed=stubbed)
    status = "STUBBED" if stubbed else "Working"
    write_output(1, 2, "category check", (
        f"# Phase 1, step 2: category check\n\nAllowed: **{allowed}**\n\nCategory: {category}\n\nReason: {reason}\n"
    ), status=status)
    if allowed:
        return {}
    result = GateResult(
        phase=1, gate="category_check", recommendation="stop", reasons=[reason],
        target="The product is digital and not in a banned category", evidence_summary="Stopped before any research.",
    )
    write_gate(1, "decision", _gate_markdown(result, None), status=status)
    log_action(agent="gate", action="category_check_stop", model=None, outcome="stop")
    return {"stopped": True, "stop_reason": reason, "gate_results": [result.model_dump()]}


def fan_out(state: Briefcase) -> list[Send]:
    """One researcher per area, in parallel."""
    return [
        Send("researcher", {"research_area": {**area, "index": i}, "brief": state["brief"], "round": state.get("round", 1)})
        for i, area in enumerate(state["areas"])
    ]


def _gate_markdown(result: GateResult, decision: Optional[FounderDecision]) -> str:
    reasons = "\n".join(f"- {r}" for r in result.reasons)
    score = f"{result.score:.2f} of 4" if result.score is not None else "not scored"
    body = (
        f"# Phase 1 gate: {result.gate}\n\n"
        f"Recommendation: **{result.recommendation.upper()}**\n\nWeighted score: {score}\n\n"
        f"Target set before the phase: {result.target}\n\nEvidence: {result.evidence_summary}\n\n## Reasons\n\n{reasons}\n\n"
        "The recommendation comes from fixed rules in gates.py and rubric.yaml; the weights and cut-offs are our design choices.\n\n"
        "## Founder decision\n\n"
    )
    if decision is None:
        return body + "_Waiting for the founder._\n"
    override = " This **overrides** the recommendation." if decision.outcome != result.recommendation else ""
    return body + (
        f"Founder chose **{decision.outcome.upper()}** (approved the recommendation: {decision.approved}).{override}\n\n"
        f"Note: {decision.note or '_none_'}\n\nDecided at {decision.decided_at}, approved_by: founder.\n"
    )


def _gate_file(gate: str) -> str:
    return "decision" if gate == GATE_1 else "niche_decision"


def make_gate_eval(gate: str):
    def node(state: Briefcase) -> dict[str, Any]:
        result = evaluate_gate_1(state["scores"], current_claims(state)).model_copy(update={"gate": gate})
        write_gate(1, _gate_file(gate), _gate_markdown(result, None))
        log_action(agent="gate", action=gate, model=None, outcome=result.recommendation, score=result.score,
                   round=state.get("round", 1))
        return {"gate_results": [result.model_dump()]}

    node.__name__ = f"{gate}_eval"
    return node


def make_gate_wait(gate: str):
    def node(state: Briefcase) -> dict[str, Any]:
        result = GateResult(**state["gate_results"][-1])
        # Pauses until the founder answers. resume_run only accepts a FounderDecision here.
        reply = interrupt({"kind": "gate", **result.model_dump()})
        decision = FounderDecision(**reply)
        if decision.gate != gate or decision.phase != 1:
            raise ValueError(f"decision is for {decision.gate!r}, but the run is waiting at {gate!r}")
        decision = decision.model_copy(update={"overrides_recommendation": decision.outcome != result.recommendation})
        write_gate(1, _gate_file(gate), _gate_markdown(result, decision))
        log_action(agent="gate", action=f"{gate}_founder_decision", model=None, approved_by="founder",
                   outcome=decision.outcome, recommendation=result.recommendation,
                   overrides_recommendation=decision.overrides_recommendation)
        update: dict[str, Any] = {"founder_decisions": [decision.model_dump()]}
        if decision.outcome == "stop":
            update.update(stopped=True, stop_reason=f"Founder chose stop at {gate}.")
        return update

    node.__name__ = f"{gate}_wait"
    return node


def after_gate(gate: str):
    def route(state: Briefcase) -> str:
        outcome = state["founder_decisions"][-1]["outcome"]
        if outcome == "stop":
            return "finish"
        if outcome in ("repeat", "pivot"):
            return "coach" if state.get("round", 1) < MAX_ROUNDS else "round_limit"
        return "subdomain" if gate == GATE_1 else "finish"

    return route


def round_limit_node(state: Briefcase) -> dict[str, Any]:
    reason = f"Stopped: {MAX_ROUNDS} rounds of repeat/pivot used without reaching go."
    log_action(agent="orchestrator", action="round_limit_stop", model=None, round=state.get("round", 1))
    return {"stopped": True, "stop_reason": reason}


def finish_node(state: Briefcase) -> dict[str, Any]:
    stopped = bool(state.get("stopped"))
    tokens = state.get("tokens", 0)
    phase = 1 if stopped else 2
    log_action(agent="orchestrator", action="phase1_finished", model=None, stopped=stopped, tokens=tokens,
               over_token_budget=tokens > TOKEN_BUDGET)
    last = state.get("gate_results", [{}])[-1] if state.get("gate_results") else {}
    write_output(1, 10, "result", (
        "# Phase 1 result\n\n"
        + (f"**Stopped.** {state.get('stop_reason', '')}\n\n" if stopped else "**Phase 1 finished; the founder approved go. Phase 2 (Validate) is next.**\n\n")
        + f"Last gate: {last.get('gate', 'none')}, recommended {str(last.get('recommendation', 'n/a')).upper()}.\n\n"
        + f"Rounds: {state.get('round', 1)}. Model tokens used: {tokens} (budget {TOKEN_BUDGET}).\n"
        + (f"\nNiche: {state['subdomain']}\n" if state.get("subdomain") else "")
    ))
    return {"current_phase": phase}


# ---------------------------------------------------------------- graph

def build_graph(checkpointer=None):
    g = StateGraph(Briefcase)
    g.add_node("intake", intake.node)
    g.add_node("category_check", category_check_node)
    g.add_node("weigher", weigher.node)
    g.add_node("researcher", researcher.node)
    g.add_node("skeptic", skeptic.node)
    g.add_node("scorer", scorer.node)
    g.add_node("gate_1", make_gate_eval(GATE_1))
    g.add_node("gate_1_wait", make_gate_wait(GATE_1))
    g.add_node("coach", coach.node)
    g.add_node("coach_answers", coach.answers_node)
    g.add_node("subdomain", subdomain.node)
    g.add_node("rescore", scorer.make_node(8, "niche scores"))
    g.add_node("gate_1_niche", make_gate_eval(GATE_1_NICHE))
    g.add_node("gate_1_niche_wait", make_gate_wait(GATE_1_NICHE))
    g.add_node("round_limit", round_limit_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "intake")
    g.add_edge("intake", "category_check")
    g.add_conditional_edges("category_check", lambda s: "finish" if s.get("stopped") else "weigher", ["weigher", "finish"])
    g.add_conditional_edges("weigher", fan_out, ["researcher"])
    g.add_edge("researcher", "skeptic")
    g.add_edge("skeptic", "scorer")
    g.add_edge("scorer", "gate_1")
    g.add_edge("gate_1", "gate_1_wait")
    g.add_conditional_edges("gate_1_wait", after_gate(GATE_1), ["finish", "coach", "round_limit", "subdomain"])
    g.add_edge("coach", "coach_answers")
    g.add_edge("coach_answers", "weigher")
    g.add_edge("subdomain", "rescore")
    g.add_edge("rescore", "gate_1_niche")
    g.add_edge("gate_1_niche", "gate_1_niche_wait")
    g.add_conditional_edges("gate_1_niche_wait", after_gate(GATE_1_NICHE), ["finish", "coach", "round_limit"])
    g.add_edge("round_limit", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


_graph = None


def get_graph():
    """The compiled graph with the SQLite checkpointer from config (built once)."""
    global _graph
    if _graph is None:
        from config import get_checkpointer

        _graph = build_graph(get_checkpointer())
    return _graph


def set_graph(graph) -> None:
    """Swap the compiled graph (tests use an in-memory checkpointer)."""
    global _graph
    _graph = graph


# ---------------------------------------------------------------- public interface

def _config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def _check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    return run_id.strip()


def _result(run_id: str) -> dict[str, Any]:
    snap = get_graph().get_state(_config(run_id))
    parts = stubbed_parts()
    meta = {"run_id": run_id, "stubbed": bool(parts), "stubbed_parts": parts}
    if snap.interrupts:
        return {**snap.interrupts[0].value, **meta, "awaiting_founder": True}
    return {**snap.values, **meta, "awaiting_founder": False}


def pending(run_id: str) -> Optional[dict[str, Any]]:
    """What the run is waiting for (the interrupt payload), or None if it is not paused."""
    snap = get_graph().get_state(_config(_check_run_id(run_id)))
    return snap.interrupts[0].value if snap.interrupts else None


def start_run(brief: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Start Phase 1 from the founder's brief and run until the first pause or the end."""
    run_id = _check_run_id(run_id)
    if not isinstance(brief, dict) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a dict with a non-empty 'idea'")
    graph = get_graph()
    if graph.get_state(_config(run_id)).values:
        raise ValueError(f"run_id {run_id!r} already exists; use resume_run or a new run_id")
    load_rubric()  # fail early on a broken rubric
    log_action(agent="orchestrator", action="start_run", model=None, run_id=run_id)
    initial: Briefcase = {
        "run_id": run_id, "brief": dict(brief), "round": 1, "evidence_from_round": 1,
        "current_phase": 1, "stopped": False, "tokens": 0,
    }
    graph.invoke(initial, _config(run_id))
    return _result(run_id)


def resume_run(run_id: str, decision: Union[FounderDecision, dict[str, Any]]) -> dict[str, Any]:
    """Continue a paused run with the founder's reply.

    At a gate only a FounderDecision for that gate is accepted; at questions,
    {"answers": {...}}. Anything else raises and the run stays paused.
    """
    run_id = _check_run_id(run_id)
    waiting = pending(run_id)
    if waiting is None:
        raise ValueError(f"run {run_id!r} is not waiting for the founder")

    if waiting["kind"] == "gate":
        if isinstance(decision, dict):
            decision = FounderDecision(**decision)
        if not isinstance(decision, FounderDecision):
            raise TypeError("this gate needs the founder's FounderDecision; the run cannot continue without it")
        if decision.gate != waiting["gate"] or decision.phase != waiting["phase"]:
            raise ValueError(f"decision is for {decision.gate!r}, but the run is waiting at {waiting['gate']!r}")
        value: dict[str, Any] = decision.model_dump()
    else:
        if isinstance(decision, FounderDecision) or not isinstance(decision, dict) or not isinstance(decision.get("answers", {}), dict):
            raise TypeError('these are questions: resume with {"answers": {field: text}}')
        value = {"answers": decision.get("answers", {}), "accept_revised_idea": decision.get("accept_revised_idea") is True}

    get_graph().invoke(Command(resume=value), _config(run_id))
    return _result(run_id)


__all__ = ["start_run", "resume_run", "pending", "build_graph", "get_graph", "set_graph", "stubbed_parts", "check_category"]
