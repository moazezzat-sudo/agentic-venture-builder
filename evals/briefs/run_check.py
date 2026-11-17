"""Real-model check of Phase 1 on one brief: discovery, search plan, claims, cited scores, Gate 1.

    python evals/briefs/run_check.py F1

Uses the model in .env or the environment (for example LLM_PROVIDER=ollama, OLLAMA_BASE_URL=...,
OLLAMA_MODEL=qwen3:4b). The script answers no discovery questions and confirms the summary as it
stands, then stops at Gate 1 without deciding. Files go to a temporary folder. Saves check.json and
rebuilds RESULTS.md.
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
TMP = Path(tempfile.mkdtemp(prefix="check_"))
os.environ["OUTPUTS_DIR"] = str(TMP / "outputs")
os.environ["DECISION_LOG_PATH"] = str(TMP / "decision_log.json")
os.environ["CHECKPOINT_DB"] = str(TMP / "checkpoints.sqlite")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import orchestrator  # noqa: E402
from config import settings  # noqa: E402
from results_md import render  # noqa: E402


def main(brief_id: str) -> int:
    briefs = {b["id"]: b for b in json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]}
    run_id = f"check-{brief_id}-{int(time.time())}"
    start = time.time()
    result = orchestrator.start_run(dict(briefs[brief_id]["brief"]), run_id)
    discovery_rounds = []
    while result.get("awaiting_founder") and result.get("stage") in ("discovery", "discovery_confirm"):
        if result["stage"] == "discovery":
            discovery_rounds.append({"round": result["round"], "summary": result["summary"]["text"],
                                     "questions": [q["text"] for q in result["questions"]]})
            result = orchestrator.resume_run(run_id, {"answers": {}})
        else:
            result = orchestrator.resume_run(run_id, {"answers": {"confirm": "Yes, that's my idea"}})
    seconds = round(time.time() - start, 1)
    state = orchestrator.get_state(run_id) or {}
    claims = state.get("claims") or []
    report = {
        "ran_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "brief": brief_id, "provider": settings.provider,
        "models": [settings.model_name("smart"), settings.model_name("fast")],
        "seconds": seconds, "tokens": orchestrator.run_tokens(run_id),
        "discovery": discovery_rounds,
        "keywords": (state.get("brief") or {}).get("keywords", {}),
        "search_plan": state.get("search_plan") or [],
        "claims": [{"id": c.get("id"), "kind": c.get("kind"), "tier": c.get("tier"), "text": c.get("text"),
                    "url": c.get("url")} for c in claims],
        "scores": state.get("scores") or {}, "score_claims": state.get("score_claims") or {},
        "score_notes": state.get("score_notes") or {}, "scoring_incomplete": state.get("scoring_incomplete") or [],
        "gate": {k: result.get(k) for k in ("gate", "recommendation", "score", "reasons")},
        "run_folder": str(TMP),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    saved = {k: v for k, v in report.items() if k != "run_folder"}
    (HERE / "check.json").write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"results: {render()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "F1"))
