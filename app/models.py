"""Database schema (PostgreSQL in Docker / Render, SQLite for local tests).

Money is stored as NUMERIC(14,2) and read back as Decimal -- never float.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    program: Mapped[str] = mapped_column(String(200))
    sponsor: Mapped[str] = mapped_column(String(120))
    delivery_lead: Mapped[str] = mapped_column(String(120))
    bac: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    pv: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ev: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ac: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    elapsed_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    milestone_target_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("85"))
    accomplishments: Mapped[list] = mapped_column(JSON, default=list)


class MilestoneRow(Base):
    __tablename__ = "milestones"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    baseline_date: Mapped[date] = mapped_column(Date)
    forecast_date: Mapped[date] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    critical_path: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str] = mapped_column(String(120), default="")


class RaidRow(Base):
    __tablename__ = "raid_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mitigation: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    blocker: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_path: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PersonRow(Base):
    __tablename__ = "people"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120))
    capacity_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("40"))
    skills: Mapped[list] = mapped_column(JSON, default=list)


class AssignmentRow(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    hours_per_week: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    skill: Mapped[str] = mapped_column(String(60))


class SkillDemandRow(Base):
    __tablename__ = "skill_demands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    skill: Mapped[str] = mapped_column(String(60))
    fte_needed: Mapped[Decimal] = mapped_column(Numeric(5, 2))


class DependencyRow(Base):
    __tablename__ = "cross_dependencies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    provider_milestone_id: Mapped[str] = mapped_column(ForeignKey("milestones.id"))
    consumer_project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    needed_by: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")


class PendingActionRow(Base):
    """Every outbound action (Slack digest, Jira ticket) waits here for a human."""
    __tablename__ = "pending_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String(40))
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    requested_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditRow(Base):
    """Append-only trail of every agent tool call and every approval decision."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(60))
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON)


class AICallRow(Base):
    """One row per model call attempt: who, when, model, tools, tokens, outcome."""
    __tablename__ = "ai_call_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    visitor: Mapped[str] = mapped_column(String(64), index=True)   # salted hash of the client address
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(32))                  # AGENT_ASK | REPORT_NARRATIVE
    model: Mapped[str] = mapped_column(String(80))
    tools: Mapped[list] = mapped_column(JSON, default=list)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)   # round trips to the model
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # OK | ERROR | RATE_LIMITED | CAP_REACHED | KILL_SWITCH | UNAVAILABLE
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    review_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AIReviewRow(Base):
    """Every AI output waits here, PENDING_REVIEW, until a named human decides.

    `ai_output` is the model's original text and is never changed. A reviewer
    may approve it, edit-then-approve (the edit goes to `final_output`), or
    reject it with a reason. Only APPROVED / APPROVED_WITH_EDITS outputs are
    ever published.
    """
    __tablename__ = "ai_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    kind: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    ai_output: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(80))
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    unverified_numbers: Mapped[list] = mapped_column(JSON, default=list)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    visitor: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="PENDING_REVIEW", index=True)
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class KillSwitchEventRow(Base):
    """Append-only history of runtime kill-switch changes. Latest row wins."""
    __tablename__ = "kill_switch_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    engaged: Mapped[bool] = mapped_column(Boolean)
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text, default="")


# --- append-only enforcement ---------------------------------------------------
# The ORM refuses to UPDATE or DELETE log rows. (Tests drop and recreate tables,
# which is DDL and unaffected.)
from sqlalchemy import event  # noqa: E402


class AppendOnlyViolation(RuntimeError):
    pass


def _refuse(kind):
    def handler(mapper, connection, target):
        raise AppendOnlyViolation(f"{type(target).__tablename__} is append-only; {kind} refused")
    return handler


for _cls in (AuditRow, AICallRow, KillSwitchEventRow):
    event.listen(_cls, "before_update", _refuse("UPDATE"))
    event.listen(_cls, "before_delete", _refuse("DELETE"))
