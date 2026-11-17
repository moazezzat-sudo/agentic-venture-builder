"""Build evals/briefs/RESULTS.md from the saved run data (brief_runs.json, full_path.json).

Both run scripts call render() after a run, so every number in RESULTS.md comes from a real run.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIEF_RUNS = HERE / "brief_runs.json"
FULL_PATH = HERE / "full_path.json"
RESULTS = HERE / "RESULTS.md"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _briefs_section(data: dict) -> list[str]:
    rows = data["rows"]
    by_id: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r)
    lines = [
        "## Gate 1 on the evaluation briefs",
        "",
        f"Run at {data['ran_at']} with `{data['provider']}` (`{data['models'][0]}` / `{data['models'][1]}`), real web "
        f"search, up to {data['repeat']} run(s) per brief. Produced by `python evals/briefs/run_briefs.py`; briefs in "
        "`evals/briefs/briefs.json`. Each run stops at Gate 1 with no founder decision made.",
        "",
        f"**{sum(all(r['ok'] for r in rs) for rs in by_id.values())} of {len(by_id)} briefs as expected on every run.**",
        "",
        "| Brief | Set | Expected | Got (each run) | Same each run | As expected | Score | Seconds | Tokens | Research ran |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for bid, rs in by_id.items():
        r0 = rs[0]
        got = ", ".join(r["got"] for r in rs)
        same = "yes" if len({r["got"] for r in rs}) == 1 else "**no**"
        ok = "yes" if all(r["ok"] for r in rs) else "**no**"
        score = ", ".join(f"{r['score']:.2f}" if isinstance(r["score"], (int, float)) else "n/a" for r in rs)
        secs = ", ".join(str(r["seconds"]) for r in rs)
        toks = ", ".join(str(r["tokens"]) for r in rs)
        research = ", ".join("yes" if r.get("researched") else "no" for r in rs)
        kind = f" ({r0['kind']})" if r0.get("kind") else ""
        lines.append(f"| {bid}: {r0['idea']} | {r0['set']}{kind} | {r0['expect']} | {got} | {same} | {ok} | {score} | "
                     f"{secs} | {toks} | {research} |")
    lines += ["", "### Gate 1 reasons (last run of each brief)", ""]
    for bid, rs in by_id.items():
        r = rs[-1]
        lines.append(f"**{bid}** ({r['got']}):")
        lines += [f"- {reason}" for reason in r["reasons"]] or ["- none given"]
        lines.append("")
    return lines


def _full_path_section(data: dict) -> list[str]:
    lines = [
        "## One brief through every phase",
        "",
        f"Run at {data['ran_at']} with `{data['provider']}` (`{data['models'][0]}` / `{data['models'][1]}`): brief "
        f"{data['brief']}, Gate 1 -> niche gate -> Phases 2-6 -> finish. Produced by "
        "`python evals/briefs/run_full_path.py`. This is a pipeline test, so the script plays the founder: it approves "
        "where the gate recommends go and otherwise overrides to go (logged as a founder override), so every phase is "
        "reached. At Gate 2 it sets a waitlist target and enters no real count (none is invented), so Gate 2 "
        "recommends repeat.",
        "",
        f"Ended in Phase {data['ended']['phase']}, stopped: {data['ended']['stopped']}. "
        f"**Total: {data['total']['seconds']} s of machine time, {data['total']['tokens']:,} tokens.**",
        "",
        "| Phase | Seconds | Tokens |",
        "|---|---|---|",
    ]
    for phase, v in data["per_phase"].items():
        lines.append(f"| {phase} | {v['seconds']} | {v['tokens']:,} |")
    lines += ["", "| Gate | Recommended | Chosen | Override |", "|---|---|---|---|"]
    for g in data["gates"]:
        lines.append(f"| {g['gate']} | {g['recommended']} | {g['chose']} | {'yes' if g['override'] else 'no'} |")
    lines.append("")
    return lines


def render() -> Path:
    lines = ["# Evaluation results", "",
             "Every number below comes from a real run of the pipeline (saved in `brief_runs.json` and "
             "`full_path.json` next to this file). Nothing is written by hand.", ""]
    briefs, full = _load(BRIEF_RUNS), _load(FULL_PATH)
    if briefs:
        lines += _briefs_section(briefs)
    if full:
        lines += _full_path_section(full)
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    return RESULTS


if __name__ == "__main__":
    print(render())
