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

How check_category works (every field of the brief, joined, is checked):
  1. A strong keyword ("dropshipping", "trading signals", "symptom checker") -> banned.
  2. Only ambiguous keywords ("crypto", "supplements", "handmade", "lending") -> the fast
     model confirms. Banned if the model agrees, or if the model can't be reached or was
     not asked (fail safe). Allowed only when the model judges it an allowed digital product.
  3. No keyword -> the fast model classifies the idea. If the model can't be reached, the
     idea is allowed on the keyword rules alone, and the reason says so.
  Every model call is logged to decision_log.json.

How check_text works: rules only (no model), in English, plus French and Arabic for fake
reviews, impersonation and income promises. A negation cancels a match only when it
governs the action itself ("we never post fake reviews"): it must sit in the same clause,
at most three words before the match. Idioms such as "don't hesitate", "never mind",
"no problem" and "no worries" never cancel. Secrets are flagged even when negated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple, Optional

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

# --------------------------------------------------------------------------- negation

# Negation words in English, French and Arabic.
_NEGATION_RE = re.compile(
    r"(?<!\w)(no|not|never|without|avoid|avoids|refuse|refuses|cannot|can't|won't|don't|do not|"
    r"doesn't|does not|isn't|aren't|mustn't|shouldn't|nor|instead of|rather than|prohibited|banned|forbidden|"
    r"ne|n'|pas|jamais|sans|aucune?|ni|"
    r"لا|لن|لم|ليس|بدون|أبدا|أبداً|ممنوع)(?!\w)",
    _FLAGS,
)
# Idioms that contain a negation word but negate nothing. They are removed before the check.
_IDIOM_RE = re.compile(
    r"(?<!\w)((don't|do not|never|no|not)\s+(hesitate|mind|problem|problems|worries|worry|forget|wait|stop|"
    r"matter|delay|excuse|doubt|care|need to ask)|not (a problem|only|just)|why not|doesn't matter|"
    r"n'h[ée]site(z)? pas|ne t'inqui[èe]te pas|ne vous inqui[ée]tez pas|pas de (probl[èe]me|souci)|peu importe|"
    r"لا مشكلة|لا تتردد|لا تترددي|لا تقلق|ولا يهمك|مش مشكلة)(?!\w)",
    _FLAGS,
)
# Words that start a new instruction: a negation before them does not reach the match.
_CLAUSE_WORDS = {"just", "but", "so", "then", "and", "instead", "anyway", "please", "still", "now",
                 "mais", "alors", "juste", "et", "بس", "لكن", "و"}
_MAX_GAP_WORDS = 3


def _negated(text: str, start: int) -> bool:
    """True when a negation governs the match starting at `start`.

    The negation must be in the same clause, at most three words before the match,
    with no clause word ("just", "but", "and" ...) in between. Idioms never count.
    """
    window = text[max(0, start - 80) : start]
    window = re.split(r"[.!?\n;:,،؛]", window)[-1]
    window = _IDIOM_RE.sub(" ", window)
    negations = list(_NEGATION_RE.finditer(window))
    if not negations:
        return False
    gap = window[negations[-1].end() :].split()
    if len(gap) > _MAX_GAP_WORDS:
        return False
    return not any(w.lower().strip("'\"") in _CLAUSE_WORDS for w in gap)


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

