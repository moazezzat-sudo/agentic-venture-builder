"""Run Phase 1 evaluation briefs to Gate 1 and record what Gate 1 recommends.

    python evals/briefs/run_briefs.py weak          # or: strong, banned, all, or brief ids (W1 S2 ...)

Each brief runs with the configured model (see .env) up to the first founder pause. Nothing is
decided for the founder: the run is left paused at Gate 1. Outputs, the decision log and checkpoints
go to a temporary folder, never to outputs/ or decision_log.json. The results are written to
evals/briefs/results.md (overwritten each time), and printed.
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

import orchestrator  # noqa: E402
from config import settings  # noqa: E402


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
            "tokens": orchestrator.run_tokens(run_id), "idea": item["brief"]["idea"]}


def write_results(rows: list[dict]) -> Path:
    lines = [
        "# Phase 1 brief evaluation: Gate 1 recommendations",
        "",
        f"Run at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC with `{settings.provider}` "
        f"(`{settings.model_name('smart')}` / `{settings.model_name('fast')}`), real web search. "
        "Produced by `python evals/briefs/run_briefs.py`; briefs in `evals/briefs/briefs.json`. "
        "Each run stops at Gate 1 with no founder decision made.",
        "",
        f"**{sum(r['ok'] for r in rows)} of {len(rows)} as expected.**",
        "",
        "| Brief | Set | Expected | Got | Score | As expected | Seconds | Tokens |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        score = f"{r['score']:.2f}" if isinstance(r["score"], (int, float)) else "n/a"
        lines.append(f"| {r['id']}: {r['idea']} | {r['set']}{' (' + r['kind'] + ')' if r['kind'] else ''} | "
                     f"{r['expect']} | {r['got']} | {score} | {'yes' if r['ok'] else '**no**'} | {r['seconds']} | {r['tokens']} |")
    lines += ["", "## Gate 1 reasons", ""]
    for r in rows:
        lines.append(f"**{r['id']}** ({r['got']}):")
        lines += [f"- {reason}" for reason in r["reasons"]] or ["- none given"]
        lines.append("")
    path = HERE / "results.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(args: list[str]) -> int:
    briefs = json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    rows = []
    for item in select(briefs, args):
        row = run_one(item)
        rows.append(row)
        print(f"{row['id']}: expected {row['expect']}, got {row['got']} "
              f"({'ok' if row['ok'] else 'NOT AS EXPECTED'}), {row['seconds']}s, {row['tokens']} tokens", flush=True)
    print(f"results: {write_results(rows)}  (run files in {TMP})")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
