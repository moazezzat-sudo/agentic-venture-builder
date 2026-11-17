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
    """The log entries of one run: from its start_run entry up to the next run's start_run.

    Agent entries do not carry run_id, so a run is the slice after its own start.
    """
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
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in OUTPUT_EXTS)


# ---------------------------------------------------------------- orchestrator access

def _orchestrator():
    import orchestrator

    return orchestrator


def run_state(run_id: str) -> dict[str, Any]:
    """The run's Briefcase from the checkpointer (claims, scores, notes), or {}."""
    try:
        graph = _orchestrator().get_graph()
        return dict(graph.get_state({"configurable": {"thread_id": run_id}}).values or {})
    except Exception:
        return {}


def load_run(run_id: str) -> Optional[dict[str, Any]]:
    """Rebuild the latest result for an existing run (after a page reload)."""
    orch = _orchestrator()
    state = run_state(run_id)
    if not state:
        return None
    parts = orch.stubbed_parts()
    meta = {"run_id": run_id, "stubbed": bool(parts), "stubbed_parts": parts}
    waiting = orch.pending(run_id)
    if waiting:
        return {**waiting, **meta, "awaiting_founder": True}
    return {**state, **meta, "awaiting_founder": False}


def current_claims(state: dict[str, Any]) -> list[dict[str, Any]]:
    since = state.get("evidence_from_round", 1)
    return [c for c in state.get("claims", []) if c.get("round", 1) >= since]


def rubric_criteria() -> dict[str, dict[str, Any]]:
    try:
        from gates import load_rubric

        return dict(load_rubric().get("criteria", {}))
    except Exception:
        return {}


# ---------------------------------------------------------------- UI

def main() -> None:  # pragma: no cover - exercised through streamlit.testing in tests/test_app.py
    import streamlit as st

    st.set_page_config(page_title="Agentic Venture Builder", layout="wide")
    ss = st.session_state
    ss.setdefault("run_id", None)
    ss.setdefault("result", None)
    ss.setdefault("error", None)

    def call(label: str, fn, *args) -> None:
        ss.error = None
        try:
            with st.spinner(label):
                ss.result = fn(*args)
        except Exception as exc:  # show the reason; the run stays where it was
            ss.error = f"{label} failed: {type(exc).__name__}: {exc}" + model_hint(exc)
        st.rerun()

    # ---- sidebar: run, model, cost, phases
    with st.sidebar:
        st.header("Run")
        if ss.run_id:
            st.code(ss.run_id, language=None)
            if st.button("Start a new brief"):
                ss.run_id, ss.result, ss.error = None, None, None
                st.rerun()
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
            col2.metric("Cost (USD)", f"${usage['cost']:.4f}")
            budget = getattr(_orchestrator(), "TOKEN_BUDGET", None)
            if budget:
                st.caption(f"Budget {budget:,} tokens per run. From {usage['entries']} entries in decision_log.json.")

        st.header("Phases")
        result = ss.result or {}
        for number, name, status, note in PHASES:
            label = f"**{number}. {name}**"
            if number == 1:
                parts = result.get("stubbed_parts") or []
                st.markdown(label + (" :orange-badge[partly STUBBED]" if parts else ""))
                for part in parts:
                    st.caption(f"STUBBED: {part}")
            else:
                color = "violet" if status == "MOCKED" else "orange"
                st.markdown(f"{label} :{color}-badge[{status}]")
                st.caption(note)

    st.title("Agentic Venture Builder")
    st.caption("Phase 1, Discover: your idea is checked against rated sources and scored on a fixed rubric. "
               "The system recommends; you decide at every gate.")
    if ss.error:
        st.error(ss.error)

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
            st.caption("Leave a field blank and the intake agent will ask about it.")
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
        st.subheader("Follow-up questions" if stage == "intake" else f"Coach: questions after {str(result.get('outcome', '')).upper()}")
        accept = False
        rnd = state.get("round", 1)
        with st.form(f"questions_{stage}_{rnd}"):
            if result.get("needs_accept_revised_idea") and result.get("revised_idea"):
                st.info(f"Proposed revised idea: {result['revised_idea']}")
                accept = st.checkbox("Use this revised idea for the next round")
            answers = {q["field"]: st.text_area(q["question"], key=f"q_{stage}_{rnd}_{q['field']}")
                       for q in result.get("questions", [])}
            send = st.form_submit_button("Send answers", type="primary")
        if send:
            reply: dict[str, Any] = {"answers": {k: v for k, v in answers.items() if v.strip()}}
            if result.get("needs_accept_revised_idea"):
                reply["accept_revised_idea"] = accept
            call("Continuing the run", _orchestrator().resume_run, ss.run_id, reply)

    # ---- paused at a gate
    elif result.get("awaiting_founder") and result.get("kind") == "gate":
        render_evidence(st, state)
        render_gate_card(st, result, call, key=f"{result.get('gate')}_{len(state.get('gate_results') or [])}")

    # ---- finished
    elif result:
        if result.get("stopped"):
            st.error(f"Run stopped. {result.get('stop_reason', '')}")
        else:
            st.success(f"Phase 1 finished. Next: Phase {result.get('current_phase', 2)} (STUBBED in this version).")
        if state.get("subdomain"):
            st.markdown(f"**Niche:** {state['subdomain']}")
        if state.get("interview_kit"):
            st.markdown("**Interview kit (ask real people about past behaviour):**")
            st.markdown("\n".join(f"- {q}" for q in state["interview_kit"]))
        render_evidence(st, state)
        decisions = state.get("founder_decisions") or []
        if decisions:
            st.subheader("Your decisions")
            for d in decisions:
                st.markdown(f"- {d.get('gate')}: {'approved' if d.get('approved') else 'rejected'}, "
                            f"outcome **{str(d.get('outcome')).upper()}**" + (f" — {d['note']}" if d.get("note") else ""))

    render_outputs(st)
    render_log(st, ss.run_id)


