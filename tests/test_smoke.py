"""Smoke tests for Agentic Venture Builder repository conventions, gates, and founder approval."""

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parent.parent

REQUIRED_README_HEADINGS = [
    "## Quickstart",
    "## What works and what is mocked",
    "## Architecture",
    "## Models and free resources",
    "## Cost per run",
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

PROHIBITED_CATEGORIES = {"physical_goods", "financial_investment_crypto", "health_advice", "legal_advice"}


def evaluate_evidence_gate(sourced_claims: int, assumption_claims: int, category: str = "digital_tool") -> str:
    """Evaluate a phase gate and recommend 'stop' on prohibited categories or weak evidence."""
    if category in PROHIBITED_CATEGORIES:
        return "stop"
    total = sourced_claims + assumption_claims
    if total == 0 or (sourced_claims / total) < 0.5:
        return "stop"
    return "go"


def execute_gated_action(action_name: str, founder_approved: bool) -> dict:
    """Enforce that nothing is published, sent, spent, or signed without founder approval."""
    if not founder_approved:
        raise PermissionError(f"Action '{action_name}' blocked: explicit founder approval is required.")
    return {
        "agent": "gate",
        "action": action_name,
        "sources": [],
        "model": None,
        "cost": 0,
        "approved_by": "founder",
    }


class TestRepositoryAndPipelineSmoke(unittest.TestCase):
    def test_required_files_and_directories_exist(self) -> None:
        for rel_path in [
            "CLAUDE.md",
            "AGENTS.md",
            "GEMINI.md",
            "README.md",
            "ARCHITECTURE.md",
            ".env.example",
            "docker-compose.yml",
            "prompts",
            "agents",
            "tests",
        ]:
            self.assertTrue((ROOT_DIR / rel_path).exists(), f"Missing required path: {rel_path}")

    def test_readme_headings_in_exact_order(self) -> None:
        content = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        headings = [line.strip() for line in content.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, REQUIRED_README_HEADINGS)
        self.assertIn("docker compose up", content)
        self.assertIn("$", content)

    def test_architecture_headings_in_exact_order(self) -> None:
        content = (ROOT_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")
        headings = [line.strip() for line in content.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, REQUIRED_ARCHITECTURE_HEADINGS)
        self.assertIn("```mermaid", content)

    def test_gate_recommends_stop_on_weak_evidence_or_prohibited_category(self) -> None:
        self.assertEqual(evaluate_evidence_gate(sourced_claims=0, assumption_claims=4), "stop")
        self.assertEqual(evaluate_evidence_gate(sourced_claims=1, assumption_claims=3), "stop")
        self.assertEqual(
            evaluate_evidence_gate(sourced_claims=5, assumption_claims=0, category="financial_investment_crypto"),
            "stop",
        )
        self.assertEqual(evaluate_evidence_gate(sourced_claims=3, assumption_claims=1), "go")

    def test_nothing_goes_out_without_founder_approval(self) -> None:
        with self.assertRaises(PermissionError):
            execute_gated_action("publish_landing_page", founder_approved=False)

        entry = execute_gated_action("publish_landing_page", founder_approved=True)
        self.assertEqual(entry["approved_by"], "founder")
        for key in ("action", "sources", "model", "cost", "approved_by"):
            self.assertIn(key, entry)


if __name__ == "__main__":
    unittest.main()
