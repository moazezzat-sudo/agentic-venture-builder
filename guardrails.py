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

How the checks work:
  - check_category: keyword rules on the product description first. If no rule
    fires, the fast model classifies the idea (logged to decision_log.json). A
    banned verdict from either one stops the run. If the model can't be reached,
    the rules result stands and the reason says the model check did not run.
  - check_text: rules only (no model), so it is fast, free and repeatable. A match
    that is negated in the same sentence ("we never post fake reviews") is not a
    violation. Secrets (passwords, card numbers, keys) are flagged even when negated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from schemas import BANNED_CATEGORIES

STUBBED = False

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

_FLAGS = re.IGNORECASE

# --------------------------------------------------------------------------- categories

CATEGORY_REASONS: dict[str, str] = {
    "physical_goods": "Physical goods are out of scope: this system only builds digital products.",
    "financial_investment_crypto": (
        "Financial, investment and crypto products are banned: the system can't build products "
        "that handle, invest or advise on money or digital assets."
    ),
    "health_advice": "Health advice products are banned: the system can't build products that diagnose, treat or advise on health.",
    "legal_advice": "Legal advice products are banned: the system can't build products that give legal advice.",
}

CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "physical_goods": (
        r"\bphysical (products?|goods|items?|copies|books?|stores?|shops?)\b",
        r"\bdrop[- ]?shipping\b",
        r"\bprint[- ]on[- ]demand\b",
        r"\b(t[- ]?shirts?|hoodies|mugs|merch(andise)?|apparel|clothing line)\b",
        r"\bhand[- ]?made\b",
        r"\b(candles|jewel(le)?ry|cosmetics|skincare products|soaps?|furniture|sneakers)\b",
        r"\bsubscription box(es)?\b",
        r"\b3d[- ]printed\b",
        r"\bsell(ing)? (clothes|shoes|food|coffee beans|snacks|baked goods|cakes|plants|hardware|gadgets)\b",
        r"\bship(ping)? (products|orders|boxes|parcels|goods)\b",
        r"\b(bakery|food truck|restaurant|caf[eé])\b",
    ),
    "financial_investment_crypto": (
        r"\bcrypto(currency|currencies)?\b",
        r"\b(bitcoin|ethereum|blockchain|defi|web3|nfts?|stablecoins?)\b",
        r"\btoken (sale|launch|offering)\b",
        r"\b(stock|share|options?) (picks|tips|signals|trading)\b",
        r"\btrading (bot|signals?|platform|algorithm|course)\b",
        r"\b(forex|fx trading|day[- ]trading)\b",
        r"\binvest(ment|ing)? (advice|advisor|adviser|platform|app|fund|portfolio|tips|club)\b",
        r"\brobo[- ]?advis[oe]r\b",
        r"\b(loans?|lending|micro[- ]?finance|credit line|bnpl|buy now,? pay later)\b",
        r"\binsurance (product|policy|policies|app|platform)\b",
        r"\b(payment processor|money transfer|remittance|e[- ]?wallet|digital wallet|neobank)\b",
        r"\bfinancial advice\b",
    ),
    "health_advice": (
        r"\bmedical (advice|diagnos\w*|second opinion)\b",
        r"\bdiagnos(e|es|is|ing|tic)\b.{0,40}\b(patients?|diseases?|illness|conditions?|symptoms?|skin|cancer|disorders?)\b",
        r"\bsymptom[- ]?checker\b",
        r"\b(prescri(be|ption)s?|dosage|medication advice)\b",
        r"\b(therapy|therapist|counsell?ing) (bot|chatbot|app|ai|sessions?)\b",
        r"\b(ai|virtual|online) (therapist|doctor|nurse|psychologist|psychiatrist)\b",
        r"\btreat(s|ing|ment (plans?|advice))?\b.{0,30}\b(depression|anxiety|diabetes|cancer|adhd|insomnia|disease|illness)\b",
        r"\b(diet|meal|nutrition) plans? for (diabetes|diabetics|cancer|weight loss|pcos|patients|kidney)\b",
        r"\b(supplements?|herbal remed(y|ies))\b",
        r"\bhealth advice\b",
    ),
    "legal_advice": (
        r"\blegal (advice|advisor|adviser|counsel|opinions?)\b",
        r"\b(answers?|gives?|provides?|offers?)\b.{0,30}\blegal (questions|help|guidance)\b",
        r"\b(ai|robot|virtual|online) (lawyer|attorney|solicitor|paralegal)\b",
        r"\blawyer (bot|chatbot|ai)\b",
        r"\b(draft|drafts|drafting|write|writes|generate|generates)\b.{0,20}\b(contracts?|wills?|leases?|ndas?|legal documents?)\b",
        r"\bcontract review\b",
        r"\b(visa|immigration|tax|divorce|custody|tenant) (advice|lawyer|law help)\b",
    ),
}

