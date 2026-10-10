"""Cross-project dependency management.

A dependency says: the CONSUMER project needs the PROVIDER project's
milestone delivered by `needed_by`.

    Conflict  = provider milestone's forecast (or actual) date > needed_by
    Slip days = that date - needed_by
    At risk   = no conflict yet, but less than `buffer_days` of float remains

Also detects circular project dependencies (A waits on B waits on A), which
can never be scheduled and always need executive resolution.
"""
from __future__ import annotations

from collections import defaultdict

from .explain import explain
from .types import CrossDependency, Milestone


def analyse_dependencies(deps: list[CrossDependency], milestones: list[Milestone],
                         buffer_days: int = 5) -> dict:
    ms = {m.id: m for m in milestones}
    results = []
    for d in deps:
        m = ms.get(d.provider_milestone_id)
        if m is None:
            results.append({"id": d.id, "status": "UNKNOWN_MILESTONE",
                            "provider_milestone_id": d.provider_milestone_id})
            continue
        delivered = m.actual_date or m.forecast_date
        float_days = (d.needed_by - delivered).days
        if float_days < 0:
            status = "CONFLICT"
        elif m.actual_date is not None:
            status = "SATISFIED"
        elif float_days < buffer_days:
            status = "AT_RISK"
        else:
            status = "ON_TRACK"
        results.append({
            "id": d.id,
            "description": d.description,
            "provider_project_id": d.provider_project_id,
            "provider_milestone_id": m.id,
            "provider_milestone": m.name,
            "consumer_project_id": d.consumer_project_id,
            "needed_by": d.needed_by.isoformat(),
            "provider_date": delivered.isoformat(),
            "float_days": float_days,
            "slip_days": max(-float_days, 0),
            "status": status,
            "explanation": explain(
                f"Float = needed-by date - provider date. Float < 0 CONFLICT; delivered SATISFIED; "
                f"float < {buffer_days} days AT_RISK; otherwise ON_TRACK.",
                {"needed_by": d.needed_by.isoformat(), "provider_date": delivered.isoformat(),
                 "provider_date_basis": "actual" if m.actual_date else "forecast",
                 "buffer_days": buffer_days},
                f"{d.needed_by.isoformat()} - {delivered.isoformat()} = {float_days} days of float: "
                f"{status}."),
        })
    order = {"CONFLICT": 0, "UNKNOWN_MILESTONE": 1, "AT_RISK": 2, "ON_TRACK": 3, "SATISFIED": 4}
    results.sort(key=lambda r: (order[r["status"]], r["id"]))

    return {
        "summary": {s: sum(1 for r in results if r["status"] == s) for s in order},
        "dependencies": results,
        "cycles": find_cycles(deps),
    }


def find_cycles(deps: list[CrossDependency]) -> list[list[str]]:
    """Return each distinct cycle in the consumer -> provider project graph."""
    graph = defaultdict(set)
    for d in deps:
        graph[d.consumer_project_id].add(d.provider_project_id)

    cycles, seen = [], set()
    WHITE, GREY, BLACK = 0, 1, 2
    color = defaultdict(int)
    stack: list[str] = []

    def visit(node: str):
        color[node] = GREY
        stack.append(node)
        for nxt in sorted(graph[node]):
            if color[nxt] == GREY:
                cyc = stack[stack.index(nxt):]
                # normalise rotation so the same cycle is reported once
                i = cyc.index(min(cyc))
                norm = tuple(cyc[i:] + cyc[:i])
                if norm not in seen:
                    seen.add(norm)
                    cycles.append(list(norm) + [norm[0]])
            elif color[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        color[node] = BLACK

    for n in sorted(list(graph)):
        if color[n] == WHITE:
            visit(n)
    return cycles
