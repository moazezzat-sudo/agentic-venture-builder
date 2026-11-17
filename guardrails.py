"""Guardrails: banned product categories and forbidden text, checked before anything moves on.

Public interface (PLAN.md section 11, "Shared interfaces"):

    from guardrails import check_category, check_text

    allowed, category, reason = check_category(brief)
        allowed  -> False when the product is in a banned category (the run must stop)
        category -> one of schemas.BANNED_CATEGORIES when banned, otherwise "allowed"
        reason   -> a plain-language reason, shown to the founder and written to the gate file

    violations = check_text(text)
        A list of dicts, empty when the text is clean. Each violation is
        {"rule": <one of TEXT_RULES>, "reason": <why it is refused>, "excerpt": <matched text>}.

Rules come from CLAUDE.md and PLAN.md sections 2 and 5a:
  - Banned products: physical goods; financial, investment or crypto products;
    health advice; legal advice.
  - Never: fake reviews, testimonials or sign-ups; fake urgency or countdown timers;
    posing as the founder, a customer or another brand; promising income or success;
    holding, moving or refunding money; creating accounts; storing passwords or card numbers.

STUBBED: the checks are not implemented yet. check_category() allows every brief
and check_text() reports no violations. Callers must not treat a STUBBED result as
a real safety check; the STUBBED flag below says so.
"""

from __future__ import annotations

from typing import Any, Mapping

from schemas import BANNED_CATEGORIES

STUBBED = True  # set to False once the real checks replace the placeholder bodies

ALLOWED = "allowed"

TEXT_RULES = (
    "fake_social_proof",  # fake reviews, testimonials, ratings or sign-up counts
    "fake_urgency",  # countdown timers, invented scarcity, "only 2 left"
    "impersonation",  # posing as the founder, a customer or another brand
    "income_promise",  # promising income, profit or success
    "money_handling",  # the system holding, moving or refunding money itself
    "account_creation",  # the system creating accounts on someone's behalf
    "credentials",  # passwords, card numbers, API keys in the text
)

Violation = dict[str, str]


def check_category(brief: Mapping[str, Any]) -> tuple[bool, str, str]:
    """Decide whether the founder's product idea is in an allowed category.

    Returns (allowed, category, reason). category is one of
    schemas.BANNED_CATEGORIES when the idea is banned, otherwise "allowed".

    STUBBED: always returns (True, "allowed", "STUBBED: ...").
    """
    if not isinstance(brief, Mapping) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a mapping with a non-empty 'idea'")
    return True, ALLOWED, "STUBBED: category check not implemented yet; nothing was checked."


def check_text(text: str) -> list[Violation]:
    """Return every guardrail violation found in text (an empty list means clean).

    STUBBED: always returns [].
    """
    if not isinstance(text, str):
        raise TypeError("check_text needs a string")
    return []


__all__ = ["check_category", "check_text", "TEXT_RULES", "ALLOWED", "BANNED_CATEGORIES", "STUBBED"]
