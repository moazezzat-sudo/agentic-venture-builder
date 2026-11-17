"""Phase 2 (Validate), step 1: Lean Canvas and landing-page copy for the waitlist test.

    from agents.phase2_lean_canvas import agent
    update = agent(briefcase)   # {"drafts": {"phase2_lean_canvas": {...}}, "text_violations": [...], "tokens": n}

Every canvas item is a claim: it cites a Phase 1 evidence number (URL or our evidence) or it
is an ASSUMPTION; numbers from the founder's own inputs are ASSUMPTIONs. The landing-page copy
passes guardrails.check_text (one rewrite, then flagged). The waitlist target is the founder's,
set before the test, and the real sign-up count is entered by the founder later: nothing here
invents either. Writes outputs/phase2_step1_lean_canvas.md (STUBBED until wired into the graph).
"""

from __future__ import annotations

from typing import Any

from agents import phase2_6_shared as shared

AGENT = "phase2_lean_canvas"

CELLS = [
    ("problem", "Problem"),
    ("customer_segments", "Customer segments"),
    ("unique_value_proposition", "Unique value proposition"),
    ("solution", "Solution"),
    ("channels", "Channels"),
    ("revenue_streams", "Revenue streams"),
    ("cost_structure", "Cost structure"),
    ("key_metrics", "Key metrics"),
    ("unfair_advantage", "Unfair advantage"),
]

SYSTEM = """You draft a Lean Canvas for a founder's digital product. Be skeptical: no praise, no invented numbers, no income or success promises.
Input: the founder's brief, the niche, and numbered research evidence.
Every item has "source": the evidence number it rests on, or null if nothing supports it. Numbers from the brief get null.
One fact per item: never add a number or fact the cited evidence doesn't contain; put your own estimate in a separate item with source null.
Reply with JSON only, at most 3 items per cell:
{"problem":[{"text":"","source":null}],"customer_segments":[],"unique_value_proposition":[],"solution":[],"channels":[],"revenue_streams":[],"cost_structure":[],"key_metrics":[],"unfair_advantage":[],"unit_economics":[],"riskiest_assumption":"","landing_page":{"headline":"","subheadline":"","bullets":[""],"call_to_action":""}}
unfair_advantage may be [{"text":"None yet","source":null}].
Landing page: describe the product plainly. No testimonials, user counts, ratings, urgency or promises. The call to action joins a waitlist."""


def agent(state: dict[str, Any]) -> dict[str, Any]:
    evidence = shared.phase1_evidence(state)
    payload = shared.base_payload(state, evidence)
    data, found, usage = shared.ask_guarded(AGENT, SYSTEM, payload, round_no=int(state.get("round") or 1), max_tokens=1100)

    canvas = {key: shared.claims_for(data.get(key), evidence, key, AGENT, limit=3) for key, _ in CELLS}
    economics = shared.claims_for(data.get("unit_economics"), evidence, "unit_economics", AGENT, limit=4)
    lp = data.get("landing_page") if isinstance(data.get("landing_page"), dict) else {}
    landing = {
        "headline": shared.common.cut(lp.get("headline", ""), 120),
        "subheadline": shared.common.cut(lp.get("subheadline", ""), 200),
        "bullets": shared.strings(lp.get("bullets"), limit=4, chars=160),
        "call_to_action": shared.common.cut(lp.get("call_to_action", ""), 60),
    }
    riskiest = shared.common.cut(data.get("riskiest_assumption", ""), 240)
    claims = [c for key, _ in CELLS for c in canvas[key]] + economics

    sections = "\n\n".join(f"### {label}\n\n{shared.bullet_claims(canvas[key])}" for key, label in CELLS)
    body = (
        f"## Lean Canvas\n\n{sections}\n\n"
        f"## Unit economics (from the founder's inputs)\n\n{shared.bullet_claims(economics)}\n\n"
        "These are ASSUMPTIONs unless a source is shown. They are not income projections.\n\n"
        f"## Riskiest assumption\n\n{riskiest or '_Not stated by the model._'}\n\n"
        "## Landing-page copy (for the waitlist test)\n\n"
        f"**{landing['headline'] or '_No headline._'}**\n\n{landing['subheadline']}\n\n{shared.bullets(landing['bullets'])}\n\n"
        f"Call to action: {landing['call_to_action'] or '_none_'}\n\n"
        "Draft only: nothing is published. The founder edits, approves and publishes the page.\n\n"
        "## Waitlist test\n\n"
        "- Target: set by the founder **before** the test (for example, a number of sign-ups in 14 days). Not set by the system.\n"
        "- Real sign-up count: entered by the founder after the test. **STUBBED** until then; never estimated or invented.\n"
    )
    draft = {"canvas": canvas, "unit_economics": economics, "riskiest_assumption": riskiest, "landing_page": landing,
             "waitlist": {"target": None, "real_count": None}}
    return shared.finish(state, AGENT, 2, 1, "lean canvas", "Lean Canvas and landing-page copy", body, draft, claims, found, usage)
