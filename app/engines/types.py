"""Plain data types the engines operate on.

The engines never touch the database. The repository layer converts stored
records into these types, which keeps every calculation pure and testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# RAID item types
RISK, ASSUMPTION, ISSUE, DEPENDENCY = "RISK", "ASSUMPTION", "ISSUE", "DEPENDENCY"
RAID_TYPES = (RISK, ASSUMPTION, ISSUE, DEPENDENCY)

# RAID item statuses
OPEN, MONITORING, CLOSED = "OPEN", "MONITORING", "CLOSED"
RAID_STATUSES = (OPEN, MONITORING, CLOSED)


@dataclass
class RaidItem:
    id: str
    project_id: str
    type: str
    category: str
    description: str
    probability: int | None = None
    impact: int | None = None
    mitigation: str = ""
    owner: str = ""
    status: str = OPEN
    blocker: bool = False          # ISSUE only: actively blocking delivery
    critical_path: bool = False    # ISSUE only: blocking the critical path

    @property
    def is_open(self) -> bool:
        return self.status != CLOSED

    @property
    def is_mitigated(self) -> bool:
        """Mitigated = has both a mitigation strategy and a named owner."""
        return bool(self.mitigation.strip()) and bool(self.owner.strip())

    @property
    def effective_probability(self) -> int | None:
        # An issue has already materialised, so its probability is certain (5).
        if self.type == ISSUE and self.impact is not None:
            return 5
        return self.probability


@dataclass
class Milestone:
    id: str
    project_id: str
    name: str
    baseline_date: date
    forecast_date: date
    actual_date: date | None = None
    critical_path: bool = False
    owner: str = ""

    @property
    def is_complete(self) -> bool:
        return self.actual_date is not None


@dataclass
class Project:
    id: str
    name: str
    program: str
    sponsor: str
    delivery_lead: str
    bac: str
    pv: str
    ev: str
    ac: str
    elapsed_days: int | None = None
    milestone_target_pct: str = "85"
    accomplishments: list[str] = field(default_factory=list)


@dataclass
class Assignment:
    person_id: str
    project_id: str
    hours_per_week: str
    skill: str


@dataclass
class Person:
    id: str
    name: str
    role: str
    capacity_hours: str = "40"
    skills: list[str] = field(default_factory=list)


@dataclass
class SkillDemand:
    project_id: str
    skill: str
    fte_needed: str


@dataclass
class CrossDependency:
    id: str
    provider_project_id: str
    provider_milestone_id: str
    consumer_project_id: str
    needed_by: date
    description: str = ""