# "strong": the phrase names the banned product itself. "ambiguous": the word also appears in
# allowed ideas (software for a bakery, a book-lending tracker), so the model must confirm.
CATEGORY_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "physical_goods": {
        "strong": (
            r"\bphysical (products?|goods|items?|copies|books?)\b",
            r"\bdrop[- ]?shipping\b",
            r"\bprint[- ]on[- ]demand\b",
            r"\bsubscription box(es)?\b",
            # The founder sells goods ("we sell", "sells our ..."); "shops that sell handmade jewelry" is
            # only ambiguous, since software for those shops is allowed.
            r"\b((we|i|to) sell(ing)?|sell(s|ing)? (our|my)) (\w+ )?(handmade|hand-made|clothes|shoes|food|coffee beans|snacks|baked goods|cakes|plants|hardware|gadgets|furniture|jewel(le)?ry|candles|cosmetics|wallets|bags)\b",
            r"\bship(s|ping)? (products|orders|boxes|parcels|goods) to\b",
        ),
        "ambiguous": (
            r"\b(t[- ]?shirts?|hoodies|mugs|merch(andise)?|apparel|clothing line)\b",
            r"\bhand[- ]?made\b",
            r"\b(candles|jewel(le)?ry|cosmetics|skincare products|soaps?|furniture|sneakers)\b",
            r"\b3d[- ]printed\b",
            r"\b(bakery|food truck|restaurant|caf[eé])\b",
            r"\bphysical (stores?|shops?)\b",
        ),
    },
    "financial_investment_crypto": {
        "strong": (
            r"\btoken (sale|launch|offering)\b",
            r"\b(stock|share|options?) (picks|tips|signals|trading)\b",
            r"\btrading (bot|signals?|platform|algorithm|course)\b",
            r"\b(forex|fx trading|day[- ]trading)\b",
            r"\binvest(ment|ing)? (advice|advisor|adviser|platform|app|fund|portfolio|tips|club)\b",
            r"\brobo[- ]?advis[oe]r\b",
            r"\b(micro[- ]?loans?|micro[- ]?finance|payday loans?|credit line|bnpl|buy now,? pay later)\b",
            r"\binsurance (product|policy|policies|app|platform)\b",
            r"\b(payment processor|money transfer|remittance|e[- ]?wallet|digital wallet|neobank)\b",
            r"\bfinancial advice\b",
            r"\bbuy (fractions of )?(bitcoin|ethereum|crypto|shares|stocks)\b",
        ),
        "ambiguous": (
            r"\bcrypto(currency|currencies)?\b",
            r"\b(bitcoin|ethereum|blockchain|defi|web3|nfts?|stablecoins?)\b",
            r"\b(loans?|lending)\b",
        ),
    },
    "health_advice": {
        "strong": (
            r"\bmedical (advice|diagnos\w*|second opinion)\b",
            r"\bdiagnos(e|es|is|ing|tic)\b.{0,40}\b(patients?|diseases?|illness|conditions?|symptoms?|skin|cancer|disorders?)\b",
            r"\bsymptom[- ]?checker\b",
            r"\b(reads?|checks?|analy[sz]es?) (your |their )?symptoms\b",
            r"\b(prescri(be|bes|bing|ption)s?|dosage|medication advice)\b",
            r"\bwhich (medicine|medication|pill|drug)s? to take\b",
            r"\b(therapy|therapist|counsell?ing) (bot|chatbot|ai)\b",
            r"\b(ai|virtual|online|robot) (therapist|doctor|nurse|psychologist|psychiatrist)\b",
            r"\btreat(s|ing|ment (plans?|advice))?\b.{0,30}\b(depression|anxiety|diabetes|cancer|adhd|insomnia|disease|illness)\b",
            r"\b(diet|meal|nutrition) plans? for (diabetes|diabetics|cancer|pcos|patients|kidney)\b",
            r"\bhealth advice\b",
        ),
        "ambiguous": (
            r"\b(supplements?|herbal remed(y|ies)|vitamins?)\b",
            r"\btherapy (app|sessions?)\b",
            r"\bweight[- ]loss (plans?|programs?|coaching)\b",
        ),
    },
    "legal_advice": {
        "strong": (
            r"\blegal (advice|advisor|adviser|counsel|opinions?)\b",
            r"\b(answers?|gives?|provides?|offers?)\b.{0,30}\blegal (questions|help|guidance)\b",
            r"\b(ai|robot|virtual|online) (lawyer|attorney|solicitor|paralegal)\b",
            r"\blawyer (bot|chatbot|ai)\b",
            r"\bcontract review\b",
            r"\b(visa|immigration|tax|divorce|custody|tenant) (advice|lawyer|law help)\b",
        ),
        "ambiguous": (
            r"\b(draft|drafts|drafting|write|writes|generate|generates)\b.{0,20}\b(contracts?|wills?|leases?|ndas?|legal documents?)\b",
        ),
    },
}

_CATEGORY_RE = {
    cat: {kind: [re.compile(p, _FLAGS) for p in pats] for kind, pats in kinds.items()}
    for cat, kinds in CATEGORY_PATTERNS.items()
}

_MODEL_PROMPT = """You classify a startup idea for a safety check. Reply with JSON only, no other text.

Banned categories:
- physical_goods: the product is a physical item that is made, stocked or shipped.
- financial_investment_crypto: the product handles, lends, insures, invests or advises on money, securities or crypto/digital assets.
- health_advice: the product diagnoses, treats or advises people on medical, mental-health or nutrition matters.
- legal_advice: the product gives legal advice or drafts legal documents for people.

Software that serves a business in one of these fields without doing the banned thing itself (for example
scheduling software for clinics, a booking widget for restaurants, or a CRM for law firms) is "allowed".

Founder brief (all fields):
{brief}

Reply exactly: {{"category": "allowed" | "physical_goods" | "financial_investment_crypto" | "health_advice" | "legal_advice", "reason": "<one sentence>"}}"""


class CategoryHit(NamedTuple):
    category: str
    matched: str
    strong: bool


