"""Founder web app (Streamlit, port 8000).

    streamlit run app.py --server.port 8000 --server.address 0.0.0.0

Flow: brief form -> orchestrator.start_run -> the run pauses for the founder:
  kind "questions"  follow-up questions (intake, or the coach after repeat/pivot):
                    a form; answers go back with orchestrator.resume_run.
  kind "gate"       a gate recommendation: evidence, scorecard and a gate card.
                    Approve or Reject (then choose the outcome), with a note.
                    approval.record_decision checks it, and the run resumes with it;
                    the gate logs it with approved_by="founder". Nothing moves on without it.
The page also shows every claim with its tier and link, the run's tokens and cost
(from decision_log.json), the files in outputs/, and MOCKED/STUBBED labels.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from config import settings

OUTCOMES = ("go", "repeat", "pivot", "stop")
OUTCOME_COLORS = {"go": "green", "repeat": "orange", "pivot": "violet", "stop": "red"}
TIER_COLORS = {"A": "green", "B": "blue", "C": "orange", "D": "gray"}
TIER_LABELS = {
    "A": "official",
    "B": "primary",
    "C": "reputable secondary",
    "D": "community signal",
}

# Later phases as the README table states them. Keep the two in line.
PHASES: list[tuple[int, str, str, str]] = [
    (1, "Discover", "", "This app runs it; parts still STUBBED are listed per run."),
    (2, "Validate", "STUBBED", "Lean Canvas and landing-page copy are not built yet."),
    (3, "Build", "STUBBED", "Product, UI/UX and MVP-plan proposals are not built yet."),
    (4, "Commercial setup", "STUBBED", "Pricing and draft policies are not built yet."),
    (5, "Sell/deliver/get paid", "MOCKED", "Fake in-memory payment events: no payment provider, no sandbox, no real money."),
    (6, "Operate and learn", "STUBBED", "Metrics and the persevere-or-pivot memo are not built yet."),
]

BRIEF_LIST_FIELDS = ("skills", "learned", "values", "team_skills")
OUTPUT_EXTS = {".md", ".json", ".csv", ".txt", ".html"}


# ---------------------------------------------------------------- pure helpers (tested)

def new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def brief_from_form(fields: dict[str, Any]) -> dict[str, Any]:
    """Turn raw form values into a brief. Blank fields are left out so intake asks for them."""
    brief: dict[str, Any] = {}
    for key, raw in fields.items():
        if key == "has_team":
            if raw in (True, False):
                brief[key] = raw
            continue
        text = str(raw or "").strip()
        if not text:
            continue
        brief[key] = [s.strip() for s in text.split(",") if s.strip()] if key in BRIEF_LIST_FIELDS else text
    return brief


def tier_badge(claim: dict[str, Any]) -> str:
    """Markdown badge for a claim: its tier, or ASSUMPTION / our own evidence."""
    support = claim.get("support")
    if support == "ASSUMPTION":
        return ":red-badge[ASSUMPTION]"
    if support == "evidence":
        return ":violet-badge[our evidence]"
    tier = str(claim.get("tier") or "NONE")
    if tier not in TIER_COLORS:
        return ":gray-badge[unrated]"
    return f":{TIER_COLORS[tier]}-badge[Tier {tier} · {TIER_LABELS[tier]}]"


def claim_line(claim: dict[str, Any]) -> str:
    """One markdown line per claim: badge, text, and the link with its tier (or the evidence pointer)."""
    text = str(claim.get("text", "")).replace("\n", " ")
    line = f"{tier_badge(claim)} {text}"
    if claim.get("support") == "url" and claim.get("url"):
        line += f" — [source]({claim['url']}) (tier {claim.get('tier', 'NONE')})"
    elif claim.get("support") == "evidence" and claim.get("evidence_ref"):
        line += f" — `{claim['evidence_ref']}`"
    return line


def read_log(path: Optional[Path] = None) -> list[dict[str, Any]]:
    path = Path(path or settings.decision_log_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def run_entries(entries: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """The log entries of one run.

    Every entry carries run_id; for older logs without it, a run is the slice from its
    start_run entry up to the next run's start_run.
    """
    tagged = [e for e in entries if e.get("run_id") == run_id]
    if any(e.get("action") != "start_run" for e in tagged):
        return tagged
    start = None
    for i, e in enumerate(entries):
        if e.get("action") == "start_run" and e.get("run_id") == run_id:
            start = i
    if start is None:
        return []
    out = [entries[start]]
    for e in entries[start + 1:]:
        if e.get("action") == "start_run" and e.get("run_id") != run_id:
            break
        out.append(e)
    return out


def progress_label(entries: list[dict[str, Any]]) -> str:
    """What the run is doing now, in plain words, from its latest log entry."""
    if not entries:
        return "Starting the run…"
    last = entries[-1]
    agent, action = str(last.get("agent", "")), str(last.get("action", ""))
    researched = 0
    for e in reversed(entries):
        if e.get("action") == "split_areas":
            break
        if str(e.get("action", "")).startswith("research_area"):
            researched += 1
    if action == "start_run":
        return "Reading your brief…"
    if agent == "intake":
        return "Checking that the product category is allowed…"
    if action == "category_check":
        return "Splitting your idea into business areas…"
    if action == "split_areas" or agent == "researcher":
        done = f" ({researched} done)" if researched else ""
        return f"Searching the web and rating every source, one business area at a time{done}… this is the slow step."
    if agent in ("skeptic", "scorer"):
        return "Checking your statements and scoring the idea on the rubric…"
    if agent == "gate" and action.endswith("_founder_decision"):
        return "Applying your decision…"
    if agent == "gate":
        return "Comparing the evidence with the target set before the phase…"
    if agent == "coach":
        return "Coach: preparing the next round…"
    if agent == "subdomain":
        return "Placing the idea in a precise niche and researching its competitors…"
    if agent == "orchestrator" and action == "phase1_finished":
        return "Writing the Phase 1 result…"
    return "Working…"


def gate_label(gate: Any) -> str:
    """'gate_1' -> 'Gate 1', 'gate_1_niche' -> 'Gate 1 (niche)'."""
    text = str(gate or "gate")
    if text.startswith("gate_"):
        parts = text.split("_")[1:]
        label = f"Gate {parts[0]}" if parts else "Gate"
        return label + (f" ({' '.join(parts[1:])})" if len(parts) > 1 else "")
    return text


def friendly(text: Any) -> str:
    """Replace gate ids such as gate_1_niche inside a sentence with their labels."""
    return re.sub(r"\bgate_\d+(?:_[a-z]+)*\b", lambda m: gate_label(m.group(0)), str(text or ""))


def run_interrupted(result: Optional[dict[str, Any]]) -> bool:
    """True when a run neither waits for the founder nor has finished (a step failed mid-run)."""
    if not result:
        return False
    return (not result.get("awaiting_founder") and not result.get("stopped")
            and int(result.get("current_phase") or 1) == 1)


def run_usage(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Total tokens, cost (USD) and models over a run's log entries."""
    tokens, cost, models = 0, 0.0, set()
    entries = list(entries)
    for e in entries:
        try:
            tokens += int(e.get("tokens") or 0)
            cost += float(e.get("cost") or 0)
        except (TypeError, ValueError):
            continue
        if e.get("model"):
            models.add(str(e["model"]))
    return {"tokens": tokens, "cost": round(cost, 6), "models": sorted(models), "entries": len(entries)}


