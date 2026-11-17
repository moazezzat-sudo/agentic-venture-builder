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
    assert "**FAIL**" not in text and "No trick prompt missed" in text
    assert "on prompts we wrote ourselves" in text and "keyword rules only" in text
    assert "False-positive rate on legitimate briefs" in text


def test_legit_briefs_and_heldout_files_are_well_formed():
    legit = json.loads(run_guardrails.LEGIT_PATH.read_text(encoding="utf-8"))["briefs"]
    assert len(legit) >= 10 and all(b["brief"]["idea"] for b in legit)
    heldout = json.loads(run_guardrails.HELDOUT_PATH.read_text(encoding="utf-8"))["prompts"]
    for p in heldout:
        assert p.get("source") and (p["expect"].get("rule") or p["expect"].get("category"))


def test_legit_brief_without_ambiguous_words_is_allowed_by_rules():
    r = run_guardrails.evaluate_brief({"id": "x", "brief": {"idea": "A CV builder for graduates"}}, use_model=False)
    assert r["passed"] and r["model_check"] == "off (--rules-only)"