def _flatten(value: Any) -> Iterable[str]:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, Mapping):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _flatten(v)
    else:
        text = str(value).strip()
        if text:
            yield text


def brief_text(brief: Mapping[str, Any]) -> str:
    """Every field of the brief joined into one text (idea, target_market, values, skills ...)."""
    return "\n".join(_flatten(brief))


def _category_hits(text: str) -> list[CategoryHit]:
    hits = []
    for category, kinds in _CATEGORY_RE.items():
        for kind, regexes in kinds.items():
            for rx in regexes:
                for m in rx.finditer(text):
                    if not _negated(text, m.start()):
                        hits.append(CategoryHit(category, m.group(0), kind == "strong"))
    return hits


def _parse_json(content: Any) -> dict[str, Any]:
    if isinstance(content, list):  # some chat models return content blocks
        content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    text = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("model reply has no JSON object")
    return json.loads(match.group(0))


def _model_category(text: str, llm: Any, log_path: Optional[Path]) -> tuple[str, str]:
    """Ask the fast model for a category. Returns (category, reason); logs the call."""
    from llm import usage_cost
    from logger import log_action

    reply = llm.invoke(_MODEL_PROMPT.format(brief=text[:3000]))
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


def _ask_model(text: str, use_model: bool, llm: Any, log_path: Optional[Path]) -> tuple[Optional[str], str]:
    """(category, reason) from the model, or (None, why it did not run)."""
    if not use_model:
        return None, "the model check was not run (keyword rules only)"
    try:
        if llm is None:
            from llm import get_llm

            llm = get_llm(role="fast")
        return _model_category(text, llm, log_path)
    except Exception as exc:  # model down or bad reply
        return None, f"the model check could not run ({type(exc).__name__})"


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

    use_model=False runs the keyword rules only (tests, evals, offline use); an
    ambiguous keyword is then blocked to be safe.
    llm lets callers pass a model; by default it is get_llm(role="fast").
    """
    if not isinstance(brief, Mapping) or not str(brief.get("idea", "")).strip():
        raise ValueError("brief must be a mapping with a non-empty 'idea'")
    text = brief_text(brief)
    hits = _category_hits(text)

    strong = [h for h in hits if h.strong]
    if strong:
        h = strong[0]
        return False, h.category, f"{CATEGORY_REASONS[h.category]} (Rule matched: \"{h.matched}\".)"

    if hits:  # only ambiguous words: the model must confirm
        h = hits[0]
        category, model_reason = _ask_model(text, use_model, llm, log_path)
        if category is None:
            return False, h.category, (
                f"{CATEGORY_REASONS[h.category]} The word \"{h.matched}\" may mean this category, and "
                f"{model_reason}, so the idea is blocked to be safe. Rephrase the idea, or rerun with the model check."
            )
        if category in BANNED_CATEGORIES:
            return False, category, f"{CATEGORY_REASONS[category]} The model confirmed the ambiguous word \"{h.matched}\": {model_reason}"
        return True, ALLOWED, (
            f"The word \"{h.matched}\" can point to a banned category, but the model check judged this an "
            f"allowed digital product: {model_reason}"
        )

    category, model_reason = _ask_model(text, use_model, llm, log_path)
    if category is None:
        return True, ALLOWED, f"No banned-category rule matched; {model_reason}, so this rests on keyword rules only."
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
        r"\bmake up\b.{0,20}\b(names?|quotes?|reviews?|testimonials?|numbers|stats|statistics|figures|sign[- ]?ups?|customers?)\b",
        r"\b(add|write|generate|create|invent)\b.{0,30}\b(customer|user|client|buyer) (quotes?|praise|success stories)\b",
        # French
        r"\b(faux|fausses?|bidons?|invent[ée]e?s?)\s+(avis|t[ée]moignages?|commentaires?|notes?|inscriptions?|abonn[ée]s)\b",
        r"\b(avis|t[ée]moignages?|commentaires?)\s+(faux|fausses?|bidons?|invent[ée]e?s?)\b",
        r"\b([ée]cris|[ée]crire|r[ée]dige[rz]?|g[ée]n[èée]re[rz]?|cr[ée]e[rz]?|invente[rz]?|publie[rz]?)\b.{0,30}\b(avis|t[ée]moignages?)\b",
        r"\bcinq [ée]toiles\b",
        # Arabic
        r"(تقييمات?|مراجعات?|تعليقات?|شهادات?|آراء)\s*(مزيفة|مزيف|وهمية|وهمي|مفبركة|مفبرك|كاذبة|كاذب)",
        r"(اكتب|أكتب|اكتبي|اعمل|أنشئ|انشر|ولد|ولّد|زيف|فبرك)\s.{0,30}(تقييمات?|مراجعات?|شهادات?|آراء)",
        r"خمس(ة)?\s*نجوم",
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
        # French
        r"\b(fais[- ]toi passer|faites[- ]vous passer|se faire passer|faire semblant d'[êe]tre|usurpe[rz]?)\b",
        r"\b(en mon nom|[àa] ma place|comme si (tu [ée]tais|c'[ée]tait) moi)\b",
        # Arabic
        r"(انتحل|تنتحل|انتحال|تقمص)",
        r"(تظاهر|اتظاهر|تتظاهر|اتنكر)\s*(بأنك|بانك|أنك|انك|إنك|إن|كأنك)",
        r"(باسمي|بإسمي|نيابة عني|نيابةً عني|كأنك أنا|كأنني أنا|على أنك أنا|بصفتي)",
    ),
    "income_promise": (
        r"\bguarantee(d|s)?\b.{0,30}\b(income|profits?|returns?|results|success|sales|revenue|customers|earnings|money)\b",
        r"\b(you|you'll|you will|founders?|buyers?|customers?|they) (will|can|could)?\s*(make|earn|generate)\b.{0,20}\$\s?\d",
        r"\b(make|earn)\s+\$\s?\d[\d,.]*\s*[km]?\s*(per|a|an|/|every)\s*(day|week|month|year|hour)\b",
        r"\bpassive income\b",
        r"\bget rich\b",
        r"\b(risk[- ]free|sure[- ]fire|surefire) (income|profits?|returns?|money|business|success)\b",
        r"\b100\s?% (success|guaranteed|profit)\b",
        r"\b(financial freedom|replace your (salary|income)|quit your (day )?job)\b",
        r"\bwill (generate|earn|make|bring in|reach)\b.{0,30}(\$\s?\d|\d[\d,.]*\s*(k|m)?\s*(in )?(revenue|mrr|arr|profit))",
        r"\b(guaranteed|certain|assured) to (succeed|work|sell|make money)\b",
        # French
        r"\b(revenus?|gains?|profits?|b[ée]n[ée]fices?)\s+(garantis?|assur[ée]s?|s[ûu]rs?)\b",
        r"\bgaranti(e|es|s|t|ssons)?\b.{0,30}\b(revenus?|gains?|succ[èe]s|ventes|profits?|b[ée]n[ée]fices?)\b",
        r"\brevenus? passifs?\b",
        r"\b(tu vas|vous allez|vous allez) (gagner|toucher|empocher)\b",
        r"\bdevenir riche\b",
        # Arabic
        r"(دخل|ربح|أرباح|ارباح|عائد|مكسب)\s*(مضمون|مضمونة|مؤكد|مؤكدة|ثابت)",
        r"(نضمن|يضمن|تضمن|ضمان|مضمون)\s.{0,20}(دخل|ربح|أرباح|ارباح|نجاح|مبيعات|فلوس)",
        r"(ستربح|هتكسب|ستكسب|هتربح|هتعمل فلوس)",
        r"دخل\s*سلبي",
        r"الثراء\s*السريع",
    ),
    "money_handling": (
        r"\b(transfer|wire|withdraw|move|send|hold|escrow|disburse|pay out)\w*\b.{0,30}\b(money|funds|cash|balance|deposits?|payouts?|\$\s?\d[\d,.]*)\b",
        r"\b(refund|charge|bill|debit)\w*\b.{0,30}\b(the customer|customers|their card|my card|the card|users?|buyers?|\$\s?\d[\d,.]*)\b",
        r"\b(log ?in|sign ?in|access)\b.{0,20}\b(my|the|our|their)\b.{0,10}\b(bank|paypal|stripe|wise|payoneer|brokerage) account\b",
        r"\b(hold|keep|manage|store)\b.{0,20}\b(customer|client|user)s?'? (money|funds|payments)\b",
        # First person: "I've refunded your payment", "we have transferred the money to you"
        r"\b(i|we)('ve|'ll| have| will| just| already)*\s+(refunded|refund|transferred|transfer|sent|send|moved|wired|charged|charge|credited)\b.{0,25}\b(you|your|the money|money|payment|funds|amount|\$\s?\d)",
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

# Credentials are not negatable: a secret in the text is a leak whatever surrounds it.
_NEGATABLE = set(TEXT_RULES) - {"credentials"}

_CARD_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")


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
    text = text.replace("’", "'").replace("‘", "'")  # curly apostrophes
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
    "brief_text",
    "TEXT_RULES",
    "ALLOWED",
    "BANNED_CATEGORIES",
    "CATEGORY_REASONS",
    "TEXT_REASONS",
    "STUBBED",
]
