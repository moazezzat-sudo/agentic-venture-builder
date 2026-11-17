"""Phase 2-6 draft agents with a fake model: claims are supported, guardrails hold, files are STUBBED.

No network and no tokens: agents._common.invoke_model is replaced by a fake that returns
queued JSON replies. Outputs and the decision log go to a temp folder.
"""

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

import agents._common as common  # noqa: E402
import logger  # noqa: E402
from agents import phase2_lean_canvas  # noqa: E402
from config import Settings  # noqa: E402
from logger import REQUIRED_KEYS  # noqa: E402
from schemas import Claim  # noqa: E402
from test_claims import _unsupported_lines  # noqa: E402

STATE = {
    "run_id": "drafts-1",
    "round": 1,
    "brief": {"idea": "Interview-scheduling SaaS for SMEs in Egypt", "budget": "300 USD",
              "time_available": "15 hours a week", "location": "Cairo, Egypt"},
    "subdomain": "HR tech -> interview scheduling for SMEs in Egypt",
    "claims": [
        Claim(text="Recruiters complain scheduling takes hours", support="url",
              url="https://www.reddit.com/r/recruiting/x", tier="D", area="problem_evidence").model_dump(),
        Claim(text="Competitor charges 10 USD per seat", support="url",
              url="https://competitor.example.com/pricing", tier="B", area="willingness_to_pay").model_dump(),
        Claim(text="Unsourced guess", support="ASSUMPTION").model_dump(),  # not offered to the model
    ],
}


