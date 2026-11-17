"""The evaluation memo at a gate: why the system recommends what it does, citing the evidence by claim id.

    from agents.evaluation_memo import write_memo
    memo = write_memo(briefcase, gate_result)
    # {"verdict", "headline", "why": [{"text", "claim_ids"}],
    #  "per_criterion": [{"criterion", "score", "explanation", "claim_ids", "counter_evidence", "what_would_change"}],
    #  "unknowns": [...], "next_steps": [...], "source": "model" | "fallback", "removed": {...}}

Python provides the facts: the verdict and reasons from gates.py, the scores, and the claims with ids
(C1, C2 ... as the app numbers them) and kinds (pain, competitors, pricing, market, regulation). The model
only writes the explanations, in one small call. Python then validates them:
  - every claim_id must exist; unknown ids are dropped (and counted in "removed");
  - in a text without a valid claim id, any sentence with a number is removed and the rest is marked
    "ASSUMPTION:" (plain "no evidence" statements stay as they are);
  - any sentence that breaks a guardrail (income promises, fake social proof ...) is removed.
next_steps are built in Python from the verdict: go -> the riskiest assumption to test first; repeat ->
exactly which evidence to gather and how (with the Mom Test kit); pivot -> two directions backed by
the evidence; stop -> why, and what new evidence would change the decision.
Without a usable model reply, a template memo is built from the gate reasons and claims.
Also writes outputs/phase1_step5_evaluation.md (citations as [C3], with a sources list), STUBBED
until the memo runs end to end in the graph.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Union

import agents._common as common
from agents.questions import ask
from logger import log_action, write_output
from schemas import GateResult

KIND_BY_AREA = {"problem_evidence": "pain", "problem": "pain", "competition": "competitors", "competitors": "competitors",
                "willingness_to_pay": "pricing", "pricing": "pricing", "market": "market", "rules_risk": "regulation",
                "regulation": "regulation"}
CRITERIA = ("problem_evidence", "market", "competition", "founder_fit", "feasibility", "willingness_to_pay", "rules_risk")
NO_EVIDENCE = re.compile(r"\b(no evidence|not stated|unknown|we don't know|no sourced|no claim)", re.I)
CITE = re.compile(r"\[(C\d+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")

SYSTEM = """You explain an evaluation of a founder's idea. The verdict and scores are decided already by fixed rules: explain them, never change them. No praise, no promises of income or success.
Use only the numbered claims given (ids like C3) and cite them in claim_ids. Never state a number or fact that is not in a cited claim.
Reply with JSON only. Example for a different idea:
{"headline":"The pain is real but nobody has shown they would pay.","why":[{"text":"Three forum threads describe bakeries losing phone orders.","claim_ids":["C1","C2","C4"]}],"per_criterion":[{"criterion":"willingness_to_pay","explanation":"No price page or paid alternative was found.","claim_ids":[],"counter_evidence":"","what_would_change":"A competitor's price page or bakeries that already pay for ordering."}],"unknowns":["How many orders a bakery loses each week"]}
Write 2-4 "why" items, one per_criterion item for each criterion given, and 2-4 unknowns."""

EVIDENCE_HOW = {
    "problem_evidence": "Find 3 independent sources where people describe this pain (forum threads, reviews, groups), and run the Mom Test interview kit with 5 people in the target group, asking when it last happened and what it cost them.",
    "market": "Find an official (tier A) or primary (tier B) number for how many people or businesses in the location have this problem, such as the national statistics office or the World Bank.",
    "competition": "List what people use today instead (tools, services, workarounds), with each one's own page, and note which are free.",
    "willingness_to_pay": "Collect price pages of paid alternatives, and ask in the interviews what they paid last time they solved this.",
    "founder_fit": "Write down which skills the build needs that you and your team don't have, and who could fill them.",
    "feasibility": "Cut the first version to what you can build in your stated time and budget, and estimate it.",
    "rules_risk": "Check the regulator's or government's own site for any rule, licence or consent this needs.",
}
CHANGE_IF = {
    "problem_evidence": "independent sources showing people have this pain",
    "competition": "sourced evidence that the free alternatives don't solve the problem",
    "rules_risk": "a version of the product outside the banned categories, with an official source for any rule it touches",
    "market": "an official or primary number showing enough reachable customers",
}


# --------------------------------------------------------------------------- facts


def claim_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Claims by id, numbered like the app: the claim's own id, else C1, C2 ... in order."""
    from agents.scorer import current_claims

    index = {}
    for i, c in enumerate(current_claims(state), start=1):
        cid = str(c.get("id") or f"C{i}")
        index[cid] = {**c, "id": cid, "kind": c.get("kind") or KIND_BY_AREA.get(str(c.get("area") or ""), "other")}
    return index


