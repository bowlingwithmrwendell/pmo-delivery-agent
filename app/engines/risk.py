"""Risk exposure scoring.

    Risk Exposure = Probability (1-5) x Impact (1-5)

Bands (from the PMO specification):
    LOW     1-6   -> log and monitor monthly
    MEDIUM  8-12  -> active mitigation strategy required; review bi-weekly
    HIGH   15-25  -> escalate immediately to the Executive Sponsor; weekly tracking

Note: products of two integers 1-5 can never equal 7, 11, 13 or 14, so the
three bands cover every possible score with no gaps.
"""
from __future__ import annotations

from dataclasses import dataclass

from .explain import explain

LOW, MEDIUM, HIGH = "LOW", "MEDIUM", "HIGH"

BAND_POLICY = {
    LOW: {
        "range": "1-6",
        "action": "Log and monitor monthly.",
        "review_interval_days": 30,
        "escalate_to_sponsor": False,
    },
    MEDIUM: {
        "range": "8-12",
        "action": "Active mitigation strategy required; review bi-weekly.",
        "review_interval_days": 14,
        "escalate_to_sponsor": False,
    },
    HIGH: {
        "range": "15-25",
        "action": "Escalate immediately to Executive Sponsor; weekly mitigation tracking.",
        "review_interval_days": 7,
        "escalate_to_sponsor": True,
    },
}

SHORT_LABEL = {LOW: "LOW", MEDIUM: "MED", HIGH: "HIGH"}


class RiskInputError(ValueError):
    """Raised when probability or impact is outside the 1-5 scale."""


@dataclass(frozen=True)
class RiskScore:
    probability: int
    impact: int
    score: int
    band: str
    action: str
    review_interval_days: int
    escalate_to_sponsor: bool

    @property
    def label(self) -> str:
        """Display label matching the RAID log format, e.g. '16 (HIGH)'."""
        return f"{self.score} ({SHORT_LABEL[self.band]})"

    def as_dict(self) -> dict:
        return {
            "probability": self.probability,
            "impact": self.impact,
            "score": self.score,
            "band": self.band,
            "label": self.label,
            "action": self.action,
            "review_interval_days": self.review_interval_days,
            "escalate_to_sponsor": self.escalate_to_sponsor,
            "explanation": self.explanation(),
        }

    def explanation(self) -> dict:
        return explain(
            "Risk Exposure = Probability (1-5) x Impact (1-5); LOW 1-6, MEDIUM 8-12, HIGH 15-25",
            {"probability": self.probability, "impact": self.impact},
            f"{self.probability} x {self.impact} = {self.score}, which is in the {self.band} band "
            f"({BAND_POLICY[self.band]['range']}). Required action: {self.action}")


def _validate(name: str, value) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskInputError(f"{name} must be an integer from 1 to 5, got {value!r}")
    if not 1 <= value <= 5:
        raise RiskInputError(f"{name} must be from 1 to 5, got {value}")
    return value


def band_for(score: int) -> str:
    if score <= 6:
        return LOW
    if score <= 12:
        return MEDIUM
    return HIGH


def score_risk(probability: int, impact: int) -> RiskScore:
    p = _validate("probability", probability)
    i = _validate("impact", impact)
    score = p * i
    band = band_for(score)
    policy = BAND_POLICY[band]
    return RiskScore(
        probability=p,
        impact=i,
        score=score,
        band=band,
        action=policy["action"],
        review_interval_days=policy["review_interval_days"],
        escalate_to_sponsor=policy["escalate_to_sponsor"],
    )