def model_hint(exc: BaseException) -> str:
    """A plain next step when the failure is the model being unreachable."""
    text = f"{type(exc).__name__} {exc}".lower()
    if not any(s in text for s in ("connecterror", "connection", "refused", "11434")):
        return ""
    if settings.provider == "ollama":
        return (f" The local model is not reachable at {settings.ollama_base_url}. Start Ollama with "
                f"`{settings.ollama_model}` pulled (docker compose up does both), or put a free GROQ_API_KEY in .env.")
    return " The model provider is not reachable; check the network and the key in .env."


def output_files(folder: Optional[Path] = None) -> list[Path]:
    folder = Path(folder or settings.outputs_dir)
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix in OUTPUT_EXTS]
    return sorted(files, key=lambda p: (-p.stat().st_mtime, p.name))  # newest first


# ---------------------------------------------------------------- orchestrator access

def _orchestrator():
    import orchestrator

    return orchestrator


def run_state(run_id: str) -> dict[str, Any]:
    """The run's saved state (claims, scores, notes), or {}."""
    try:
        orch = _orchestrator()
        if hasattr(orch, "get_state"):
            return dict(orch.get_state(run_id) or {})
        return dict(orch.get_graph().get_state({"configurable": {"thread_id": run_id}}).values or {})
    except Exception:
        return {}


