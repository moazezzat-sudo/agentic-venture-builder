"""The trick-prompt eval (evals/run_guardrails.py) runs and every prompt gets the expected result."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

import run_guardrails  # noqa: E402


def test_trick_prompts_file_is_well_formed():
    items = json.loads(run_guardrails.PROMPTS_PATH.read_text(encoding="utf-8"))["prompts"]
    tricks = [i for i in items if not i.get("control")]
    assert len(tricks) >= 15 and any(i.get("control") for i in items)
    assert len({i["id"] for i in items}) == len(items)
    for i in tricks:
        assert i["expect"].get("rule") or i["expect"].get("category")


def test_every_trick_prompt_is_caught_by_rules(tmp_path):
    out = tmp_path / "results.md"
    assert run_guardrails.main(["--rules-only", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "**FAIL**" not in text and "None in this run." in text
