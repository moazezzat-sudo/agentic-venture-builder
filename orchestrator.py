"""Runs Phase 1 (Discover) as a LangGraph graph and pauses at every gate for the founder.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from orchestrator import start_run, resume_run
    result = start_run(brief, run_id)          # runs until the first pause
    result = resume_run(run_id, reply)         # continues after the founder answers
    state = get_state(run_id)                  # read-only: the run's saved state, or None
    result = retry_run(run_id)                 # after an error (e.g. model timeout): re-run the failed step

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
from pathlib import Path
from typing import Any, Optional, Union

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agents import coach, discovery, intake, researcher, scorer, search_plan, skeptic, subdomain, weigher
from agents._common import describe_violation, text_violations
from agents.scorer import current_claims
import gates as gates_mod
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
    log_action(agent="guardrails", action="category_check", model=None, run_id=state.get("run_id"),
               allowed=allowed, category=category, stubbed=stubbed)
    status = "STUBBED" if stubbed else "Working"
    write_output(1, 1, "category check", (
        f"# Phase 1, step 1: category check\n\nAllowed: **{allowed}**\n\nCategory: {category}\n\nReason: {reason}\n"
    ), status=status)
    if allowed:
        return {}
    result = GateResult(
        phase=1, gate="category_check", recommendation="stop", reasons=[reason],
        target="The product is digital and not in a banned category", evidence_summary="Stopped before any research.",
    )
    write_gate(1, "decision", _gate_markdown(result, None), status=status)
    log_action(agent="gate", action="category_check_stop", model=None, run_id=state.get("run_id"), outcome="stop")
    return {"stopped": True, "stop_reason": reason, "gate_results": [result.model_dump()]}


def after_category_check(state: Briefcase) -> str:
    if state.get("stopped"):
        return "finish"
    return "discovery_skip" if discovery.has_confirmed_understanding(state["brief"]) else "discovery_prepare"


def fan_out(state: Briefcase) -> list[Send]:
    """One researcher per area, in parallel."""
    return [
        Send("researcher", {"research_area": {**area, "index": i}, "brief": state["brief"], "round": state.get("round", 1),
                            "run_id": state.get("run_id")})
        for i, area in enumerate(state["areas"])
    ]


def _memo_markdown(memo: Optional[dict[str, Any]]) -> str:
    if not memo:
        return ""
    why = "\n".join(f"- {w['text']}" + (f" ({', '.join(w['claim_ids'])})" if w.get("claim_ids") else "")
                    for w in memo.get("why") or [])
    unknowns = "\n".join(f"- {u}" for u in memo.get("unknowns") or []) or "- _none listed_"
    steps = "\n".join(f"- {n}" for n in memo.get("next_steps") or []) or "- _none listed_"
    return (f"## Evaluation memo\n\n**{memo.get('headline', '')}**\n\n{why}\n\n"
            f"Still unknown:\n{unknowns}\n\nNext steps:\n{steps}\n\n")


def _gate_markdown(result: GateResult, decision: Optional[FounderDecision], memo: Optional[dict[str, Any]] = None) -> str:
    reasons = "\n".join(f"- {r}" for r in result.reasons)
    score = f"{result.score:.2f} of 4" if result.score is not None else "not scored"
    body = (
        f"# Phase {result.phase} gate: {result.gate}\n\n"
        f"Recommendation: **{result.recommendation.upper()}**\n\nWeighted score: {score}\n\n"
        f"Target set before the phase: {result.target}\n\nEvidence: {result.evidence_summary}\n\n## Reasons\n\n{reasons}\n\n"
        + _memo_markdown(memo) +
        "The recommendation comes from fixed rules in gates.py"
        + (" and rubric.yaml; the weights and cut-offs are our design choices" if result.phase == 1 else "")
        + ".\n\n"
        "## Founder decision\n\n"
    )
    if decision is None:
        return body + "_Waiting for the founder._\n"
    override = " This **overrides** the recommendation." if decision.outcome != result.recommendation else ""
    return body + (
        f"Founder chose **{decision.outcome.upper()}** (approved the recommendation: {decision.approved}).{override}\n\n"
        f"Note: {decision.note or '_none_'}\n\nDecided at {decision.decided_at}, approved_by: founder.\n"
    )


GATE_FILES = {GATE_1: "decision", GATE_1_NICHE: "niche_decision", "gate_3_plan": "plan_decision"}


def _gate_file(gate: str) -> str:
    """outputs/phase<N>_gate_<this>.md"""
    return GATE_FILES.get(gate, "decision")


def current_drafts(state: Briefcase) -> dict[str, str]:
    """Text our agents wrote for this round, to run through guardrails.check_text before the gate.

    Sourced claims are left out: they report what a source says, not what we claim.
    ASSUMPTION claims are our own statements, so they are checked.
    """
    drafts: dict[str, str] = {}
    for i, area in enumerate(state.get("areas") or []):
        drafts[f"area {i}"] = f"{area.get('name', '')}. {area.get('query', '')}"
    for i, c in enumerate(current_claims(state)):
        if c.get("support") == "ASSUMPTION":
            drafts[f"assumption {i}"] = c.get("text", "")
    for i, check in enumerate(state.get("claim_checks") or []):
        drafts[f"skeptic check {i}"] = check.get("why", "")
    for name, note in (state.get("score_notes") or {}).items():
        drafts[f"score reason: {name}"] = note
    coach_notes = state.get("coach_notes") or {}
    if coach_notes:
        drafts["coach"] = " ".join([coach_notes.get("revised_idea", ""), *coach_notes.get("missing_evidence", []),
                                    *coach_notes.get("questions", [])])
    if state.get("subdomain"):
        drafts["niche"] = state["subdomain"]
    for i, q in enumerate(state.get("interview_kit") or []):
        drafts[f"interview question {i + 1}"] = q
    return drafts


def make_gate_eval(gate: str):
    def node(state: Briefcase) -> dict[str, Any]:
        round_no = state.get("round", 1)
        draft_hits = text_violations(current_drafts(state), True, round_no)
        founder_hits = [v for v in state.get("text_violations") or [] if not v.get("rewritable")]
        gaps = [f"\"{g['area']}\" ({g['focus']})" for g in state.get("search_gaps") or [] if g.get("round") == round_no]
        if state.get("scoring_incomplete"):
            result = gates_mod.evaluate_scoring_incomplete(state["scoring_incomplete"], gate)
        else:
            result = evaluate_gate_1(
                state["scores"], current_claims(state),
                violations=[describe_violation(v) for v in founder_hits],
                rewritable_violations=[describe_violation(v) for v in draft_hits],
                evidence_gaps=gaps,
            ).model_copy(update={"gate": gate})
        memo = build_memo(state, result)
        write_gate(1, _gate_file(gate), _gate_markdown(result, None, memo))
        log_action(agent="gate", action=gate, model=None, run_id=state.get("run_id"), outcome=result.recommendation,
                   score=result.score, round=round_no, guardrail_violations=[v["rule"] for v in founder_hits + draft_hits],
                   memo_source=memo.get("source"))
        return {"gate_results": [{**result.model_dump(), "memo": memo}], "text_violations": draft_hits}

    node.__name__ = f"{gate}_eval"
    return node


def make_gate_wait(gate: str):
    def node(state: Briefcase) -> dict[str, Any]:
        last = state["gate_results"][-1]
        result = GateResult(**last)
        # Pauses until the founder answers. resume_run only accepts a FounderDecision here.
        reply = interrupt({"kind": "gate", **result.model_dump(), "memo": last.get("memo") or {}})
        decision = FounderDecision(**reply)
        if decision.gate != gate or decision.phase != result.phase:
            raise ValueError(f"decision is for {decision.gate!r}, but the run is waiting at {gate!r}")
        check_approval(decision, result.recommendation)
        decision = decision.model_copy(update={"overrides_recommendation": decision.outcome != result.recommendation})
        write_gate(result.phase, _gate_file(gate), _gate_markdown(result, decision, last.get("memo")))
        log_action(agent="gate", action=f"{gate}_founder_decision", model=None, approved_by="founder",
                   run_id=state.get("run_id"), round=state.get("round", 1),
                   outcome=decision.outcome, recommendation=result.recommendation,
                   approved=decision.approved, note=decision.note,
                   overrides_recommendation=decision.overrides_recommendation,
                   overrode_stop=result.recommendation == "stop" and decision.outcome != "stop")
        update: dict[str, Any] = {"founder_decisions": [decision.model_dump()]}
        if decision.outcome == "stop":
            update.update(stopped=True, stop_reason=f"Founder chose stop at {gate}.")
        if decision.outcome == "repeat" and gate in PHASE_GATE_NODES:
            repeats = dict(state.get("phase_repeats") or {})
            repeats[gate] = repeats.get(gate, 0) + 1
            update["phase_repeats"] = repeats
            # "Request changes" = repeat with a note: the phase reruns once with the note in the brief,
            # which every phase agent sends to the model.
            brief = {k: v for k, v in state["brief"].items() if k != "change_request"}
            if decision.note.strip():
                brief["change_request"] = decision.note.strip()
            update["brief"] = brief
        return update

    node.__name__ = f"{gate}_wait"
    return node


def check_approval(decision: FounderDecision, recommendation: str) -> None:
    """Approve keeps the recommended outcome; Reject must pick a different one (team decision, 15:20)."""
    if decision.approved and decision.outcome != recommendation:
        raise ValueError(f"approved means keeping the recommendation ({recommendation}); got outcome {decision.outcome!r}")
    if not decision.approved and decision.outcome == recommendation:
        raise ValueError(f"rejecting the recommendation ({recommendation}) needs a different outcome")


def after_gate(gate: str):
    def route(state: Briefcase) -> str:
        outcome = state["founder_decisions"][-1]["outcome"]
        if outcome == "stop":
            return "finish"
        if outcome in ("repeat", "pivot"):
            return "coach" if state.get("round", 1) < MAX_ROUNDS else "round_limit"
        return "subdomain" if gate == GATE_1 else "phase_2"

    return route


def round_limit_node(state: Briefcase) -> dict[str, Any]:
    reason = f"Stopped: {MAX_ROUNDS} rounds of repeat/pivot used without reaching go."
    log_action(agent="orchestrator", action="round_limit_stop", model=None, run_id=state.get("run_id"),
               round=state.get("round", 1))
    return {"stopped": True, "stop_reason": reason}


def run_tokens(run_id: str) -> int:
    """Tokens for one run = the sum of "tokens" over the decision_log entries since its start_run entry.

    This includes calls logged by other modules (for example the guardrails category check).
    """
    import json

    import logger

    path = logger.settings.decision_log_path
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return 0
    entries = json.loads(path.read_text(encoding="utf-8"))
    starts = [i for i, e in enumerate(entries) if e.get("action") == "start_run" and e.get("run_id") == run_id]
    since = starts[-1] if starts else 0
    return sum(int(e.get("tokens") or 0) for e in entries[since:])


def finish_node(state: Briefcase) -> dict[str, Any]:
    stopped = bool(state.get("stopped"))
    tokens = run_tokens(state["run_id"])
    phase = int(state.get("current_phase") or 1)
    # "run_tokens", not "tokens": this entry reports the total and must not be summed again.
    log_action(agent="orchestrator", action="run_finished", model=None, run_id=state.get("run_id"),
               stopped=stopped, phase=phase, run_tokens=tokens,
               over_token_budget=tokens > TOKEN_BUDGET)
    last = state.get("gate_results", [{}])[-1] if state.get("gate_results") else {}
    done = "**All six phases finished; the founder approved go at every gate.**\n\n"
    write_output(phase, 10 if phase == 1 else 9, "result", (
        f"# Run result (ended in Phase {phase})\n\n"
        + (f"**Stopped in Phase {phase}.** {state.get('stop_reason', '')}\n\n" if stopped else done)
        + f"Last gate: {last.get('gate', 'none')}, recommended {str(last.get('recommendation', 'n/a')).upper()}.\n\n"
        + f"Rounds: {state.get('round', 1)}. Model tokens used: {tokens}, summed from decision_log.json "
        f"(budget {TOKEN_BUDGET}).\n"
        + (f"\nNiche: {state['subdomain']}\n" if state.get("subdomain") else "")
    ))
    return {"current_phase": phase}


# ---------------------------------------------------------------- graph

def build_graph(checkpointer=None):
    g = StateGraph(Briefcase)
    g.add_node("category_check", category_check_node)
    g.add_node("discovery_prepare", discovery.prepare_node)
    g.add_node("discovery_ask", discovery.ask_node)
    g.add_node("discovery_confirm", discovery.confirm_node)
    g.add_node("discovery_skip", discovery.skip_node)
    g.add_node("category_recheck", category_check_node)
    g.add_node("search_plan", search_plan.node)
    g.add_node("researcher", researcher.evidence_node)
    g.add_node("research_summary", researcher.summary_node)
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

    g.add_edge(START, "category_check")
    g.add_conditional_edges("category_check", after_category_check, ["finish", "discovery_prepare", "discovery_skip"])
    g.add_conditional_edges("discovery_prepare", discovery.after_prepare, ["discovery_ask", "discovery_confirm"])
    g.add_edge("discovery_ask", "discovery_prepare")
    g.add_conditional_edges("discovery_confirm", discovery.after_confirm, ["category_recheck", "discovery_prepare"])
    g.add_conditional_edges("category_recheck", lambda s: "finish" if s.get("stopped") else "search_plan",
                            ["finish", "search_plan"])
    g.add_edge("discovery_skip", "search_plan")
    g.add_conditional_edges("search_plan", researcher.fan_out_plan, ["researcher"])
    g.add_edge("researcher", "research_summary")
    g.add_edge("research_summary", "skeptic")
    g.add_edge("skeptic", "scorer")
    g.add_edge("scorer", "gate_1")
    g.add_edge("gate_1", "gate_1_wait")
    g.add_conditional_edges("gate_1_wait", after_gate(GATE_1), ["finish", "coach", "round_limit", "subdomain"])
    g.add_edge("coach", "coach_answers")
    g.add_edge("coach_answers", "search_plan")
    g.add_edge("subdomain", "rescore")
    g.add_edge("rescore", "gate_1_niche")
    g.add_edge("gate_1_niche", "gate_1_niche_wait")
    g.add_conditional_edges("gate_1_niche_wait", after_gate(GATE_1_NICHE), ["finish", "coach", "round_limit", "phase_2"])
    add_later_phases(g)
    g.add_edge("round_limit", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------- Phases 2-6

# (node, phase, agent module, gate). Each phase ends at its own founder gate; go moves to the next row.
LATER_PHASES = [
    ("phase_2", 2, "agents.phase2_lean_canvas", "gate_2"),
    ("phase_3_plan", 3, "agents.phase3_build_plan", "gate_3_plan"),
    ("phase_3_build", 3, "agents.phase3_build", "gate_3"),
    ("phase_4", 4, "agents.phase4_commercial", "gate_4"),
    ("phase_5", 5, "agents.phase5_launch", "gate_5"),
    ("phase_6", 6, "agents.phase6_memo", "gate_6"),
]
PHASE_GATE_NODES = {gate: node for node, _, _, gate in LATER_PHASES}
MAX_PHASE_REPEATS = 2  # repeats chosen at one gate before the run stops
GATE_2_QUESTIONS = [
    {"field": "waitlist_target", "question": "Waitlist test: how many sign-ups is your target, set before the test? (a number)"},
    {"field": "waitlist_count", "question": "How many real sign-ups do you have? Leave this empty if the test has not run yet."},
    {"field": "paid_orders", "question": "For Phase 6: how many paid orders in the first month would mean it works? (a number)"},
]


def make_phase_node(phase: int, module_name: str):
    def node(state: Briefcase) -> dict[str, Any]:
        import importlib

        update = dict(importlib.import_module(module_name).agent(state))
        update["current_phase"] = phase
        update["text_violations"] = [{**v, "phase": phase} for v in update.get("text_violations") or []]
        return update

    node.__name__ = module_name.rsplit(".", 1)[-1]
    return node


def gate_2_targets_node(state: Briefcase) -> dict[str, Any]:
    """Pause for the founder's waitlist target and real count. Nothing is estimated for them."""
    reply = interrupt({"kind": "questions", "stage": "gate_2_targets", "questions": GATE_2_QUESTIONS}) or {}
    answers = {k: str(v).strip() for k, v in (reply.get("answers") or {}).items() if str(v).strip()}
    targets = dict(state.get("targets") or {})
    for field in ("waitlist_target", "waitlist_count", "paid_orders"):
        if field in answers:
            try:
                targets[field] = int(answers[field].replace(",", ""))
            except ValueError:
                targets[field] = None  # not a number: treated as not entered
    log_action(agent="gate", action="gate_2_targets", model=None, approved_by="founder", run_id=state.get("run_id"),
               targets=targets)
    return {"targets": targets, "founder_answers": {**(state.get("founder_answers") or {}), **answers}}


