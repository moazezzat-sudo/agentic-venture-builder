"""Run Phase 1 evaluation briefs to Gate 1 and record what Gate 1 recommends.

    python evals/briefs/run_briefs.py weak banned --repeat 2   # or: strong, all, or brief ids (W1 S2 ...)

Each brief runs with the configured model (see .env) up to the first founder pause. Nothing is
decided for the founder: the run is left paused at Gate 1. Outputs, the decision log and checkpoints
go to a temporary folder, never to outputs/ or decision_log.json. The results are written to
evals/briefs/brief_runs.json and RESULTS.md (overwritten each time), and printed.
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

# Must be set before config is imported: keep this run's files out of the repo.
TMP = Path(tempfile.mkdtemp(prefix="brief_eval_"))
os.environ["OUTPUTS_DIR"] = str(TMP / "outputs")
os.environ["DECISION_LOG_PATH"] = str(TMP / "decision_log.json")
os.environ["CHECKPOINT_DB"] = str(TMP / "checkpoints.sqlite")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import orchestrator  # noqa: E402
from config import settings  # noqa: E402
from results_md import render  # noqa: E402


def select(briefs: list[dict], args: list[str]) -> list[dict]:
    wanted = set(args or ["all"])
    if "all" in wanted:
        return briefs
    return [b for b in briefs if b["set"] in wanted or b["id"] in wanted]


def run_one(item: dict) -> dict:
    run_id = f"eval-{item['id']}-{int(time.time())}"
    start = time.time()
    try:
        result = orchestrator.start_run(dict(item["brief"]), run_id)
        error = None
    except Exception as exc:  # report it; never hide a failed run
        result, error = {}, f"{type(exc).__name__}: {exc}"
    seconds = round(time.time() - start, 1)
    if result.get("awaiting_founder") and result.get("kind") == "gate":
        got, score, reasons = result["recommendation"], result.get("score"), result.get("reasons", [])
    elif result and not result.get("awaiting_founder"):
        last = (result.get("gate_results") or [{}])[-1]
        got, score, reasons = last.get("recommendation", "stop" if result.get("stopped") else "?"), last.get("score"), last.get("reasons", [])
    elif result.get("kind") == "questions":
        got, score, reasons = "paused for questions", None, [q["question"] for q in result.get("questions", [])]
    else:
        got, score, reasons = "error", None, [error or "no result"]
    ok = (got == "stop") if item["expect"] == "stop" else (got not in ("stop", "error", "paused for questions"))
    return {"id": item["id"], "set": item["set"], "kind": item.get("kind", ""), "expect": item["expect"], "got": got,
            "ok": ok, "score": score, "reasons": reasons, "seconds": seconds,
            "tokens": orchestrator.run_tokens(run_id), "idea": item["brief"]["idea"], "researched": researched(run_id)}


def researched(run_id: str) -> bool:
    """Whether any research step ran (a banned idea must stop before research)."""
    entries = json.loads((TMP / "decision_log.json").read_text(encoding="utf-8"))
    return any(e.get("run_id") == run_id and e.get("agent") == "researcher" for e in entries)


def main(args: list[str]) -> int:
    repeat, strong_once = 1, "--strong-once" in args  # --strong-once: repeat only the briefs expected to stop
    args = [a for a in args if a != "--strong-once"]
    if "--repeat" in args:
        i = args.index("--repeat")
        repeat, args = int(args[i + 1]), args[:i] + args[i + 2:]
    briefs = json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    rows = []
    for item in select(briefs, args):
        for n in range(1, (1 if strong_once and item["set"] == "strong" else repeat) + 1):
            row = {**run_one(item), "run": n}
            rows.append(row)
            print(f"{row['id']} run {n}: expected {row['expect']}, got {row['got']} "
                  f"({'ok' if row['ok'] else 'NOT AS EXPECTED'}), {row['seconds']}s, {row['tokens']} tokens, "
                  f"research ran: {row['researched']}", flush=True)
    data = {"ran_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "provider": settings.provider,
            "models": [settings.model_name("smart"), settings.model_name("fast")], "repeat": repeat, "rows": rows}
    (HERE / "brief_runs.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"results: {render()}  (run files in {TMP})")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