def load_run(run_id: str) -> Optional[dict[str, Any]]:
    """Rebuild the latest result for an existing run (after a page reload or a failed step)."""
    orch = _orchestrator()
    state = run_state(run_id)
    if not state:
        return None
    parts = orch.stubbed_parts()
    meta = {"run_id": run_id, "stubbed": bool(parts), "stubbed_parts": parts}
    waiting = state.get("pending") if "pending" in state else orch.pending(run_id)
    if waiting:
        return {**waiting, **meta, "awaiting_founder": True}
    return {**{k: v for k, v in state.items() if k != "pending"}, **meta, "awaiting_founder": False}


def current_claims(state: dict[str, Any]) -> list[dict[str, Any]]:
    since = state.get("evidence_from_round", 1)
    return [c for c in state.get("claims", []) if c.get("round", 1) >= since]


def rubric_criteria() -> dict[str, dict[str, Any]]:
    try:
        from gates import load_rubric

        return dict(load_rubric().get("criteria", {}))
    except Exception:
        return {}


def cutoffs_text() -> str:
    """' (go at 2.8 or more, stop under 2.0)' from rubric.yaml, or '' if it can't be read."""
    try:
        from gates import load_rubric

        decision = load_rubric().get("decision", {})
        return f" (go at {decision['go_min']} or more, stop under {decision['stop_below']})"
    except Exception:
        return ""


# ---------------------------------------------------------------- UI