def _payment_test() -> tuple[bool, str]:
    """Hashish's MOCKED sale-to-cash test (payments.run_payment_test), written to outputs/payment_test_log.md."""
    import tempfile

    import logger
    from payments import run_payment_test

    out = Path(logger.settings.outputs_dir) / "payment_test_log.md"
    path = run_payment_test(out_path=out, log_path=Path(tempfile.mkdtemp()) / "mock_store_log.json")
    failed = path.read_text(encoding="utf-8").count("| FAIL |")
    return failed == 0, f"{failed} step(s) failed" if failed else "all steps passed"


def make_phase_gate_eval(gate: str):
    def node(state: Briefcase) -> dict[str, Any]:
        drafts = state.get("drafts") or {}
        extra: dict[str, Any] = {}
        if gate == "gate_2":
            result = gates_mod.evaluate_gate_2(drafts.get("phase2_lean_canvas") or {}, state.get("targets") or {})
        elif gate == "gate_3_plan":
            result = gates_mod.evaluate_gate_3_plan(drafts.get("phase3_build_plan") or {})
        elif gate == "gate_3":
            result = gates_mod.evaluate_gate_3(drafts.get("phase3_build") or {})
        elif gate == "gate_4":
            result = gates_mod.evaluate_gate_4(drafts.get("phase4_commercial") or {})
        elif gate == "gate_5":
            passed, note = _payment_test()
            extra = {"payment_test_passed": passed, "payment_test": note}
            result = gates_mod.evaluate_gate_5(drafts.get("phase5_launch") or {}, passed, note)
        else:
            result = gates_mod.evaluate_gate_6(drafts.get("phase6_memo") or {})
        memo = build_memo(state, result)
        write_gate(result.phase, _gate_file(gate), _gate_markdown(result, None, memo))
        log_action(agent="gate", action=gate, model=None, run_id=state.get("run_id"), phase=result.phase,
                   outcome=result.recommendation, memo_source=memo.get("source"), **extra)
        return {"gate_results": [{**result.model_dump(), "memo": memo}]}

    node.__name__ = f"{gate}_eval"
    return node