_CATEGORY_RE = {cat: [re.compile(p, _FLAGS) for p in pats] for cat, pats in CATEGORY_PATTERNS.items()}

# Fields of the brief that describe the product. Skills, budget and the rest are about the
# founder, not the product, so they never trigger a ban (a lawyer may build an HR tool).
_PRODUCT_FIELDS = ("idea", "product", "description", "product_description", "subdomain")

_MODEL_PROMPT = """You classify a startup idea for a safety check. Reply with JSON only, no other text.

Banned categories:
- physical_goods: the product is a physical item that is made, stocked or shipped.
- financial_investment_crypto: the product handles, lends, insures, invests or advises on money, securities or crypto/digital assets.
- health_advice: the product diagnoses, treats or advises people on medical, mental-health or nutrition matters.
- legal_advice: the product gives legal advice or drafts legal documents for people.

Software that serves a business in one of these fields without doing the banned thing itself (for example
scheduling software for clinics, or a CRM for law firms) is "allowed".

Idea: {idea}

Reply exactly: {{"category": "allowed" | "physical_goods" | "financial_investment_crypto" | "health_advice" | "legal_advice", "reason": "<one sentence>"}}"""


def _product_text(brief: Mapping[str, Any]) -> str:
    return "\n".join(str(brief.get(f, "")) for f in _PRODUCT_FIELDS if brief.get(f))


def _rule_category(text: str) -> Optional[tuple[str, str]]:
    """Return (category, matched text) for the first banned-category rule that fires, else None."""
    for category, regexes in _CATEGORY_RE.items():
        for rx in regexes:
            for m in rx.finditer(text):
                if not _negated(text, m.start()):
                    return category, m.group(0)
    return None


def _parse_json(content: Any) -> dict[str, Any]:
    if isinstance(content, list):  # some chat models return content blocks
        content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    text = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("model reply has no JSON object")
    return json.loads(match.group(0))


def _model_category(idea: str, llm: Any, log_path: Optional[Path]) -> tuple[str, str]:
    """Ask the fast model for a category. Returns (category, reason); logs the call."""
    from llm import usage_cost
    from logger import log_action

    reply = llm.invoke(_MODEL_PROMPT.format(idea=idea[:2000]))
    tokens, cost = usage_cost(reply)
    data = _parse_json(getattr(reply, "content", reply))
    category = str(data.get("category", "")).strip().lower()
    if category != ALLOWED and category not in BANNED_CATEGORIES:
        raise ValueError(f"model returned an unknown category: {category!r}")
    reason = str(data.get("reason", "")).strip()
    model_name = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    log_action(
        agent="guardrails",
        action="category_check_model",
        sources=[],
        model=str(model_name) if model_name else None,
        cost=cost,
        log_path=log_path,
        tokens=tokens,
        outcome=category,
    )
    return category, reason


def check_category(
    brief: Mapping[str, Any],
    *,
    use_model: bool = True,
    llm: Any = None,
    log_path: Optional[Path] = None,
) -> tuple[bool, str, str]:
    """Decide whether the founder's product idea is in an allowed category.

    Returns (allowed, category, reason). category is one of
    schemas.BANNED_CATEGORIES when the idea is banned, otherwise "allowed".

    use_model=False runs the keyword rules only (tests, evals, offline use).
    llm lets callers pass a model; by default it is get_llm(role="fast").
    """
    if not isinstance(brief, Mapping) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a mapping with a non-empty 'idea'")
    text = _product_text(brief)

    hit = _rule_category(text)
    if hit:
        category, matched = hit
        return False, category, f"{CATEGORY_REASONS[category]} (Rule matched: \"{matched}\".)"

    if not use_model:
        return True, ALLOWED, "No banned-category rule matched (keyword rules only; model check not run)."

    try:
        if llm is None:
            from llm import get_llm

            llm = get_llm(role="fast")
        category, model_reason = _model_category(text, llm, log_path)
    except Exception as exc:  # model down or bad reply: the rules result stands, and we say so
        return True, ALLOWED, (
            "No banned-category rule matched. The model check could not run "
            f"({type(exc).__name__}), so this rests on keyword rules only."
        )

    if category in BANNED_CATEGORIES:
        detail = f" Model's reason: {model_reason}" if model_reason else ""
        return False, category, f"{CATEGORY_REASONS[category]}{detail}"
    return True, ALLOWED, "No banned-category rule matched, and the model check found an allowed digital product."


# --------------------------------------------------------------------------- text checks