def main() -> None:  # pragma: no cover - exercised through streamlit.testing in tests/test_app.py
    import threading
    import time

    import streamlit as st

    st.set_page_config(page_title="Agentic Venture Builder", layout="wide")
    ss = st.session_state
    ss.setdefault("run_id", None)
    ss.setdefault("result", None)
    ss.setdefault("error", None)
    ss.setdefault("model_error", False)

    def call(label: str, fn, *args) -> None:
        """Run an orchestrator call in a thread and show live progress from this run's log entries."""
        ss.error, ss.model_error = None, False
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["result"] = fn(*args)
            except Exception as exc:  # reported below; the run stays where it was
                box["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        started = time.monotonic()
        thread.start()
        with st.status(label, expanded=True) as status:
            line = st.empty()
            while thread.is_alive():
                seconds = int(time.monotonic() - started)
                line.markdown(f"{progress_label(run_entries(read_log(), ss.run_id))}  \n"
                              f":gray[{seconds} s · runs on {settings.provider} `{settings.model_name()}`]")
                thread.join(timeout=1.0)
            if "error" in box:
                status.update(label=f"{label}: failed", state="error")
            else:
                status.update(label=f"{label}: done", state="complete")
        if "error" in box:
            exc = box["error"]
            hint = model_hint(exc)
            ss.error = f"{label} failed: {type(exc).__name__}: {exc}" + hint
            ss.model_error = bool(hint) or "model" in str(exc).lower()
            # Show where the run really is now, not the form that was just sent.
            if ss.run_id:
                reloaded = load_run(ss.run_id)
                if reloaded is not None:
                    ss.result = reloaded
                elif ss.result is None:
                    ss.run_id = None  # the run never started: back to the brief form
        else:
            ss.result = box.get("result")
        st.rerun()

    # ---- sidebar: run, model, cost
    with st.sidebar:
        st.header("Run")
        if ss.run_id:
            st.code(ss.run_id, language=None)
            if st.button("Start a new brief"):
                ss.run_id, ss.result, ss.error, ss.model_error = None, None, None, False
                st.rerun()
        else:
            st.caption("No run yet. Fill in the brief to start one.")
        with st.expander("Open an earlier run"):
            earlier = st.text_input("Run id", key="earlier_run_id")
            if st.button("Open", disabled=not earlier.strip()):
                loaded = load_run(earlier.strip())
                if loaded is None:
                    st.error("No run with that id in the checkpoint store.")
                else:
                    ss.run_id, ss.result, ss.error = earlier.strip(), loaded, None
                    st.rerun()

        st.header("Model")
        st.write(f"Provider: `{settings.provider}` · model: `{settings.model_name()}`")

        if ss.run_id:
            usage = run_usage(run_entries(read_log(), ss.run_id))
            st.header("This run")
            col1, col2 = st.columns(2)
            col1.metric("Tokens", f"{usage['tokens']:,}")
            col2.metric("Cost (USD)", f"${usage['cost']:.2f}")
            budget = getattr(_orchestrator(), "TOKEN_BUDGET", None)
            st.caption((f"Budget {budget:,} tokens per run. " if budget else "")
                       + f"Counted from {usage['entries']} entries in decision_log.json.")

    st.title("Agentic Venture Builder")
    st.caption("Your idea is checked against rated sources and scored on a fixed rubric. "
               "The system recommends; you decide at every gate.")
    render_phase_strip(st, ss.result or {})

    if ss.error:
        st.error(ss.error)
        retry = getattr(_orchestrator(), "retry_run", None)
        if ss.model_error and ss.run_id and callable(retry) and run_interrupted(ss.result):
            if st.button("Retry the failed step", type="primary"):
                call("Retrying", retry, ss.run_id)

    # ---- no run yet: the brief form
    if not ss.run_id:
        st.subheader("Your brief")
        with st.form("brief"):
            idea = st.text_area("Your idea (required)", placeholder="What do you want to build, and for whom?")
            c1, c2 = st.columns(2)
            skills = c1.text_input("Your skills (comma-separated)")
            learned = c2.text_input("What you have learned or tried so far (comma-separated)")
            budget = c1.text_input("Budget")
            time_available = c2.text_input("Time available")
            location = c1.text_input("Location (country)")
            target_market = c2.text_input("Target market")
            values = c1.text_input("Your values (comma-separated)")
            has_team = c2.selectbox("Do you have a team?", ["Not said", "Yes", "No"])
            team_skills = st.text_input("Team members' skills (comma-separated)")
            st.caption("Only the idea is required. Leave a field blank and the intake agent will ask about it.")
            submitted = st.form_submit_button("Start Phase 1", type="primary")
        if submitted:
            if not idea.strip():
                st.error("Please describe your idea.")
            else:
                brief = brief_from_form({
                    "idea": idea, "skills": skills, "learned": learned, "budget": budget,
                    "time_available": time_available, "location": location, "target_market": target_market,
                    "values": values, "team_skills": team_skills,
                    "has_team": {"Yes": True, "No": False}.get(has_team),
                })
                ss.run_id = new_run_id()
                call("Starting the run", _orchestrator().start_run, brief, ss.run_id)
        return

    result = ss.result or {}
    state = run_state(ss.run_id)
    if result.get("stubbed"):
        st.warning("STUBBED parts in this run: " + ", ".join(result.get("stubbed_parts") or []) +
                   ". Their results are placeholders, not research.")

    # ---- paused for questions
    if result.get("awaiting_founder") and result.get("kind") == "questions":
        stage = result.get("stage", "intake")
        if stage == "intake":
            st.subheader("A few questions before the research")
            st.caption("Your answers feed the founder-fit and feasibility scores. Leave a question blank to skip it.")
        else:
            st.subheader(f"Coach: questions after {str(result.get('outcome', '')).upper()}")
            last = (state.get("founder_decisions") or [{}])[-1]
            last_gate = (state.get("gate_results") or [{}])[-1]
            if last:
                st.markdown(f"At {gate_label(last.get('gate'))} the system recommended "
                            f"**{str(last_gate.get('recommendation', '?')).upper()}** and you chose "
                            f"**{str(last.get('outcome', '?')).upper()}**"
                            + (f" (note: {last['note']})" if last.get("note") else "") + ".")
            st.caption("The coach asks what would close the evidence gap. Your answers go into the next research round "
                       f"(round {state.get('round', 1) + 1}).")
        accept = False
        rnd = state.get("round", 1)
        with st.form(f"questions_{stage}_{rnd}"):
            if result.get("needs_accept_revised_idea") and result.get("revised_idea"):
                st.info(f"Proposed revised idea: {result['revised_idea']}")
                accept = st.checkbox("Use this revised idea for the next round")
            answers = {q["field"]: st.text_area(q["question"], key=f"q_{stage}_{rnd}_{q['field']}")
                       for q in result.get("questions", [])}
            send = st.form_submit_button("Send answers and start the research" if stage == "intake" else "Send answers",
                                         type="primary")
        if send:
            reply: dict[str, Any] = {"answers": {k: v for k, v in answers.items() if v.strip()}}
            if result.get("needs_accept_revised_idea"):
                reply["accept_revised_idea"] = accept
            call("Researching your idea", _orchestrator().resume_run, ss.run_id, reply)

    # ---- paused at a gate: the recommendation first, the evidence under it
    elif result.get("awaiting_founder") and result.get("kind") == "gate":
        render_gate_card(st, result, call, key=f"{result.get('gate')}_{len(state.get('gate_results') or [])}")
        render_evidence(st, state)

    # ---- a step failed mid-run
    elif run_interrupted(result):
        st.warning("This run stopped part-way because a step failed (see the message above). "
                   "Nothing was decided for you. Start a new brief, or retry when the model is reachable.")
        render_evidence(st, state)

    # ---- finished
    elif result:
        if result.get("stopped"):
            st.error(f"**Run stopped.** {friendly(result.get('stop_reason', ''))}")
        else:
            st.success(f"**Phase 1 finished.** Next: Phase {result.get('current_phase', 2)}, Validate (STUBBED in this version).")
        if state.get("subdomain"):
            st.markdown(f"**Niche:** {state['subdomain']}")
        if state.get("interview_kit"):
            st.markdown("**Interview kit (ask real people about past behaviour):**")
            st.markdown("\n".join(f"- {q}" for q in state["interview_kit"]))
        decisions = state.get("founder_decisions") or []
        if decisions:
            st.markdown("**Your decisions:** " + "; ".join(
                f"{gate_label(d.get('gate'))}: you {'approved' if d.get('approved') else 'rejected'} the recommendation → "
                f"{str(d.get('outcome')).upper()}"
                + (f" ({d['note']})" if d.get("note") else "") for d in decisions))
        render_evidence(st, state)

    render_outputs(st)
    render_log(st, ss.run_id)


def render_phase_strip(st, result: dict[str, Any]) -> None:  # pragma: no cover - UI
    """The six phases with their status, always visible at the top."""
    # One line of badges that wraps on narrow screens, so no label is ever cut off.
    parts = result.get("stubbed_parts") or []
    chips = []
    for number, name, status, _note in PHASES:
        if number == 1:
            badge = ":orange-badge[partly STUBBED]" if parts else ":green-badge[LIVE]"
        else:
            badge = f":{'violet' if status == 'MOCKED' else 'orange'}-badge[{status}]"
        chips.append(f"**{number}. {name}** {badge}")
    st.markdown(" &nbsp;·&nbsp; ".join(chips))
    st.caption("LIVE: runs on this page. STUBBED: not built yet, nothing runs. "
               "MOCKED: runs on fake data only (no payment provider, no real money).")


def render_evidence(st, state: dict[str, Any]) -> None:  # pragma: no cover - UI
    claims = current_claims(state)
    checks = state.get("claim_checks") or []
    scores = state.get("scores") or {}
    sourced = sum(1 for c in claims if c.get("support") == "url")
    tab_claims, tab_checks, tab_scores = st.tabs([
        f"Evidence ({sourced} sourced / {len(claims)} claims)",
        f"Your statements, checked ({len(checks)})",
        "Scorecard",
    ])
    with tab_claims:
        if not claims:
            if state.get("stopped") and not state.get("areas"):
                st.info("No research was done: the run stopped before it. " + str(state.get("stop_reason", "")))
            else:
                st.info("No claims yet. They appear here once the research step has run.")
        else:
            st.caption("Every source is rated A–D by fixed domain rules (rule: unknown -> B). "
                       "Tier D is a community signal only, never a number. ASSUMPTION means no source was found.")
            areas: dict[str, list[dict[str, Any]]] = {}
            for c in claims:
                areas.setdefault(str(c.get("area") or "other"), []).append(c)
            for area, items in areas.items():
                with st.expander(f"{area.replace('_', ' ')} ({len(items)})", expanded=True):
                    st.markdown("\n".join(f"- {claim_line(c)}" for c in items))
    with tab_checks:
        if not checks:
            st.info("No statements checked yet. The skeptic checks what you claimed in your brief once research has run.")
        colors = {"supported": "green", "contradicted": "red", "unverified": "gray"}
        for c in checks:
            verdict = str(c.get("verdict", "unverified"))
            links = " ".join(f"[link]({u})" for u in c.get("evidence") or [])
            st.markdown(f"- :{colors.get(verdict, 'gray')}-badge[{verdict}] {c.get('statement', '')} — {c.get('why', '')} {links}")
    with tab_scores:
        if not scores:
            st.info("Not scored yet. Scores appear once the evidence has been collected.")
        else:
            criteria = rubric_criteria()
            notes = state.get("score_notes") or {}
            # A markdown table, not st.dataframe: no pandas/numpy needed to show seven rows.
            rows = ["| Criterion | Score (0-4) | Weight | Reason |", "|---|---|---|---|"]
            for name, score in scores.items():
                weight = criteria.get(name, {}).get("weight")
                reason = str(notes.get(name, "")).replace("|", "/").replace("\n", " ")
                rows.append(f"| {name.replace('_', ' ')} | {score} | "
                            f"{f'{weight:.0%}' if isinstance(weight, (int, float)) else ''} | {reason} |")
            st.markdown("\n".join(rows))
            st.caption("The model proposes each score; the weighted total and the recommendation are plain Python "
                       "(gates.py). Weights and cut-offs are our own design choices (rubric.yaml).")


def render_gate_card(st, gate: dict[str, Any], call, key: str) -> None:  # pragma: no cover - UI
    from approval import record_decision

    rec = str(gate.get("recommendation"))
    name = gate_label(gate.get("gate"))
    with st.container(border=True):
        score = gate.get("score")
        score_text = f" · weighted score {score:.2f} / 4" if isinstance(score, (int, float)) else ""
        st.markdown(f"## {name} recommends :{OUTCOME_COLORS.get(rec, 'gray')}[**{rec.upper()}**]")
        if score_text:
            st.caption(score_text.strip(" ·").capitalize() + cutoffs_text())
        st.markdown("\n".join(f"- {friendly(r)}" for r in gate.get("reasons", [])) or "_No reasons given._")
        with st.expander("Target set before the phase, and the evidence behind it"):
            st.markdown(f"**Target:** {gate.get('target', '')}")
            if gate.get("evidence_summary"):
                st.markdown(f"**Evidence:** {gate['evidence_summary']}")

        st.markdown("**Your decision.** Nothing moves on until you choose.")
        choice = st.radio(
            "Decision", ["approve", "reject"], index=None, horizontal=True, key=f"choice_{key}",
            format_func=lambda c: f"Approve: {rec.upper()}" if c == "approve" else "Reject and choose another outcome",
            label_visibility="collapsed",
        )
        outcome: Optional[str] = rec if choice == "approve" else None
        if choice == "reject":
            outcome = st.selectbox("Outcome instead", [o for o in OUTCOMES if o != rec], index=None,
                                   format_func=str.upper, key=f"outcome_{key}")
            if rec == "stop" and outcome:
                st.warning("You are overriding a STOP recommendation. This is recorded in decision_log.json and the gate file.")
        note = st.text_input("Note (optional)", key=f"note_{key}")
        if st.button("Record my decision", type="primary", disabled=choice is None or outcome is None):
            run_id = gate.get("run_id") or st.session_state.run_id

            def decide_and_resume():
                decision = record_decision(run_id, gate, approved=choice == "approve", outcome=outcome, note=note)
                # Sent as a dict: resume_run rebuilds it with its own FounderDecision class. Streamlit
                # can reload project modules between reruns, and then two copies of the class exist,
                # so an isinstance check on the object itself would wrongly refuse the decision.
                return _orchestrator().resume_run(run_id, decision.model_dump())

            call("Recording your decision", decide_and_resume)


def render_outputs(st) -> None:  # pragma: no cover - UI
    files = output_files()
    with st.expander(f"Output files ({len(files)} in outputs/, newest first)"):
        if not files:
            st.caption("No output files yet. Each step writes one here as it finishes.")
            return
        st.caption("Each step writes its file here; a later run overwrites files with the same step name.")
        chosen = st.selectbox("File", files, format_func=lambda p: p.name)
        text = chosen.read_text(encoding="utf-8", errors="replace")
        if chosen.suffix == ".md":
            st.markdown(text)
        elif chosen.suffix == ".json":
            try:
                st.json(json.loads(text))
            except ValueError:
                st.code(text)
        else:
            st.code(text, language=None)


def render_log(st, run_id: Optional[str]) -> None:  # pragma: no cover - UI
    if not run_id:
        return
    from tools.credibility import rate

    entries = run_entries(read_log(), run_id)
    with st.expander(f"Decision log for this run ({len(entries)} entries)"):
        if not entries:
            st.caption("No entries yet.")
        for e in entries:
            who = " · approved by founder" if e.get("approved_by") == "founder" else ""
            st.markdown(f"`{e.get('timestamp', '')}` **{e.get('agent')}** {e.get('action')}"
                        f"{' · ' + str(e['model']) if e.get('model') else ''}{who}")
            for url in e.get("sources") or []:
                try:
                    tier = rate(url)
                except ValueError:
                    tier = "?"
                st.markdown(f"  - [{url}]({url}) (tier {tier})")


if __name__ == "__main__":
    main()