def after_phase_gate(gate: str, next_node: str, phase_node: str):
    def route(state: Briefcase) -> str:
        outcome = state["founder_decisions"][-1]["outcome"]
        if outcome == "stop":
            return "finish"
        if outcome == "pivot":
            return "coach" if state.get("round", 1) < MAX_ROUNDS else "round_limit"
        if outcome == "repeat":
            if (state.get("phase_repeats") or {}).get(gate, 0) > MAX_PHASE_REPEATS:
                return "repeat_limit"
            draft = (state.get("drafts") or {}).get("phase2_lean_canvas") or {}
            changes = (state.get("brief") or {}).get("change_request")
            # Gate 2 usually repeats for a missing real count: ask again rather than redraft the canvas,
            # unless the founder asked for changes or the draft broke a guardrail.
            return "gate_2_targets" if gate == "gate_2" and not draft.get("violations") and not changes else phase_node
        return next_node

    return route


BUILD_FORMATS = ["A guide or checklist (Markdown files)", "A small single-page tool (HTML)", "Let the build agent choose"]


def build_options_node(state: Briefcase) -> dict[str, Any]:
    """Before the build: the founder picks the product format and says what the first version must include."""
    questions = [
        {"id": "product_format", "text": "What should the first version be?",
         "why": "The build makes the simplest honest product in this format.", "suggestions": [], "choices": BUILD_FORMATS},
        {"id": "must_include", "text": "Anything the first version must include?",
         "why": "The build agent gets this with the plan.", "suggestions": [], "choices": None},
    ]
    reply = interrupt({"kind": "questions", "stage": "build_options", "questions": questions}) or {}
    answers = {k: str(v).strip() for k, v in (reply.get("answers") or {}).items() if str(v).strip()}
    chosen = answers.get("product_format") if answers.get("product_format") in BUILD_FORMATS else BUILD_FORMATS[2]
    prefs = {"product_format": chosen, "must_include": answers.get("must_include", "")}
    log_action(agent="gate", action="build_options", model=None, approved_by="founder", run_id=state.get("run_id"),
               **prefs)
    return {"brief": {**state["brief"], "build_preferences": prefs}}