TEXT_REASONS: dict[str, str] = {
    "fake_social_proof": "Fake reviews, testimonials, ratings or sign-up counts are not allowed. Use only real ones, with their source.",
    "fake_urgency": "Fake urgency or countdown timers are not allowed. Don't invent scarcity or deadlines.",
    "impersonation": "The system can't pose as the founder, a customer or another brand. It drafts; the founder sends under their own name.",
    "income_promise": "Promising income, profit or success is not allowed. Present numbers as ASSUMPTIONs or sourced facts, never as expected results.",
    "money_handling": "The system can't hold, move, charge or refund money. Payments are MOCKED; the founder acts through their own provider.",
    "account_creation": "The system can't create accounts. It can recommend a service; the founder creates any account themselves.",
    "credentials": "Passwords, card numbers and API keys must never appear in text or be stored by the system.",
}

TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "fake_social_proof": (
        r"\b(fake|made[- ]up|invented|fabricated|fictional|fictitious|bogus|false)\b.{0,30}\b(reviews?|testimonials?|ratings?|sign[- ]?ups?|followers|likes|endorsements?|customers?|users)\b",
        r"\b(write|generate|create|make|produce|post|add|invent)\b.{0,30}\b(reviews?|testimonials?|endorsements?)\b",
        r"\b(five|5)[- ]star (reviews?|ratings?)\b",
        r"★{4,}",
        r"\b(trusted by|loved by|join(ed)?( over| more than)?)\s+[\d,.]+\s*[km+]?\+?\s*(happy |satisfied )?(customers|users|founders|people|members|businesses|teams|subscribers)\b",
        r"\b(inflate|pad|boost)\b.{0,20}\b(sign[- ]?ups?|waitlist|numbers|counts?|followers)\b",
        r"\b(bots?|fake accounts?)\b.{0,20}\b(sign[- ]?ups?|reviews?|likes|followers)\b",
    ),
    "fake_urgency": (
        r"\bcount[- ]?down( timer| clock)?\b",
        r"\bonly \d+ (left|remaining|spots?|seats?|copies|licen[cs]es)\b",
        r"\b(offer|sale|deal|discount|price) (ends|expires) (today|tonight|soon|in \d+|at midnight)\b",
        r"\blimited[- ]time (offer|only|deal|discount)\b",
        r"\b(hurry|act now|last chance|don'?t miss out|before it'?s too late|selling out fast)\b",
        r"\b\d+ (people|others|users) (are )?(viewing|looking at|buying) (this|now)\b",
        r"\bprice (goes|will go) up (tomorrow|tonight|soon|in \d+)\b",
        r"\b(fake|false|artificial|invented)\b.{0,20}\b(urgency|scarcity|deadline)\b",
    ),
    "impersonation": (
        r"\b(pose|posing|poses|pretend(ing)?|impersonat\w*|masquerad\w*)\b.{0,30}\b(as|to be)\b",
        r"\bpretend(ing)? (you are|you're|to be)\b",
        r"\b(email|e-mail|message|dm|text|reply|post|write|sign|call|contact|tweet)\w*\b.{0,60}\bas (me|the founder|if (you were|you are) (me|the founder))\b",
        r"\b(write|post|leave|reply)\w*\b.{0,30}\bas (an? )?(happy |satisfied |real |verified )?(customer|user|client|buyer)\b",
        r"\b(in my name|under my name|sign(ed)? (it )?with my name)\b",
        r"\b(official|authori[sz]ed) (partner|reseller|account|page)\b.{0,30}\b(of|for|from)\b",
        r"\b(use|copy|borrow)\b.{0,20}\b(their|competitor'?s?|another (brand|company)'?s?|apple'?s?|google'?s?|amazon'?s?|microsoft'?s?)\b.{0,10}\b(logo|brand( name)?|trademark|branding)\b",
    ),
    "income_promise": (
        r"\bguarantee(d|s)?\b.{0,30}\b(income|profits?|returns?|results|success|sales|revenue|customers|earnings|money)\b",
        r"\b(you|you'll|you will|founders?) (will|can|could)?\s*(make|earn|generate)\b.{0,20}\$\s?\d",
        r"\b(make|earn)\s+\$\s?\d[\d,.]*\s*[km]?\s*(per|a|an|/|every)\s*(day|week|month|year|hour)\b",
        r"\bpassive income\b",
        r"\bget rich\b",
        r"\b(risk[- ]free|sure[- ]fire|surefire) (income|profits?|returns?|money|business|success)\b",
        r"\b100\s?% (success|guaranteed|profit)\b",
        r"\b(financial freedom|replace your (salary|income)|quit your (day )?job)\b",
        r"\bwill (generate|earn|make|bring in|reach)\b.{0,30}(\$\s?\d|\d[\d,.]*\s*(k|m)?\s*(in )?(revenue|mrr|arr|profit))",
        r"\b(guaranteed|certain|assured) to (succeed|work|sell|make money)\b",
    ),
    "money_handling": (
        r"\b(transfer|wire|withdraw|move|send|hold|escrow|disburse|pay out)\w*\b.{0,30}\b(money|funds|cash|balance|deposits?|payouts?|\$\s?\d[\d,.]*)\b",
        r"\b(refund|charge|bill|debit)\w*\b.{0,30}\b(the customer|customers|their card|my card|the card|users?|buyers?|\$\s?\d[\d,.]*)\b",
        r"\b(log ?in|sign ?in|access)\b.{0,20}\b(my|the|our|their)\b.{0,10}\b(bank|paypal|stripe|wise|payoneer|brokerage) account\b",
        r"\b(hold|keep|manage|store)\b.{0,20}\b(customer|client|user)s?'? (money|funds|payments)\b",
    ),
    "account_creation": (
        r"\b(create|open|register|set up|make)\b.{0,20}\b(an? |new |my |the )?(\w+ )?accounts?\b.{0,20}\b(for me|on my behalf|for the founder|in my name|for (each|every|all|our) (users?|customers?))\b",
        r"\b(sign|register) (me|us|the founder) up\b",
        r"\b(create|make|open|register)\b.{0,10}\b(fake|multiple|bulk|many|\d+|dozens of|hundreds of) (\w+ )?accounts\b",
        r"\b(create|open|register|set up|sign up for)\b.{0,15}\b(a |an |my |the )?(stripe|paypal|bank|gmail|google|twitter|x|facebook|instagram|linkedin|tiktok|shopify|gumroad|firebase|aws|github|apple developer) account\b",
    ),
    "credentials": (
        r"\b(password|passcode|passwd|pwd)\s*(is|:|=)\s*\S+",
        r"\b(store|save|keep|remember|log|record)\b.{0,30}\b(passwords?|card numbers?|credit cards?|card details|cvv|cvc|pins?)\b",
        r"\b(cvv|cvc|security code)\s*(is|:|=)?\s*\d{3,4}\b",
        r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{8,}\b",
        r"\bgsk_[A-Za-z0-9]{20,}\b",
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b(api[_ -]?key|secret|token)\s*(is|:|=)\s*['\"]?[A-Za-z0-9_\-]{16,}",
    ),
}