def _gate(gate_result: Union[GateResult, dict[str, Any]]) -> dict[str, Any]:
    return gate_result.model_dump() if isinstance(gate_result, GateResult) else dict(gate_result)


def _scores(state: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in (state.get("scores") or {}).items() if isinstance(v, (int, float))}


# --------------------------------------------------------------------------- validation


def _ids(raw: Any, index: dict[str, Any], removed: dict[str, int]) -> list[str]:
    out = []
    for cid in raw if isinstance(raw, list) else []:
        cid = str(cid).strip().strip("[]")
        if cid in index:
            out.append(cid) if cid not in out else None
        elif cid:
            removed["unknown_claim_ids"] += 1
    return out


def clean_text(text: Any, ids: list[str], index: dict[str, Any], removed: dict[str, int], label: bool = True) -> str:
    """Drop unknown inline ids, uncited numbers and guardrail hits; mark uncited statements ASSUMPTION."""
    from guardrails import check_text

    text = " ".join(str(text or "").split())

    def inline(m: re.Match) -> str:
        if m.group(1) in index:
            return m.group(0)
        removed["unknown_claim_ids"] += 1
        return ""

    text = CITE.sub(inline, text)
    cited = bool(ids) or bool(CITE.search(text))
    kept = []
    for s in SENTENCE.split(text):
        s = s.strip()
        if not s:
            continue
        if check_text(s):
            removed["guardrail_sentences"] += 1
            continue
        if not cited and re.search(r"\d", s):
            removed["uncited_numbers"] += 1
            continue
        kept.append(s)
    out = " ".join(kept)
    if out and not cited and label and not NO_EVIDENCE.search(out) and not out.startswith("ASSUMPTION"):
        out = f"ASSUMPTION: {out}"
    return common.cut(out, 400)


# --------------------------------------------------------------------------- next steps


def next_steps(verdict: str, gate: dict[str, Any], state: dict[str, Any], index: dict[str, Any]) -> list[str]:
    scores = _scores(state)
    lowest = sorted((k for k in scores if k in EVIDENCE_HOW), key=lambda k: scores[k])
    if verdict == "go":
        assumptions = (state.get("discovery") or {}).get("assumptions") or []
        risk = assumptions[0]["text"] if assumptions else (f"the weakest criterion, {lowest[0]}" if lowest else "the riskiest assumption")
        return [f"Test the riskiest assumption first: {risk}.",
                "Run the Mom Test interview kit (outputs/phase1_step9_interview_kit.md) with 5 people in the target group before building.",
                "Set the waitlist target for Gate 2 before the test starts."]
    if verdict == "repeat":
        steps = [f"{c.replace('_', ' ').capitalize()} (score {scores[c]:g} of 4): {EVIDENCE_HOW[c]}" for c in lowest[:2]]
        steps.append("Use the Mom Test interview kit (outputs/phase1_step9_interview_kit.md): ask about past behaviour, never whether they would buy.")
        return steps
    if verdict == "pivot":
        pains = [c for c in index.values() if c["kind"] == "pain" and c.get("support") == "url"]
        comps = [c for c in index.values() if c["kind"] == "competitors" and c.get("support") == "url"]
        steps = []
        if pains:
            p = pains[0]
            steps.append(f"Keep the pain shown in [{p['id']}] ({common.cut(p['text'], 120)}) and aim it at a narrower customer group that has it most.")
        if comps:
            c = comps[0]
            steps.append(f"Start from what people use today, shown in [{c['id']}] ({common.cut(c['text'], 120)}), and offer the one thing it does badly.")
        while len(steps) < 2:
            steps.append("ASSUMPTION: no sourced claim supports a direction yet. Gather pain evidence first, then choose a direction.")
        return steps
    reasons = [r for r in gate.get("reasons") or [] if r]
    zeros = [c for c in CHANGE_IF if scores.get(c) == 0]
    steps = [f"Why stop: {' '.join(reasons[:2]) or 'the evidence is too weak.'}"]
    for c in zeros or lowest[:2]:
        steps.append(f"What would change this: {CHANGE_IF.get(c) or EVIDENCE_HOW.get(c, 'stronger sourced evidence')}.")
    return steps


