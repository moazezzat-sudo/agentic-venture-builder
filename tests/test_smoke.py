"""Smoke tests: repository conventions and the shared foundation.

Gate, approval and guardrail tests are added with those modules.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from logger import REQUIRED_KEYS, log_action, write_gate, write_output  # noqa: E402
from schemas import Claim  # noqa: E402

REQUIRED_README_HEADINGS = [
    "## Quickstart",
    "## What works and what is mocked",
    "## Architecture",
    "## Models and free resources",
    "## Cost per run",
    "## Demo video",
    "## What our system will NOT do",
    "## How the project stays alive after the hackathon",
]

REQUIRED_ARCHITECTURE_HEADINGS = [
    "## Overview",
    "## Phases",
    "## Gates",
    "## Sale to cash",
    "## Data flow",
    "## Built vs. stubbed",
    "## Roadmap",
]


def _headings(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]


def test_required_files_exist():
    for rel in ["README.md", "LICENSE", "docker-compose.yml", "ARCHITECTURE.md", ".env.example", "tests", "outputs"]:
        assert (ROOT_DIR / rel).exists(), f"missing {rel}"


def test_readme_headings_in_order():
    assert _headings(ROOT_DIR / "README.md") == REQUIRED_README_HEADINGS
    text = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
    assert "```bash\ndocker compose up\n```" in text
    assert "$" in text.split("## Cost per run", 1)[1].split("## ", 1)[0]


def test_architecture_headings_in_order():
    assert _headings(ROOT_DIR / "ARCHITECTURE.md") == REQUIRED_ARCHITECTURE_HEADINGS
    assert "```mermaid" in (ROOT_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_no_payment_keys_in_env_example():
    text = (ROOT_DIR / ".env.example").read_text(encoding="utf-8").lower()
    assert "stripe" not in text and "sk_live" not in text and "sk_test" not in text


def test_log_action_has_required_keys(tmp_path):
    log = tmp_path / "decision_log.json"
    log_action(agent="researcher", action="search", sources=["https://example.org"], model="qwen3:8b", log_path=log)
    log_action(agent="gate", action="gate_1", approved_by="founder", log_path=log, outcome="stop")
    entries = json.loads(log.read_text())
    assert len(entries) == 2
    for entry in entries:
        for key in REQUIRED_KEYS:
            assert key in entry
        assert isinstance(entry["sources"], list)
        assert isinstance(entry["cost"], (int, float))
    assert entries[1]["approved_by"] == "founder" and entries[1]["outcome"] == "stop"


def test_log_action_rejects_other_approvers(tmp_path):
    with pytest.raises(ValueError):
        log_action(agent="x", action="y", approved_by="agent", log_path=tmp_path / "log.json")


def test_output_names_and_mock_labels(tmp_path):
    p1 = write_output(1, 2, "Domains & weights", "body", outputs_dir=tmp_path)
    p2 = write_gate(1, "decision", "stop", outputs_dir=tmp_path)
    p3 = write_output(5, 1, "payment test", "body", status="MOCKED", outputs_dir=tmp_path)
    assert p1.name == "phase1_step2_domains_weights.md"
    assert p2.name == "phase1_gate_decision.md"
    assert p3.read_text().startswith("> **MOCKED**")
    with pytest.raises(ValueError):
        write_output(1, 1, "x", "y", ext="pdf", outputs_dir=tmp_path)


def test_claims_need_support():
    assert Claim(text="t", support="url", url="https://data.worldbank.org", tier="A").weight == 1.0
    assert Claim(text="t", support="ASSUMPTION", tier="A").tier == "NONE"
    with pytest.raises(ValueError):
        Claim(text="t", support="url")
    with pytest.raises(ValueError):
        Claim(text="t", support="evidence")


def test_provider_auto_falls_back_to_local():
    from config import Settings

    assert Settings(llm_provider="auto", groq_api_key="").provider == "ollama"
    with_key = Settings(llm_provider="auto", groq_api_key="placeholder")
    assert with_key.provider == "groq"
    assert with_key.model_name("fast") != "" and with_key.model_name("smart") != ""