class FakeModel:
    """Returns queued replies in order; each call records (agent, user payload)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, agent, system, user, role="smart", max_tokens=500, temperature=None):
        self.calls.append({"agent": agent, "user": user, "temperature": temperature})
        reply = self.replies.pop(0) if self.replies else {}
        return (reply if isinstance(reply, str) else json.dumps(reply)), 100, 0.0, "fake-model"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(logger, "settings", Settings(outputs_dir=tmp_path / "outputs", decision_log_path=tmp_path / "log.json"))

    def use(*replies):
        fake = FakeModel(*replies)
        monkeypatch.setattr(common, "invoke_model", fake)
        return fake

    return {"use": use, "out": tmp_path / "outputs", "log": tmp_path / "log.json"}


def read_log(env):
    return json.loads(env["log"].read_text(encoding="utf-8"))


CANVAS = {
    "problem": [{"text": "Scheduling interviews takes recruiters hours", "source": 0}],
    "customer_segments": [{"text": "SME HR teams in Cairo", "source": None}],
    "unique_value_proposition": [{"text": "Book interviews in one link", "source": None}],
    "solution": [{"text": "Shared booking link with reminders", "source": None}],
    "channels": [{"text": "Recruiter communities", "source": 0}],
    "revenue_streams": [{"text": "Monthly subscription per seat", "source": 1}],
    "cost_structure": [{"text": "Hosting about 20 USD a month", "source": None}],
    "key_metrics": [{"text": "Interviews booked per week", "source": None}],
    "unfair_advantage": [{"text": "None yet", "source": None}],
    "unit_economics": [{"text": "Founder budget 300 USD", "source": 7}],
    "riskiest_assumption": "SMEs will pay for scheduling",
    "landing_page": {"headline": "Interview scheduling for small HR teams", "subheadline": "One link, fewer emails.",
                     "bullets": ["Shared availability", "Reminders"], "call_to_action": "Join the waitlist"},
}


# --------------------------------------------------------------------------- phase 2


def test_lean_canvas_supports_every_claim(env):
    fake = env["use"](CANVAS)
    update = phase2_lean_canvas.agent(dict(STATE))
    draft = update["drafts"]["phase2_lean_canvas"]

    assert draft["canvas"]["problem"][0]["support"] == "url"
    assert draft["canvas"]["problem"][0]["url"] == "https://www.reddit.com/r/recruiting/x"
    assert draft["canvas"]["revenue_streams"][0]["tier"] == "B"
    assert draft["canvas"]["cost_structure"][0]["support"] == "ASSUMPTION"
    assert draft["unit_economics"][0]["support"] == "ASSUMPTION"  # source 7 doesn't exist
    for c in draft["claims"]:
        Claim(**c)
    assert draft["waitlist"] == {"target": None, "real_count": None}
    assert update["text_violations"] == [] and update["tokens"] == 100

    sent = json.loads(fake.calls[0]["user"])
    assert len(sent["evidence"]) == 2 and "Unsourced guess" not in fake.calls[0]["user"]
    assert fake.calls[0]["temperature"] == 0

    path = env["out"] / "phase2_step1_lean_canvas.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("> **STUBBED**") and "not set by the system" in text.lower()
    assert _unsupported_lines(env["out"]) == []

    entry = read_log(env)[-1]
    assert all(k in entry for k in REQUIRED_KEYS) and entry["agent"] == "phase2_lean_canvas"
    assert entry["sources"] == ["https://competitor.example.com/pricing", "https://www.reddit.com/r/recruiting/x"]


def test_violation_is_rewritten_once(env):
    bad = {**CANVAS, "landing_page": {**CANVAS["landing_page"], "subheadline": "Join 5,000+ happy customers"}}
    fake = env["use"](bad, CANVAS)
    update = phase2_lean_canvas.agent(dict(STATE))
    assert len(fake.calls) == 2 and "previous_draft" in fake.calls[1]["user"]
    assert update["text_violations"] == []
    assert read_log(env)[-1]["rewrote"] is True


def test_violation_that_survives_the_rewrite_is_flagged(env):
    bad = {**CANVAS, "landing_page": {**CANVAS["landing_page"], "headline": "Guaranteed income in 30 days"}}
    env["use"](bad, bad)
    update = phase2_lean_canvas.agent(dict(STATE))
    rules = {v["rule"] for v in update["text_violations"]}
    assert "income_promise" in rules
    assert all(v["rewritable"] is True and v["agent"] == "phase2_lean_canvas" for v in update["text_violations"])
    assert "income_promise" in (env["out"] / "phase2_step1_lean_canvas.md").read_text(encoding="utf-8")


def test_bad_json_falls_back_to_empty_draft(env):
    env["use"]("not json", "still not json")
    update = phase2_lean_canvas.agent(dict(STATE))
    draft = update["drafts"]["phase2_lean_canvas"]
    assert draft["claims"] == [] and update["tokens"] == 200
    assert read_log(env)[-1]["parsed"] is False


# --------------------------------------------------------------------------- phase 4

from agents import phase4_commercial  # noqa: E402

COMMERCIAL = {
    "pricing": {"currency": "EGP", "price": "250 per month", "model": "subscription",
                "basis": [{"text": "Competitor charges 10 USD per seat", "source": 1}]},
    "policies": {"terms": ["Use for hiring only"], "privacy": ["Candidate data deleted after 90 days"],
                 "refund": ["The seller refunds the customer's first month on request within 14 days"]},
    "rules_checklist": [{"text": "Register with the data-protection authority", "source": 0}],
    "marketing": [{"channel": "Recruiter subreddits", "why": "pain posts found there", "source": 0}],
}


def test_commercial_draft(env):
    env["use"](COMMERCIAL)
    update = phase4_commercial.agent(dict(STATE))
    draft = update["drafts"]["phase4_commercial"]
    assert draft["price_has_sourced_basis"] is True and draft["pricing"]["basis"][0]["tier"] == "B"
    assert update["text_violations"] == []  # the refund policy may talk about refunds
    text = (env["out"] / "phase4_step1_commercial.md").read_text(encoding="utf-8")
    assert text.startswith("> **STUBBED**")
    assert text.count("Draft, not legal advice") == 3
    assert "Not from an official source" in text  # the rule cites a tier-D source, not tier A
    assert "MOCKED" in text and _unsupported_lines(env["out"]) == []


def test_commercial_exemption_is_only_for_money_handling_in_the_refund_policy(env):
    bad = {**COMMERCIAL, "policies": {**COMMERCIAL["policies"],
                                      "refund": ["Refunds guaranteed, plus guaranteed income for resellers"],
                                      "terms": ["The system will refund the customer automatically"]}}
    env["use"](bad, bad)
    rules = {(v["source"].split("[")[0], v["rule"]) for v in phase4_commercial.agent(dict(STATE))["text_violations"]}
    assert ("policies.refund", "income_promise") in rules
    assert ("policies.terms", "money_handling") in rules


def test_unsourced_price_is_called_an_assumption(env):
    env["use"]({**COMMERCIAL, "pricing": {**COMMERCIAL["pricing"], "basis": [{"text": "Feels right", "source": None}]}})
    update = phase4_commercial.agent(dict(STATE))
    assert update["drafts"]["phase4_commercial"]["price_has_sourced_basis"] is False
    assert "no sourced basis" in (env["out"] / "phase4_step1_commercial.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- phase 5

from agents import phase5_launch  # noqa: E402

LAUNCH = {
    "segment": [{"text": "SME HR teams that hire weekly", "source": 0}],
    "positioning": "Interview scheduling without email ping-pong",
    "channels": [{"text": "Recruiter subreddits", "source": 0}, {"text": "LinkedIn HR groups", "source": None}],
    "launch_sequence": ["Share the waitlist page", "Interview 5 recruiters"],
    "store_page": {"title": "Interview scheduler", "description": "Candidates pick a slot from one link.",
                   "bullets": ["Reminders", "Calendar sync"]},
    "launch_posts": [{"channel": "LinkedIn", "text": "I'm building an interview scheduler for small HR teams. Feedback welcome."}],
}


def test_launch_draft_posts_nothing_and_uses_the_phase4_price(env):
    fake = env["use"](LAUNCH)
    state = {**STATE, "drafts": {"phase4_commercial": {"pricing": {"price": "250", "currency": "EGP"}}}}
    update = phase5_launch.agent(state)
    draft = update["drafts"]["phase5_launch"]
    assert draft["posted"] is False and all(p["posted"] is False for p in draft["launch_posts"])
    assert draft["store_page"]["price"] == "250 EGP" and json.loads(fake.calls[0]["user"])["price"] == "250 EGP"
    assert draft["channels"][1]["support"] == "ASSUMPTION"
    text = (env["out"] / "phase5_step1_launch.md").read_text(encoding="utf-8")
    assert "Nothing has been posted" in text and "founder_approved=True" in text
    assert _unsupported_lines(env["out"]) == []


def test_launch_without_a_price_does_not_invent_one(env):
    env["use"](LAUNCH)
    draft = phase5_launch.agent(dict(STATE))["drafts"]["phase5_launch"]
    assert draft["store_page"]["price"] is None


def test_launch_post_posing_as_a_customer_is_flagged(env):
    bad = {**LAUNCH, "launch_posts": [{"channel": "Reddit", "text": "Post as a happy customer: best tool ever, 5-star reviews everywhere!"}]}
    env["use"](bad, bad)
    rules = {v["rule"] for v in phase5_launch.agent(dict(STATE))["text_violations"]}
    assert {"impersonation", "fake_social_proof"} <= rules


# --------------------------------------------------------------------------- phase 3

from agents import phase3_build_plan  # noqa: E402

BUILD = {
    "stack": [{"component": "Backend", "choice": "FastAPI", "why": "Founder knows Python"}],
    "database": {"choice": "SQLite", "why": "Local, free"},
    "flows": ["Recruiter shares a link; candidate picks a slot"],
    "screens": [{"name": "Booking page", "purpose": "Candidate picks a slot"}],
    "riskiest_assumption": {"text": "Recruiters will switch from email", "source": 0},
    "mvp_features": ["Booking link", "Email reminder"],
    "out_of_scope": ["Payments"],
    "how_mvp_tests_it": "Five recruiters use it for a week",
    "feasibility": [{"text": "About 60 hours of work fits 15 hours a week for 4 weeks", "source": None}],
}


def test_build_plan(env):
    fake = env["use"](BUILD)
    state = {**STATE, "scores": {"problem_evidence": 3, "market": 1, "founder_fit": 2},
             "score_notes": {"market": "no tier A numbers"}}
    draft = phase3_build_plan.agent(state)["drafts"]["phase3_build_plan"]
    assert [w["criterion"] for w in draft["weakest_criteria"]] == ["market", "founder_fit"]
    assert json.loads(fake.calls[0]["user"])["weakest_criteria"][0]["note"] == "no tier A numbers"
    assert draft["database"]["local"] is True
    assert draft["riskiest_assumption"][0]["support"] == "url" and draft["feasibility"][0]["support"] == "ASSUMPTION"
    text = (env["out"] / "phase3_step1_build_plan.md").read_text(encoding="utf-8")
    assert text.split("## Not built yet")[1].count("**STUBBED**") == 3
    assert "not promises" in text and _unsupported_lines(env["out"]) == []


def test_cloud_database_needs_the_founder(env):
    env["use"]({**BUILD, "database": {"choice": "Firebase free tier", "why": "hosted"}})
    draft = phase3_build_plan.agent(dict(STATE))["drafts"]["phase3_build_plan"]
    assert draft["database"]["local"] is False
    text = (env["out"] / "phase3_step1_build_plan.md").read_text(encoding="utf-8")
    assert "founder creates any account" in text


def test_empty_reply_defaults_to_a_local_database(env):
    env["use"]("{}", "{}")
    draft = phase3_build_plan.agent(dict(STATE))["drafts"]["phase3_build_plan"]
    assert draft["database"] == {"choice": "SQLite (local file)", "why": "", "local": True}