_TEXT_RE = {rule: [re.compile(p, _FLAGS) for p in pats] for rule, pats in TEXT_PATTERNS.items()}

# Rules where "never", "no", "not" ... earlier in the same sentence cancels the match.
# Credentials are not negatable: a secret in the text is a leak whatever surrounds it.
_NEGATABLE = set(TEXT_RULES) - {"credentials"}

_NEGATION_RE = re.compile(
    r"\b(no|not|never|without|avoid|avoids|refuse|refuses|cannot|can't|won't|don't|doesn't|"
    r"isn't|aren't|mustn't|shouldn't|nor|instead of|rather than|prohibited|banned|forbidden)\b",
    _FLAGS,
)
_CARD_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")


def _negated(text: str, start: int) -> bool:
    """True when a negation word appears earlier in the same sentence, within 60 characters."""
    window = text[max(0, start - 60) : start]
    window = re.split(r"[.!?\n;:]", window)[-1]
    return bool(_NEGATION_RE.search(window))


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 80 else text[:77] + "..."


def _redact(text: str) -> str:
    """Hide the secret part of a credentials match so the violation never repeats it."""
    text = re.sub(r"((?:\bis|:|=)\s*['\"]?)\S+", r"\1[REDACTED]", text, flags=_FLAGS)
    text = re.sub(r"\b(sk|pk|rk|gsk|AKIA)[\w-]{6,}", "[REDACTED]", text)
    return re.sub(r"\d{3,}", "[REDACTED]", text)


def check_text(text: str) -> list[Violation]:
    """Return every guardrail violation found in text (an empty list means clean).

    Use it on any request to the system and on every draft before it is shown,
    published or sent. Each violation is {"rule", "reason", "excerpt"}.
    """
    if not isinstance(text, str):
        raise TypeError("check_text needs a string")
    found: list[Violation] = []
    seen: set[tuple[str, str]] = set()

    def add(rule: str, excerpt: str) -> None:
        key = (rule, excerpt.lower())
        if key not in seen:
            seen.add(key)
            found.append({"rule": rule, "reason": TEXT_REASONS[rule], "excerpt": excerpt})

    for rule, regexes in _TEXT_RE.items():
        for rx in regexes:
            for m in rx.finditer(text):
                if rule in _NEGATABLE and _negated(text, m.start()):
                    continue
                matched = _redact(m.group(0)) if rule == "credentials" else m.group(0)
                add(rule, _excerpt(matched))

    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            add("credentials", "card number ending " + digits[-4:])  # never echo the full number

    return found


__all__ = [
    "check_category",
    "check_text",
    "TEXT_RULES",
    "ALLOWED",
    "BANNED_CATEGORIES",
    "CATEGORY_REASONS",
    "TEXT_REASONS",
    "STUBBED",
]