def render_evidence(st, state: dict[str, Any]) -> None:  # pragma: no cover - UI
    claims = current_claims(state)
    st.subheader("Evidence")
    if not claims:
        st.caption("No claims yet.")
    else:
        sourced = sum(1 for c in claims if c.get("support") == "url")
        st.caption(f"{len(claims)} claims, {sourced} with a source. Every source is rated A–D by fixed domain rules "
                   "(rule: unknown -> B). Tier D is a community signal only, never a number.")
        areas: dict[str, list[dict[str, Any]]] = {}
        for c in claims:
            areas.setdefault(str(c.get("area") or "other"), []).append(c)
        for area, items in areas.items():
            with st.expander(f"{area.replace('_', ' ')} ({len(items)})", expanded=True):
                st.markdown("\n".join(f"- {claim_line(c)}" for c in items))

    checks = state.get("claim_checks") or []
    if checks:
        st.subheader("Your statements, checked")
        colors = {"supported": "green", "contradicted": "red", "unverified": "gray"}
        for c in checks:
            verdict = str(c.get("verdict", "unverified"))
            links = " ".join(f"[link]({u})" for u in c.get("evidence") or [])
            st.markdown(f"- :{colors.get(verdict, 'gray')}-badge[{verdict}] {c.get('statement', '')} — {c.get('why', '')} {links}")

    scores = state.get("scores") or {}
    if scores:
        st.subheader("Scorecard")
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
        st.caption("The model proposes each score; the weighted total and the recommendation are plain Python (gates.py). "
                   "Weights and cut-offs are our own design choices (rubric.yaml).")


def render_gate_card(st, gate: dict[str, Any], call, key: str) -> None:  # pragma: no cover - UI
    from approval import record_decision

    rec = str(gate.get("recommendation"))
    with st.container(border=True):
        st.subheader(f"Gate: {gate.get('gate')}")
        cols = st.columns(3)
        with cols[0]:
            st.markdown("Recommendation")
            st.badge(rec.upper(), color=OUTCOME_COLORS.get(rec, "gray"))
        cols[1].metric("Weighted score (0-4)", f"{gate['score']:.2f}" if isinstance(gate.get("score"), (int, float)) else "n/a")
        cols[2].markdown(f"**Target set before the phase**\n\n{gate.get('target', '')}")
        if gate.get("evidence_summary"):
            st.markdown(f"**Evidence:** {gate['evidence_summary']}")
        st.markdown("**Reasons**\n" + "\n".join(f"- {r}" for r in gate.get("reasons", [])))

        st.divider()
        st.markdown("**Your decision.** Nothing moves on until you choose.")
        choice = st.radio(
            "Decision", ["approve", "reject"], index=None, horizontal=True, key=f"choice_{key}",
            format_func=lambda c: f"Approve: {rec.upper()}" if c == "approve" else "Reject and choose another outcome",
        )
        outcome: Optional[str] = rec if choice == "approve" else None
        if choice == "reject":
            outcome = st.selectbox("Outcome instead", [o for o in OUTCOMES if o != rec], index=None,
                                   format_func=str.upper, key=f"outcome_{key}")
            if rec == "stop" and outcome:
                st.warning("You are overriding a STOP recommendation. This is recorded in decision_log.json and the gate file.")
        note = st.text_area("Note (optional)", key=f"note_{key}")
        if st.button("Record my decision", type="primary", disabled=choice is None or outcome is None):
            run_id = gate.get("run_id") or st.session_state.run_id

            def decide_and_resume():
                decision = record_decision(run_id, gate, approved=choice == "approve", outcome=outcome, note=note)
                return _orchestrator().resume_run(run_id, decision)

            call("Recording your decision", decide_and_resume)


def render_outputs(st) -> None:  # pragma: no cover - UI
    files = output_files()
    with st.expander(f"Outputs ({len(files)} files in outputs/)"):
        if not files:
            st.caption("No outputs yet.")
            return
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
