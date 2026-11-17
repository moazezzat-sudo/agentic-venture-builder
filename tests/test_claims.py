"""Every claim is supported: a URL, our own evidence, or the label ASSUMPTION (PLAN.md section 10).

Checks the Claim model, the claim lines the real pipeline writes to outputs/ (offline run
with the fake model and search from tests/test_orchestrator.py), and the committed outputs/.
"""

import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_DIR))

import orchestrator  # noqa: E402
from agents._common import claims_markdown  # noqa: E402
from gates import claim_stats  # noqa: E402
from schemas import Claim  # noqa: E402
from test_orchestrator import FULL_BRIEF, run  # noqa: E402,F401  (run is a pytest fixture)

# A claim line as agents._common.claims_markdown writes it: "N. text (area; support)".
CLAIM_LINE = re.compile(r"^\d+\. .+\((?P<area>[^;()]+); (?P<support>.+)\)$")


def _support_ok(support: str) -> bool:
    if support == "ASSUMPTION":
        return True
    if support.startswith("our evidence: ") and support[len("our evidence: "):].strip() not in ("", "None"):
        return True
    return support.startswith("tier ") and bool(re.search(r"\]\(https?://[^)\s]+\)", support))


def _claim_sections(text: str) -> list[str]:
    """Lines under every '## Claims' heading, up to the next heading."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            inside = line.strip().lower() == "## claims"
            continue
        if inside and line.strip() and line.strip() != "_No claims._":
            lines.append(line.strip())
    return lines


def _unsupported_lines(folder: Path) -> list[str]:
    bad = []
    for path in sorted(folder.glob("*.md")):
        for line in _claim_sections(path.read_text(encoding="utf-8")):
            m = CLAIM_LINE.match(line)
            if not m or not _support_ok(m["support"]):
                bad.append(f"{path.name}: {line}")
    return bad


# --------------------------------------------------------------------------- the model


def test_a_claim_needs_support():
    with pytest.raises(ValueError):
        Claim(text="The market is huge", support="url")
    with pytest.raises(ValueError):
        Claim(text="The market is huge", support="url", url="ftp://example.org")
    with pytest.raises(ValueError):
        Claim(text="Our test passed", support="evidence")
    with pytest.raises(ValueError):
        Claim(text="Unlabelled", support="guess")  # type: ignore[arg-type]
    assert Claim(text="An assumption", support="ASSUMPTION", tier="A").weight == 0.0


def test_assumptions_count_as_unsourced():
    claims = [
        Claim(text="a", support="url", url="https://data.worldbank.org/x", tier="A"),
        Claim(text="b", support="evidence", evidence_ref="evals/guardrail_results.md"),
        Claim(text="c", support="ASSUMPTION"),
        Claim(text="d", support="ASSUMPTION"),
    ]
    stats = claim_stats(claims)
    assert stats["sourced"] == 2 and stats["unsourced"] == 2 and stats["sourced_share"] == 0.5
    assert claim_stats([])["unsourced_share"] == 1.0  # no claims is no evidence


def test_claim_lines_always_carry_their_support():
    lines = claims_markdown([
        Claim(text="Pain", support="url", url="https://www.reddit.com/r/x", tier="D").model_dump(),
        Claim(text="Tested", support="evidence", evidence_ref="tests/test_gates.py").model_dump(),
        Claim(text="Guess", support="ASSUMPTION").model_dump(),
    ]).splitlines()
    assert len(lines) == 3
    for line in lines:
        m = CLAIM_LINE.match(line)
        assert m and _support_ok(m["support"]), line


@pytest.mark.parametrize("line", [
    "0. Big market (market; tier A, read 2026-11-17)",  # tier but no URL
    "1. Big market (market; our evidence: None)",
    "2. Big market (market)",
])
def test_unsupported_lines_are_detected(line):
    m = CLAIM_LINE.match(line)
    assert not m or not _support_ok(m["support"])


# --------------------------------------------------------------------------- real pipeline outputs


def test_every_claim_the_pipeline_writes_is_supported(run):
    orchestrator.start_run(dict(FULL_BRIEF), "claims-1")
    claim_lines = [l for p in run["out"].glob("*.md") for l in _claim_sections(p.read_text(encoding="utf-8"))]
    assert claim_lines, "the run wrote no claims"
    assert _unsupported_lines(run["out"]) == []
    # The fake model cited a source number that doesn't exist; it must have become an ASSUMPTION.
    assert any("Made-up statistic" in l and l.endswith("ASSUMPTION)") for l in claim_lines)

    state = orchestrator.get_graph().get_state({"configurable": {"thread_id": "claims-1"}}).values
    for c in state["claims"]:
        Claim(**c)  # raises if any claim in the Briefcase lacks support


def test_committed_outputs_have_no_unsupported_claims():
    assert _unsupported_lines(ROOT / "outputs") == []