def build_memo(state: Briefcase, result: GateResult) -> dict[str, Any]:
    """Build the live gate memo in Python from gate reasons and the scores' claim ids.

    agents/evaluation_memo.py is not called by this path; no model call is made here.
    """
    # The plain Python memo below is the one used in the live run: it is built only from the gate's
    # reasons and the scores' cited claim ids, so it can't drop or invent evidence on a small local model.
    scores, notes, cited = state.get("scores") or {}, state.get("score_notes") or {}, state.get("score_claims") or {}
    per_criterion = [{"criterion": c, "score": scores[c], "claim_ids": cited.get(c, []), "reasoning": notes.get(c, "")}
                     for c in scores] if result.phase == 1 else []
    ids = sorted({i for v in cited.values() for i in v}, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    unknowns = [f"{p['criterion']}: no claim cited" for p in per_criterion if not p["claim_ids"]
                and p["criterion"] not in ("founder_fit", "feasibility")]
    headline = {"go": "Go: the evidence meets the target set before the phase.",
                "repeat": "Repeat: more evidence or another pass is needed first.",
                "pivot": "Pivot: the pain looks real, the idea as framed does not.",
                "stop": "Stop: the evidence says not to continue."}[result.recommendation]
    next_steps = {"go": ["Approve to continue to the next phase."],
                  "repeat": ["Answer the coach's questions, or request changes with a note."],
                  "pivot": ["Review the coach's revised idea."],
                  "stop": ["Approve the stop, or override it with a note (logged as an override)."]}[result.recommendation]
    return {"verdict": result.recommendation, "headline": headline,
            "why": [{"text": r, "claim_ids": []} for r in result.reasons]
            + [{"text": f"{p['criterion']} {p['score']:g}/4: {p['reasoning']}", "claim_ids": p["claim_ids"]}
               for p in per_criterion if p["claim_ids"]],
            "per_criterion": per_criterion, "unknowns": unknowns, "next_steps": next_steps,
            "claim_ids": ids, "source": "fallback"}


def repeat_limit_node(state: Briefcase) -> dict[str, Any]:
    reason = f"Stopped: repeat chosen more than {MAX_PHASE_REPEATS} times at one gate."
    log_action(agent="orchestrator", action="repeat_limit_stop", model=None, run_id=state.get("run_id"))
    return {"stopped": True, "stop_reason": reason}


def add_later_phases(g) -> None:
    """Phases 2-6 after the niche gate: agent -> (Gate 2: founder's targets) -> gate rule -> founder pause."""
    g.add_node("gate_2_targets", gate_2_targets_node)
    g.add_node("repeat_limit", repeat_limit_node)
    g.add_edge("repeat_limit", "finish")
    g.add_node("build_options", build_options_node)
    g.add_edge("build_options", "phase_3_build")
    for i, (node, phase, module, gate) in enumerate(LATER_PHASES):
        next_node = LATER_PHASES[i + 1][0] if i + 1 < len(LATER_PHASES) else "finish"
        if gate == "gate_3_plan":
            next_node = "build_options"  # the founder picks the product format before anything is built
        g.add_node(node, make_phase_node(phase, module))
        g.add_node(gate, make_phase_gate_eval(gate))
        g.add_node(f"{gate}_wait", make_gate_wait(gate))
        if gate == "gate_2":
            g.add_edge(node, "gate_2_targets")
            g.add_edge("gate_2_targets", gate)
        else:
            g.add_edge(node, gate)
        g.add_edge(gate, f"{gate}_wait")
        targets = sorted({next_node, "finish", "coach", "round_limit", "repeat_limit", node}
                         | ({"gate_2_targets"} if gate == "gate_2" else set()))
        g.add_conditional_edges(f"{gate}_wait", after_phase_gate(gate, next_node, node), targets)


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


def get_state(run_id: str) -> Optional[dict[str, Any]]:
    """The saved state of a run, for the app: the Briefcase fields (brief, areas, claims, scores,
    claim_checks, gate_results, founder_decisions, round, stopped, current_phase, ...) plus
    run_id, awaiting_founder and pending (what the run is waiting for, or None).

    Returns None when there is no run with this id. Read-only: it never moves the run on.
    """
    snap = get_graph().get_state(_config(_check_run_id(run_id)))
    if not snap.values:
        return None
    waiting = snap.interrupts[0].value if snap.interrupts else None
    return {**snap.values, "run_id": run_id, "awaiting_founder": waiting is not None, "pending": waiting}


def failed_step(run_id: str) -> Optional[dict[str, Any]]:
    """The step a run stopped on because of an error (for example a model timeout), or None.

    {"node": name, "error": text}. A run paused for the founder, or finished, has no failed step.
    """
    snap = get_graph().get_state(_config(_check_run_id(run_id)))
    if not snap.values or not snap.next or snap.interrupts:
        return None
    errored = [t for t in snap.tasks if getattr(t, "error", None)]
    task = errored[0] if errored else snap.tasks[0] if snap.tasks else None
    return {"node": task.name if task else snap.next[0], "error": str(getattr(task, "error", "") or "")}


def retry_run(run_id: str) -> dict[str, Any]:
    """Re-run the step that failed (for example after a model timeout) from the last checkpoint.

    Steps that already finished are not run again; parallel researchers that finished keep
    their results. Raises ValueError when the run has not failed: a paused run continues with
    resume_run, a finished one cannot continue. Returns the same dict as start_run.
    """
    run_id = _check_run_id(run_id)
    failed = failed_step(run_id)
    if failed is None:
        raise ValueError(f"run {run_id!r} has no failed step to retry (paused runs continue with resume_run)")
    log_action(agent="orchestrator", action="retry_run", model=None, run_id=run_id,
               node=failed["node"], error=failed["error"][:200])
    get_graph().invoke(None, _config(run_id))
    return _result(run_id)


def pending(run_id: str) -> Optional[dict[str, Any]]:
    """What the run is waiting for (the interrupt payload), or None if it is not paused."""
    snap = get_graph().get_state(_config(_check_run_id(run_id)))
    return snap.interrupts[0].value if snap.interrupts else None


def _reject_credential_input(value: Any) -> None:
    """Check founder input before it can enter graph state, prompts or the log."""
    from guardrails import check_text

    if isinstance(value, dict):
        for key, item in value.items():
            _reject_credential_input(key)
            _reject_credential_input(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_credential_input(item)
    elif isinstance(value, (str, int)) and any(hit["rule"] == "credentials" for hit in check_text(str(value))):
        raise ValueError("Remove passwords, card details and API keys before submitting this input.")


def start_run(brief: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Start Phase 1 from the founder's brief and run until the first pause or the end."""
    run_id = _check_run_id(run_id)
    if not isinstance(brief, dict) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a dict with a non-empty 'idea'")
    _reject_credential_input((run_id, brief))
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
    reply = decision.model_dump() if isinstance(decision, FounderDecision) else decision
    _reject_credential_input((run_id, reply))
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
        check_approval(decision, waiting["recommendation"])
        value: dict[str, Any] = decision.model_dump()
    else:
        if isinstance(decision, FounderDecision) or not isinstance(decision, dict) or not isinstance(decision.get("answers", {}), dict):
            raise TypeError('these are questions: resume with {"answers": {field: text}}')
        value = {"answers": decision.get("answers", {}), "accept_revised_idea": decision.get("accept_revised_idea") is True}

    get_graph().invoke(Command(resume=value), _config(run_id))
    return _result(run_id)


__all__ = ["start_run", "resume_run", "retry_run", "failed_step", "get_state", "pending", "build_graph", "get_graph", "set_graph", "stubbed_parts", "check_category"]
