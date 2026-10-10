"""Resource optimisation across delivery streams.

    Utilisation %   = total assigned hours/week across all projects / capacity x 100
    Overallocated   = utilisation > 100%
    Underutilised   = utilisation < 50%
    Skills gap      = FTE needed for a skill on a project - FTE assigned to that
                      skill on that project (1 FTE = the person's capacity)
    Single point of failure (SPOF) = a skill demanded by at least one project
                      that exactly one person in the pool holds
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from .explain import explain
from .types import Assignment, Person, SkillDemand

OVER = Decimal("100")
UNDER = Decimal("50")


def _r(v: Decimal, step="0.1") -> str:
    return str(v.quantize(Decimal(step), rounding=ROUND_HALF_UP))


def resource_analysis(people: list[Person], assignments: list[Assignment],
                      demands: list[SkillDemand]) -> dict:
    by_id = {p.id: p for p in people}
    for a in assignments:
        if a.person_id not in by_id:
            raise ValueError(f"Assignment references unknown person {a.person_id}")

    # --- utilisation -------------------------------------------------------
    hours = defaultdict(Decimal)
    projects_by_person = defaultdict(set)
    for a in assignments:
        hours[a.person_id] += Decimal(a.hours_per_week)
        projects_by_person[a.person_id].add(a.project_id)

    utilisation = []
    for p in people:
        cap = Decimal(p.capacity_hours)
        pct = hours[p.id] / cap * 100 if cap else Decimal(0)
        flag = "OVERALLOCATED" if pct > OVER else ("UNDERUTILISED" if pct < UNDER else "OK")
        utilisation.append({
            "person_id": p.id,
            "name": p.name,
            "role": p.role,
            "capacity_hours": _r(cap, "0.01"),
            "assigned_hours": _r(hours[p.id], "0.01"),
            "utilisation_pct": _r(pct),
            "over_by_hours": _r(max(hours[p.id] - cap, Decimal(0)), "0.01"),
            "projects": sorted(projects_by_person[p.id]),
            "flag": flag,
            "explanation": explain(
                "Utilisation % = assigned hours/week across all streams / capacity x 100; "
                "> 100% OVERALLOCATED, < 50% UNDERUTILISED",
                {"assigned_hours": _r(hours[p.id], "0.01"), "capacity_hours": _r(cap, "0.01"),
                 "assignments": [{"project_id": a.project_id, "hours_per_week": a.hours_per_week}
                                 for a in assignments if a.person_id == p.id]},
                f"{_r(hours[p.id], '0.01')} / {_r(cap, '0.01')} x 100 = {_r(pct)}%: {flag}."),
        })
    utilisation.sort(key=lambda u: (-Decimal(u["utilisation_pct"]), u["person_id"]))

    # --- skills gaps -------------------------------------------------------
    supplied = defaultdict(Decimal)  # (project, skill) -> FTE
    for a in assignments:
        cap = Decimal(by_id[a.person_id].capacity_hours)
        if cap:
            supplied[(a.project_id, a.skill)] += Decimal(a.hours_per_week) / cap

    gaps = []
    for d in demands:
        need = Decimal(d.fte_needed)
        have = supplied[(d.project_id, d.skill)]
        short = need - have
        if short > 0:
            gaps.append({
                "project_id": d.project_id,
                "skill": d.skill,
                "fte_needed": _r(need, "0.01"),
                "fte_assigned": _r(have, "0.01"),
                "fte_short": _r(short, "0.01"),
                "explanation": explain(
                    "FTE short = FTE needed - FTE assigned; FTE assigned = sum(hours on this skill "
                    "and stream / that person's capacity)",
                    {"fte_needed": _r(need, "0.01"), "fte_assigned": _r(have, "0.01")},
                    f"{_r(need, '0.01')} - {_r(have, '0.01')} = {_r(short, '0.01')} FTE short."),
            })
    gaps.sort(key=lambda g: (-Decimal(g["fte_short"]), g["project_id"], g["skill"]))

    # --- single points of failure -----------------------------------------
    holders = defaultdict(list)
    for p in people:
        for s in p.skills:
            holders[s].append(p)
    demanded = defaultdict(set)
    for d in demands:
        demanded[d.skill].add(d.project_id)

    util_by_id = {u["person_id"]: u for u in utilisation}
    spofs = []
    for skill in sorted(demanded):
        who = holders.get(skill, [])
        if len(who) == 1:
            person = who[0]
            u = util_by_id[person.id]
            spofs.append({
                "skill": skill,
                "person_id": person.id,
                "name": person.name,
                "projects_depending": sorted(demanded[skill]),
                "person_overallocated": u["flag"] == "OVERALLOCATED",
                "severity": "CRITICAL" if u["flag"] == "OVERALLOCATED"
                            or len(demanded[skill]) > 1 else "HIGH",
                "explanation": explain(
                    "SPOF = a demanded skill held by exactly one person. CRITICAL if that person "
                    "is overallocated or the skill serves more than one stream; otherwise HIGH.",
                    {"holders": [person.id], "streams_demanding": sorted(demanded[skill]),
                     "holder_flag": u["flag"]},
                    f"Only {person.name} holds {skill}; {len(demanded[skill])} stream(s) need it and "
                    f"the holder is {u['flag']}."),
            })
        elif len(who) == 0:
            spofs.append({
                "skill": skill, "person_id": None, "name": None,
                "projects_depending": sorted(demanded[skill]),
                "person_overallocated": False,
                "severity": "NO_COVERAGE",
                "explanation": explain("No coverage = a demanded skill held by nobody in the pool",
                                       {"holders": [], "streams_demanding": sorted(demanded[skill])},
                                       f"Nobody holds {skill}, but {len(demanded[skill])} stream(s) "
                                       "need it."),
            })

    return {
        "summary": {
            "people": len(people),
            "overallocated": sum(1 for u in utilisation if u["flag"] == "OVERALLOCATED"),
            "underutilised": sum(1 for u in utilisation if u["flag"] == "UNDERUTILISED"),
            "skills_gaps": len(gaps),
            "single_points_of_failure": sum(1 for s in spofs if s["severity"] != "NO_COVERAGE"),
            "skills_with_no_coverage": sum(1 for s in spofs if s["severity"] == "NO_COVERAGE"),
        },
        "utilisation": utilisation,
        "skills_gaps": gaps,
        "single_points_of_failure": spofs,
    }
