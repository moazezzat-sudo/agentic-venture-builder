"""Run one brief through every wired phase (Gate 1 -> niche gate -> Phases 2-6 -> finish) and time it.

    python evals/briefs/run_full_path.py S1

This is a test of the pipeline, not a founder's run, so the script answers the gates itself:
  - where the gate recommends go, it approves;
  - otherwise it rejects and chooses go (a founder override, logged with approved_by "founder"
    and overrides_recommendation true), so every phase is reached;
  - at Gate 2 it sets a waitlist target of 100 and leaves the real count empty: no sign-ups
    are invented, so Gate 2 recommends repeat and the script overrides it.
Founder questions (intake, coach) get no answers. Outputs, the decision log and checkpoints go
to a temporary folder, never to outputs/ or decision_log.json. Prints per-phase seconds and
tokens (tokens summed from that run's decision_log.json).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = Path(tempfile.mkdtemp(prefix="full_path_"))
os.environ["OUTPUTS_DIR"] = str(TMP / "outputs")
os.environ["DECISION_LOG_PATH"] = str(TMP / "decision_log.json")
os.environ["CHECKPOINT_DB"] = str(TMP / "checkpoints.sqlite")
sys.path.insert(0, str(ROOT))

import orchestrator  # noqa: E402
from approval import record_decision  # noqa: E402
from config import settings  # noqa: E402

sys.path.insert(0, str(HERE))
from results_md import render  # noqa: E402

GATE_2_ANSWERS = {"waitlist_target": "100", "paid_orders": "10"}  # no real count: never invented

# Which phase each logged agent belongs to, for per-phase tokens.
AGENT_PHASE = {"phase2_lean_canvas": 2, "phase3_build_plan": 3, "phase3_build": 3, "phase4_commercial": 4,
               "phase5_launch": 5, "phase6_memo": 6}


def main(brief_id: str) -> int:
    briefs = {b["id"]: b for b in json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]}
    brief = dict(briefs[brief_id]["brief"])
    run_id = f"full-{brief_id}-{int(time.time())}"
    seconds: dict[int, float] = {}
    gates: list[dict] = []

    def timed(phase_of_pause, fn, *args):
        start = time.time()
        result = fn(*args)
        phase = phase_of_pause(result)
        seconds[phase] = seconds.get(phase, 0.0) + time.time() - start
        return result

    def phase_of(result: dict) -> int:
        if result.get("awaiting_founder"):
            if result.get("kind") == "gate":
                return int(result["phase"])
            return 2 if result.get("stage") == "gate_2_targets" else 1
        return int(result.get("current_phase") or 1)

    result = timed(phase_of, orchestrator.start_run, brief, run_id)
    while result.get("awaiting_founder"):
        if result["kind"] == "questions":
            answers = GATE_2_ANSWERS if result.get("stage") == "gate_2_targets" else {}
            reply = {"answers": answers, "accept_revised_idea": False}
            result = timed(phase_of, orchestrator.resume_run, run_id, reply)
            continue
        rec = result["recommendation"]
        approved = rec == "go"
        gates.append({"gate": result["gate"], "phase": result["phase"], "recommended": rec,
                      "chose": "go", "override": not approved})
        decision = record_decision(run_id, result, approved=approved, outcome="go",
                                   note="Pipeline test: approve go; otherwise override to go to reach every phase.")
        result = timed(phase_of, orchestrator.resume_run, run_id, decision)

    entries = json.loads((TMP / "decision_log.json").read_text(encoding="utf-8"))
    tokens: dict[int, int] = {}
    phase = 1
    for e in entries:
        phase = AGENT_PHASE.get(e.get("agent"), phase)
        tokens[phase] = tokens.get(phase, 0) + int(e.get("tokens") or 0)
    total_tokens = orchestrator.run_tokens(run_id)
    report = {
        "ran_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "brief": brief_id, "run_id": run_id, "provider": settings.provider,
        "models": [settings.model_name("smart"), settings.model_name("fast")],
        "ended": {"stopped": result.get("stopped"), "phase": result.get("current_phase")},
        "gates": gates,
        "per_phase": {p: {"seconds": round(seconds.get(p, 0.0), 1), "tokens": tokens.get(p, 0)} for p in range(1, 7)},
        "total": {"seconds": round(sum(seconds.values()), 1), "tokens": total_tokens},
        "files": sorted(p.name for p in (TMP / "outputs").glob("*")),
        "run_folder": str(TMP),
    }
    print(json.dumps(report, indent=2))
    saved = {k: v for k, v in report.items() if k not in ("files", "run_folder")}
    (HERE / "full_path.json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
    print(f"results: {render()}")
    return 0 if not result.get("stopped") and result.get("current_phase") == 6 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "S1"))