# --------------------------------------------------------------------------- memo


def _fallback(gate: dict[str, Any], state: dict[str, Any], index: dict[str, Any], removed: dict[str, int],
              scores: dict[str, float]) -> dict[str, Any]:
    notes = state.get("score_notes") or {}
    verdict = str(gate.get("recommendation") or "repeat")
    per = []
    cited = state.get("score_claims") or {}
    for c in [c for c in CRITERIA if c in scores]:
        note = str(notes.get(c, ""))
        # The scorer's cited ids when it records them; else its 0-based list ([2]) -> the app's 1-based ids (C3).
        ids = [i for i in cited.get(c) or [] if i in index] or [
            f"C{int(n) + 1}" for n in re.findall(r"\[(\d+)\]", note) if f"C{int(n) + 1}" in index]
        note = re.sub(r"\[(\d+)\]", lambda m: f"[C{int(m.group(1)) + 1}]", note)
        per.append({"criterion": c, "score": scores[c], "explanation": clean_text(note, ids, index, removed) or "No explanation recorded.",
                    "claim_ids": ids, "counter_evidence": "", "what_would_change": EVIDENCE_HOW.get(c, "")})
    return {
        "headline": f"The fixed rules recommend {verdict.upper()}.",
        "why": [{"text": clean_text(r, [], index, removed, label=False), "claim_ids": []} for r in gate.get("reasons") or [] if r],
        "per_criterion": per,
        "unknowns": [f"{c.replace('_', ' ')}: {EVIDENCE_HOW[c]}" for c in sorted(scores, key=scores.get)[:2] if c in EVIDENCE_HOW],
        "source": "fallback",
    }


