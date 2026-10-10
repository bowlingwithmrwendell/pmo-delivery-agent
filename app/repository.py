"""Reads stored rows and converts them into engine types; runs the engines.

This is the single place the API and the Claude agent get their numbers from,
so both always agree.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .config import STATUS_DATE
from .engines.dependencies import analyse_dependencies
from .engines.evm import compute_evm
from .engines.milestones import milestone_health
from .engines.rag import AMBER, GREEN, RED, determine_rag, worst
from .engines.raid import raid_log, raid_summary
from .engines.report import build_status_report
from .engines.resources import resource_analysis
from .engines.types import (Assignment, CrossDependency, Milestone, Person, Project, RaidItem,
                            SkillDemand)
from .models import (AssignmentRow, DependencyRow, MilestoneRow, PersonRow, ProjectRow, RaidRow,
                     SkillDemandRow)


class NotFound(LookupError):
    pass


def _project(r: ProjectRow) -> Project:
    return Project(id=r.id, name=r.name, program=r.program, sponsor=r.sponsor,
                   delivery_lead=r.delivery_lead, bac=str(r.bac), pv=str(r.pv), ev=str(r.ev),
                   ac=str(r.ac), elapsed_days=r.elapsed_days,
                   milestone_target_pct=str(r.milestone_target_pct),
                   accomplishments=list(r.accomplishments or []))


def _milestone(r: MilestoneRow) -> Milestone:
    return Milestone(id=r.id, project_id=r.project_id, name=r.name, baseline_date=r.baseline_date,
                     forecast_date=r.forecast_date, actual_date=r.actual_date,
                     critical_path=r.critical_path, owner=r.owner)


def _raid(r: RaidRow) -> RaidItem:
    return RaidItem(id=r.id, project_id=r.project_id, type=r.type, category=r.category,
                    description=r.description, probability=r.probability, impact=r.impact,
                    mitigation=r.mitigation or "", owner=r.owner or "", status=r.status,
                    blocker=r.blocker, critical_path=r.critical_path)


def get_project(s: Session, project_id: str) -> Project:
    row = s.get(ProjectRow, project_id)
    if row is None:
        raise NotFound(f"Unknown project '{project_id}'")
    return _project(row)


def list_projects(s: Session) -> list[Project]:
    return [_project(r) for r in s.query(ProjectRow).order_by(ProjectRow.id)]


def milestones_for(s: Session, project_id: str | None = None) -> list[Milestone]:
    q = s.query(MilestoneRow)
    if project_id:
        q = q.filter(MilestoneRow.project_id == project_id)
    return [_milestone(r) for r in q.order_by(MilestoneRow.id)]


def raid_for(s: Session, project_id: str | None = None) -> list[RaidItem]:
    q = s.query(RaidRow)
    if project_id:
        q = q.filter(RaidRow.project_id == project_id)
    return [_raid(r) for r in q.order_by(RaidRow.id)]


# --- computed views ---------------------------------------------------------

def project_evm(s: Session, project_id: str) -> dict:
    p = get_project(s, project_id)
    return {"project_id": p.id, "name": p.name,
            **compute_evm(p.bac, p.pv, p.ev, p.ac, p.elapsed_days).as_dict()}


def project_rag(s: Session, project_id: str) -> dict:
    p = get_project(s, project_id)
    evm = compute_evm(p.bac, p.pv, p.ev, p.ac, p.elapsed_days)
    return {"project_id": p.id, "name": p.name, **determine_rag(evm, raid_for(s, p.id))}


def project_raid(s: Session, project_id: str | None, include_closed: bool = False) -> dict:
    if project_id:
        get_project(s, project_id)
    items = raid_for(s, project_id)
    return {"project_id": project_id, "summary": raid_summary(items),
            "items": raid_log(items, include_closed=include_closed)}


def project_milestones(s: Session, project_id: str, as_of: date | None = None) -> dict:
    p = get_project(s, project_id)
    return {"project_id": p.id, "name": p.name,
            **milestone_health(milestones_for(s, p.id), as_of or STATUS_DATE, p.milestone_target_pct)}


def status_report(s: Session, project_id: str, as_of: date | None = None) -> dict:
    p = get_project(s, project_id)
    return build_status_report(p, milestones_for(s, p.id), raid_for(s, p.id), as_of or STATUS_DATE)


def portfolio(s: Session) -> dict:
    rows = []
    for p in list_projects(s):
        evm = compute_evm(p.bac, p.pv, p.ev, p.ac, p.elapsed_days)
        rag = determine_rag(evm, raid_for(s, p.id))
        e = evm.as_dict()
        rows.append({"project_id": p.id, "name": p.name, "delivery_lead": p.delivery_lead,
                     "rag": rag["status"], "spi": e["spi"], "cpi": e["cpi"],
                     "sv_pct": e["sv_pct"], "cv_pct": e["cv_pct"],
                     "percent_complete": e["percent_complete"],
                     "top_reason": rag["reasons"][0]["message"] if rag["reasons"] else None,
                     "explanation": rag["explanation"]})
    statuses = [r["rag"] for r in rows]
    return {
        "explanation": {
            "formula": "Program RAG = worst RAG of any stream",
            "inputs": {r["project_id"]: r["rag"] for r in rows},
            "reasoning": f"Worst stream status is {worst(GREEN, *statuses)}, so the program is "
                         f"{worst(GREEN, *statuses)}."},
        "program": rows and list_projects(s)[0].program,
        "status_date": STATUS_DATE.isoformat(),
        "program_rag": worst(GREEN, *statuses),
        "counts": {c: statuses.count(c) for c in (GREEN, AMBER, RED)},
        "projects": rows,
    }


def resources(s: Session) -> dict:
    people = [Person(id=r.id, name=r.name, role=r.role, capacity_hours=str(r.capacity_hours),
                     skills=list(r.skills or [])) for r in s.query(PersonRow).order_by(PersonRow.id)]
    assigns = [Assignment(person_id=r.person_id, project_id=r.project_id,
                          hours_per_week=str(r.hours_per_week), skill=r.skill)
               for r in s.query(AssignmentRow).order_by(AssignmentRow.id)]
    demands = [SkillDemand(project_id=r.project_id, skill=r.skill, fte_needed=str(r.fte_needed))
               for r in s.query(SkillDemandRow).order_by(SkillDemandRow.id)]
    return resource_analysis(people, assigns, demands)


def dependencies(s: Session) -> dict:
    deps = [CrossDependency(id=r.id, provider_project_id=r.provider_project_id,
                            provider_milestone_id=r.provider_milestone_id,
                            consumer_project_id=r.consumer_project_id, needed_by=r.needed_by,
                            description=r.description)
            for r in s.query(DependencyRow).order_by(DependencyRow.id)]
    return analyse_dependencies(deps, milestones_for(s))
