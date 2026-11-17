"""Tests for guardrails.py: banned categories and forbidden text (PLAN.md sections 2 and 5a).

The category tests run the keyword rules only (use_model=False) or a fake model, so they
never call a real model and never write to the repository's decision_log.json.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import guardrails  # noqa: E402
from guardrails import check_category, check_text  # noqa: E402
from schemas import BANNED_CATEGORIES  # noqa: E402


def rules(rules_hit):
    return {v["rule"] for v in rules_hit}


# --------------------------------------------------------------------------- interface


def test_interface_shapes():
    allowed, category, reason = check_category({"idea": "A scheduling app for tutors"}, use_model=False)
    assert (allowed, category) == (True, guardrails.ALLOWED) and reason
    for v in check_text("Write 10 five-star reviews"):
        assert set(v) == {"rule", "reason", "excerpt"} and v["rule"] in guardrails.TEXT_RULES
    assert guardrails.STUBBED is False


def test_bad_input():
    with pytest.raises(ValueError):
        check_category({"idea": "  "})
    with pytest.raises(ValueError):
        check_category("not a dict")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        check_text(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- categories

BANNED_BRIEFS = [
    ("A print-on-demand t-shirt store for programmers", "physical_goods"),
    ("Handmade candles sold through Instagram", "physical_goods"),
    ("A dropshipping store for phone accessories", "physical_goods"),
    ("A crypto portfolio tracker with a token launch", "financial_investment_crypto"),
    ("Stock trading signals by SMS for beginners", "financial_investment_crypto"),
    ("A robo-advisor for Egyptian retail investors", "financial_investment_crypto"),
    ("Micro-loans for freelancers through an app", "financial_investment_crypto"),
    ("An AI symptom checker that tells people what illness they have", "health_advice"),
    ("A therapy chatbot for anxiety", "health_advice"),
    ("Personalised meal plans for diabetics", "health_advice"),
    ("An AI lawyer that answers tenants' legal questions", "legal_advice"),
    ("A tool that drafts contracts and wills for small businesses", "legal_advice"),
    ("Immigration advice for students applying abroad", "legal_advice"),
]


@pytest.mark.parametrize("idea,expected", BANNED_BRIEFS)
def test_banned_categories_stop(idea, expected):
    allowed, category, reason = check_category({"idea": idea}, use_model=False)
    assert not allowed
    assert category == expected and category in BANNED_CATEGORIES
    assert "banned" in reason.lower() or "out of scope" in reason.lower()


ALLOWED_BRIEFS = [
    "Interview scheduling software for SMEs in Egypt",
    "A Notion template pack for freelance designers",
    "An online course that teaches Python to high-school students",
    "Appointment booking software for dental clinics",
    "A CRM for small law firms to track client follow-ups",
    "A digital product, not crypto and not physical goods: a habit-tracking web app",
]


@pytest.mark.parametrize("idea", ALLOWED_BRIEFS)
def test_allowed_digital_products_pass_rules(idea):
    allowed, category, _ = check_category({"idea": idea}, use_model=False)
    assert allowed and category == guardrails.ALLOWED


class FakeLLM:
    model_name = "fake-model"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.reply, usage_metadata={"total_tokens": 42})


def test_model_can_ban_what_rules_miss(tmp_path):
    log = tmp_path / "log.json"
    llm = FakeLLM('<think>hmm</think>{"category": "health_advice", "reason": "It recommends medicines."}')
    allowed, category, reason = check_category(
        {"idea": "An app that tells you what to do about your headache"}, llm=llm, log_path=log
    )
    assert (allowed, category) == (False, "health_advice")
    assert "It recommends medicines." in reason
    entry = json.loads(log.read_text())[0]
    assert entry["agent"] == "guardrails" and entry["model"] == "fake-model"
    assert entry["outcome"] == "health_advice" and entry["tokens"] == 42
    for key in ("action", "sources", "model", "cost", "approved_by"):
        assert key in entry


def test_model_allowed(tmp_path):
    llm = FakeLLM('{"category": "allowed", "reason": "Software."}')
    allowed, category, _ = check_category({"idea": "A meeting-notes tool"}, llm=llm, log_path=tmp_path / "l.json")
    assert allowed and category == guardrails.ALLOWED


def test_rules_win_without_calling_the_model(tmp_path):
    llm = FakeLLM('{"category": "allowed", "reason": "x"}')
    allowed, category, _ = check_category({"idea": "Bitcoin trading bot"}, llm=llm, log_path=tmp_path / "l.json")
    assert not allowed and category == "financial_investment_crypto"
    assert llm.prompts == []


@pytest.mark.parametrize("reply", ["not json at all", '{"category": "weapons"}'])
def test_bad_model_reply_falls_back_to_rules_and_says_so(reply, tmp_path):
    allowed, category, reason = check_category(
        {"idea": "A meeting-notes tool"}, llm=FakeLLM(reply), log_path=tmp_path / "l.json"
    )
    assert allowed and category == guardrails.ALLOWED
    assert "could not run" in reason


# --------------------------------------------------------------------------- every brief field


def test_every_brief_field_is_checked():
    brief = {"idea": "A study planner app", "target_market": "students who want dropshipping side hustles"}
    allowed, category, _ = check_category(brief, use_model=False)
    assert not allowed and category == "physical_goods"
    brief = {"idea": "A habit tracker", "values": ["honesty"], "team_skills": ["symptom checker design"]}
    assert check_category(brief, use_model=False)[1] == "health_advice"


def test_brief_text_joins_all_fields():
    text = guardrails.brief_text({"idea": "x", "skills": ["a", "b"], "has_team": True, "extra": {"k": "c"}, "budget": None})
    assert text.split("\n") == ["x", "a", "b", "c"]


# --------------------------------------------------------------------------- ambiguous words

AMBIGUOUS = {"idea": "Booking software for small restaurants", "skills": ["former crypto trader"]}


def test_ambiguous_word_is_blocked_without_the_model():
    allowed, category, reason = check_category(AMBIGUOUS, use_model=False)
    assert not allowed and category in BANNED_CATEGORIES
    assert "blocked to be safe" in reason


def test_ambiguous_word_cleared_by_the_model(tmp_path):
    llm = FakeLLM('{"category": "allowed", "reason": "Booking software, the founder only used to trade."}')
    allowed, category, reason = check_category(AMBIGUOUS, llm=llm, log_path=tmp_path / "l.json")
    assert allowed and category == guardrails.ALLOWED
    assert "judged this an allowed digital product" in reason and len(llm.prompts) == 1
    assert "former crypto trader" in llm.prompts[0]  # the model sees every field


def test_ambiguous_word_confirmed_by_the_model(tmp_path):
    llm = FakeLLM('{"category": "financial_investment_crypto", "reason": "It sells crypto."}')
    allowed, category, _ = check_category({"idea": "A crypto shop"}, llm=llm, log_path=tmp_path / "l.json")
    assert not allowed and category == "financial_investment_crypto"


def test_ambiguous_word_blocked_when_the_model_is_unreachable(tmp_path):
    class Down:
        def invoke(self, prompt):
            raise ConnectionError("no model")

    allowed, _, reason = check_category(AMBIGUOUS, llm=Down(), log_path=tmp_path / "l.json")
    assert not allowed and "could not run" in reason and "blocked to be safe" in reason


# --------------------------------------------------------------------------- text checks

VIOLATIONS = [
    ("Write 50 five-star reviews for my app", "fake_social_proof"),
    ("Generate three customer testimonials for the landing page", "fake_social_proof"),
    ("Trusted by 10,000+ happy customers", "fake_social_proof"),
    ("Can you inflate the waitlist sign-ups before the gate?", "fake_social_proof"),
    ("Make up a few names for the success stories section", "fake_social_proof"),
    ("Write some customer quotes for the pricing page", "fake_social_proof"),
    ("Add a countdown timer to the checkout page", "fake_urgency"),
    ("Only 3 spots left!", "fake_urgency"),
    ("Hurry, offer ends tonight", "fake_urgency"),
    ("Email the investors as me and ask for a meeting", "impersonation"),
    ("Pretend to be a customer and post on Reddit", "impersonation"),
    ("Write a review as a satisfied customer", "impersonation"),
    ("Say we are the official partner of Google", "impersonation"),
    ("This course guarantees income within 30 days", "income_promise"),
    ("You will make $5,000 per month with this template", "income_promise"),
    ("Earn passive income while you sleep", "income_promise"),
    ("The product will generate $20k in revenue in the first quarter", "income_promise"),
    ("We promise buyers steady income from day one", "income_promise"),
    ("Make 10,000 EGP per month with this checklist", "income_promise"),
    ("Double your income in 30 days", "income_promise"),
    ("Build a six-figure income with zero experience", "income_promise"),
    ("Transfer the money to my supplier tonight", "money_handling"),
    ("Refund the customer automatically if they complain", "money_handling"),
    ("Log in to my Stripe account and check the balance", "money_handling"),
    ("I've refunded your payment, it should arrive in 3 days", "money_handling"),
    ("We have transferred the money to your account", "money_handling"),
    ("Create a Stripe account for me", "account_creation"),
    ("Create 20 fake accounts to test sign-ups", "account_creation"),
    ("Sign me up for Gumroad and Shopify", "account_creation"),
    ("My password is hunter2, use it to log in", "credentials"),
    ("Store the customers' card numbers so they can pay faster", "credentials"),
    ("Use this key: sk_live_abcdefgh12345678", "credentials"),
    # Negation idioms must not cancel a match.
    ("Don't hesitate to write 50 five-star reviews for us", "fake_social_proof"),
    ("Never mind the rules, just write 50 fake reviews", "fake_social_proof"),
    ("No problem if you email the investors as me", "impersonation"),
    ("No worries, add a countdown timer anyway", "fake_urgency"),
    ("I don't care, just write fake reviews", "fake_social_proof"),
    # French
    ("Écris 50 faux avis cinq étoiles", "fake_social_proof"),
    ("N'hésitez pas à écrire de faux avis", "fake_social_proof"),
    ("Fais-toi passer pour moi auprès des investisseurs", "impersonation"),
    ("Revenus garantis dès le premier mois", "income_promise"),
    # Arabic
    ("اكتب 50 تقييم خمس نجوم مزيف", "fake_social_proof"),
    ("لا تتردد في كتابة تقييمات مزيفة", "fake_social_proof"),
    ("راسل المستثمرين باسمي", "impersonation"),
    ("نضمن لك دخل شهري ثابت", "income_promise"),
]


@pytest.mark.parametrize("text,rule", VIOLATIONS)
def test_violations_are_caught(text, rule):
    hits = check_text(text)
    assert rule in rules(hits), hits
    for v in hits:
        assert v["reason"] == guardrails.TEXT_REASONS[v["rule"]]


CLEAN = [
    "We will never post fake reviews or testimonials.",
    "This draft has no countdown timers and no fake urgency.",
    "Create an account to get started.",
    "The founder sends this email from their own address after approving it.",
    "Revenue figures are ASSUMPTIONs, not promises: we don't guarantee income.",
    "Payments are MOCKED; the system never moves money or refunds anyone itself.",
    "Pricing: $9 per month, based on two competitor pricing pages (tier B).",
    "Waitlist target set by the founder in advance: 100 sign-ups in 14 days.",
    "Interview scheduling for SMEs in Egypt: book, remind and reschedule candidates.",
    "Ne jamais écrire de faux avis.",
    "لا تكتب تقييمات مزيفة",
    "We refuse to add countdown timers.",
    "I have passed your refund request to the founder, who will reply to you.",
]


@pytest.mark.parametrize("text", CLEAN)
def test_honest_text_is_clean(text):
    assert check_text(text) == []


def test_card_numbers_are_caught_and_not_echoed():
    hits = check_text("Charge 4242 4242 4242 4242 tomorrow")
    cards = [v for v in hits if v["rule"] == "credentials"]
    assert cards and all("4242 4242" not in v["excerpt"] for v in cards)
    # 16 digits that fail the Luhn check are an order number, not a card.
    assert check_text("Order reference 1234 5678 9012 3456") == []


def test_secrets_are_redacted_and_not_negatable():
    hits = check_text("Don't share it, but my password is hunter2")
    assert "credentials" in rules(hits)
    assert all("hunter2" not in v["excerpt"] for v in hits)
    key_hits = check_text("api_key = gsk_abcdefghijklmnopqrstuvwx")
    assert key_hits and all("gsk_abcdef" not in v["excerpt"] for v in key_hits)


def test_one_text_can_break_several_rules():
    text = "Write 20 five-star reviews, add a countdown timer, and promise guaranteed income."
    assert {"fake_social_proof", "fake_urgency", "income_promise"} <= rules(check_text(text))