def write_memo(state: dict[str, Any], gate_result: Union[GateResult, dict[str, Any]], status: str = "STUBBED") -> dict[str, Any]:
    gate = _gate(gate_result)
    verdict = str(gate.get("recommendation") or "repeat")
    phase = int(gate.get("phase") or 1)
    index = claim_index(state)
    # The rubric scores belong to Phase 1; later gates explain their own reasons only.
    scores = _scores(state) if phase == 1 else {}
    removed = {"unknown_claim_ids": 0, "uncited_numbers": 0, "guardrail_sentences": 0}

    payload = {
        "verdict": verdict, "weighted_score": gate.get("score"), "rules_triggered": gate.get("reasons") or [],
        "scores": scores, "criteria": [c for c in CRITERIA if c in scores],
        "claims": [{"id": c["id"], "kind": c["kind"], "text": common.cut(c.get("text"), 160), "tier": c.get("tier")}
                   for c in list(index.values())[:15]],
    }
    data, usage = ask("evaluation_memo", SYSTEM, payload,
                      '{"headline":"...","why":[{"text":"...","claim_ids":["C1"]}],"per_criterion":[{"criterion":"...","explanation":"...",'
                      '"claim_ids":[],"counter_evidence":"","what_would_change":"..."}],"unknowns":["..."]}',
                      ("headline", "why", "per_criterion"), max_tokens=900)

    memo: Optional[dict[str, Any]] = None
    if data:
        why = []
        for w in data.get("why") if isinstance(data.get("why"), list) else []:
            if isinstance(w, dict):
                ids = _ids(w.get("claim_ids"), index, removed)
                text = clean_text(w.get("text"), ids, index, removed)
                if text:
                    why.append({"text": text, "claim_ids": ids})
        by_name = {str(p.get("criterion")): p for p in data.get("per_criterion") or [] if isinstance(p, dict)}
        per = []
        for c in [c for c in CRITERIA if c in scores]:
            p = by_name.get(c, {})
            ids = _ids(p.get("claim_ids"), index, removed)
            per.append({
                "criterion": c, "score": scores[c],  # the score always comes from Python, never the model
                "explanation": clean_text(p.get("explanation"), ids, index, removed) or "No explanation written.",
                "claim_ids": ids,
                "counter_evidence": clean_text(p.get("counter_evidence"), [], index, removed),
                "what_would_change": clean_text(p.get("what_would_change"), [], index, removed, label=False) or EVIDENCE_HOW.get(c, ""),
            })
        headline = clean_text(data.get("headline"), [], index, removed, label=False)
        unknowns = [u for u in (clean_text(x, [], index, removed, label=False) for x in (data.get("unknowns") or [])[:4]) if u]
        if headline and why:
            memo = {"headline": headline, "why": why, "per_criterion": per, "unknowns": unknowns, "source": "model"}
    if memo is None:
        memo = _fallback(gate, state, index, removed, scores)

    memo = {"verdict": verdict, **memo, "next_steps": next_steps(verdict, gate, state if phase == 1 else {}, index),
            "removed": removed}
    if phase == 1:
        path = write_output(1, 5, "evaluation", memo_markdown(memo, index), status=status)
    else:
        path = write_output(phase, 9, "evaluation", memo_markdown(memo, index).replace("Phase 1, step 5", f"Phase {phase}"), status=status)
    cited = sorted({cid for w in memo["why"] for cid in w["claim_ids"]} | {cid for p in memo["per_criterion"] for cid in p["claim_ids"]})
    log_action(agent="evaluation_memo", action="write_memo", sources=[index[c]["url"] for c in cited if index[c].get("url")],
               run_id=state.get("run_id"), outcome=verdict, memo_source=memo["source"], removed=removed, output=path.name,
               **common.model_fields(usage))
    return memo


def memo_markdown(memo: dict[str, Any], index: dict[str, Any]) -> str:
    def cites(ids: list[str]) -> str:
        return " ".join(f"[{i}]" for i in ids)

    why = "\n".join(f"- {w['text']} {cites(w['claim_ids'])}".rstrip() for w in memo["why"]) or "- _None._"
    crit = "\n".join(
        f"### {p['criterion'].replace('_', ' ')}: {p['score']:g} of 4\n\n{p['explanation']} {cites(p['claim_ids'])}".rstrip()
        + (f"\n\nAgainst: {p['counter_evidence']}" if p.get("counter_evidence") else "")
        + (f"\n\nWhat would change this score: {p['what_would_change']}" if p.get("what_would_change") else "")
        for p in memo["per_criterion"]) or "_No scores._"
    cited = sorted({c for w in memo["why"] for c in w["claim_ids"]} | {c for p in memo["per_criterion"] for c in p["claim_ids"]},
                   key=lambda c: int(c[1:]) if c[1:].isdigit() else 0)
    sources = []
    for cid in cited:
        c = index[cid]
        tag = f"tier {c.get('tier')}, [{c['url']}]({c['url']})" if c.get("support") == "url" else (
            f"our evidence: {c.get('evidence_ref')}" if c.get("support") == "evidence" else "ASSUMPTION")
        sources.append(f"- [{cid}] {common.cut(c.get('text'), 160)} ({c['kind']}; {tag})")
    return (
        f"# Phase 1, step 5: evaluation memo\n\n**Verdict: {memo['verdict'].upper()}** (decided by the fixed rules in gates.py; "
        f"the founder decides at the gate). Written by: {memo['source']}.\n\n## {memo['headline']}\n\n## Why\n\n{why}\n\n"
        f"## Per criterion\n\n{crit}\n\n## What we don't know yet\n\n" + ("\n".join(f"- {u}" for u in memo["unknowns"]) or "- _None listed._")
        + "\n\n## Next steps\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(memo["next_steps"], 1))
        + "\n\n## Sources\n\n" + ("\n".join(sources) or "- _No claims cited._") + "\n"
    )


__all__ = ["write_memo", "claim_index", "clean_text", "next_steps", "memo_markdown"]
