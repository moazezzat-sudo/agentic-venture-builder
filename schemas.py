"""Shared data contract for every agent, gate and the web app.

Briefcase is the LangGraph state. Lists that several nodes write to in
parallel (claims, questions) use an "add" reducer so parallel researchers
append instead of overwriting each other.
"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field, model_validator

Tier = Literal["A", "B", "C", "D", "NONE"]
Outcome = Literal["go", "repeat", "pivot", "stop"]
Status = Literal["Working", "MOCKED", "STUBBED"]
Support = Literal["url", "evidence", "ASSUMPTION"]

TIER_WEIGHTS: dict[str, float] = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.3, "NONE": 0.0}

BANNED_CATEGORIES = (
    "physical_goods",
    "financial_investment_crypto",
    "health_advice",
    "legal_advice",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Claim(BaseModel):
    """One statement the system relies on, with its support.

    Every claim is supported by a URL, by our own evidence (a test, eval,
    log entry or output file), or is labelled ASSUMPTION. Nothing else.
    """

    text: str
    support: Support
    url: Optional[str] = None
    tier: Tier = "NONE"
    accessed_at: Optional[str] = None
    evidence_ref: Optional[str] = None
    area: Optional[str] = None
    agent: Optional[str] = None

    @model_validator(mode="after")
    def _check_support(self) -> "Claim":
        if self.support == "url":
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError("support='url' needs an http(s) url")
            if self.accessed_at is None:
                self.accessed_at = utc_now()
        elif self.support == "evidence":
            if not self.evidence_ref:
                raise ValueError("support='evidence' needs evidence_ref (a test, eval, log or output path)")
        else:  # ASSUMPTION
            self.tier = "NONE"
        return self

    @property
    def weight(self) -> float:
        return TIER_WEIGHTS[self.tier] if self.support == "url" else 0.0


class FounderBrief(BaseModel):
    idea: str
    skills: list[str] = Field(default_factory=list)
    learned: list[str] = Field(default_factory=list)
    budget: Optional[str] = None
    time_available: Optional[str] = None
    location: Optional[str] = None
    target_market: Optional[str] = None
    values: list[str] = Field(default_factory=list)
    has_team: Optional[bool] = None
    team_skills: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    """What a gate recommends. The founder's answer is a separate FounderDecision."""

    phase: int
    gate: str
    recommendation: Outcome
    reasons: list[str]
    target: str
    evidence_summary: str = ""
    score: Optional[float] = None


class FounderDecision(BaseModel):
    """The founder's answer at a gate. Recorded with approved_by='founder'."""

    phase: int
    gate: str
    approved: bool
    outcome: Outcome
    note: str = ""
    decided_at: str = Field(default_factory=utc_now)
    overrides_recommendation: bool = False


class Briefcase(TypedDict, total=False):
    """LangGraph state carried through every phase."""

    run_id: str
    brief: dict[str, Any]
    clarifying_questions: Annotated[list[str], operator.add]
    founder_answers: dict[str, str]
    domain_weights: dict[str, float]
    innovation_type: str
    subdomain: str
    claims: Annotated[list[dict[str, Any]], operator.add]
    claim_checks: list[dict[str, Any]]
    scores: dict[str, float]
    gate_results: Annotated[list[dict[str, Any]], operator.add]
    founder_decisions: Annotated[list[dict[str, Any]], operator.add]
    current_phase: int
    stopped: bool
    # Phase 1 graph bookkeeping (orchestrator.py)
    round: int  # 1 on the first pass; +1 each coach loop. Claims carry the round they came from.
    evidence_from_round: int  # claims from this round on count; moves forward on an accepted pivot
    areas: list[dict[str, Any]]  # weigher output: [{name, weight, query}]
    research_area: dict[str, Any]  # the one area a parallel researcher works on (Send payload)
    score_notes: dict[str, str]  # one-line reason per rubric criterion, from the scorer
    stop_reason: str
    coach_notes: dict[str, Any]
    interview_kit: list[str]
    tokens: Annotated[int, operator.add]  # model tokens used in this run
