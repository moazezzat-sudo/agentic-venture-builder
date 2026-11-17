"""Smoke tests for the guardrails interface (PLAN.md section 11)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import guardrails  # noqa: E402
from schemas import BANNED_CATEGORIES  # noqa: E402


def test_check_category_returns_triple():
    allowed, category, reason = guardrails.check_category({"idea": "A scheduling app for tutors"})
    assert isinstance(allowed, bool)
    assert category == guardrails.ALLOWED or category in BANNED_CATEGORIES
    assert isinstance(reason, str) and reason


def test_check_category_needs_an_idea():
    with pytest.raises(ValueError):
        guardrails.check_category({"idea": "  "})
    with pytest.raises(ValueError):
        guardrails.check_category("not a dict")  # type: ignore[arg-type]


def test_check_text_returns_list_of_violations():
    violations = guardrails.check_text("A short, honest product description.")
    assert isinstance(violations, list)
    for v in violations:
        assert set(v) == {"rule", "reason", "excerpt"}
        assert v["rule"] in guardrails.TEXT_RULES


def test_check_text_rejects_non_strings():
    with pytest.raises(TypeError):
        guardrails.check_text(None)  # type: ignore[arg-type]
