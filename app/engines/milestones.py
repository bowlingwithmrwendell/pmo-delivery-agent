"""Milestone health: completion rate, slippage, and upcoming milestones."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .explain import explain
from .types import Milestone


def milestone_health(milestones: list[Milestone], as_of: date,
                     target_pct: Decimal | str = "85", lookahead_days: int = 30) -> dict:
    """
    Completion rate = milestones completed (actual date on/before as_of) among
    those whose BASELINE date is on/before as_of, x 100.  Milestones not yet
    due are excluded so early progress doesn't inflate the rate.
    """
    target = Decimal(str(target_pct))
    due = [m for m in milestones if m.baseline_date <= as_of]
    done_on_due = [m for m in due if m.actual_date is not None and m.actual_date <= as_of]
    rate = None
    if due:
        rate = (Decimal(len(done_on_due)) / Decimal(len(due)) * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP)

    slipped = []
    for m in milestones:
        finish = m.actual_date or m.forecast_date
        slip = (finish - m.baseline_date).days
        if slip > 0:
            slipped.append({
                "id": m.id, "name": m.name, "slip_days": slip,
                "critical_path": m.critical_path, "complete": m.is_complete,
                "explanation": explain("Slip days = (actual date, else forecast date) - baseline date",
                                       {"baseline_date": m.baseline_date.isoformat(),
                                        "finish_date": finish.isoformat(),
                                        "finish_basis": "actual" if m.actual_date else "forecast"},
                                       f"{finish.isoformat()} - {m.baseline_date.isoformat()} = "
                                       f"{slip} days late."),
            })
    slipped.sort(key=lambda s: (-s["slip_days"], s["id"]))

    horizon = as_of + timedelta(days=lookahead_days)
    upcoming = sorted(
        (m for m in milestones if not m.is_complete and as_of <= m.forecast_date <= horizon),
        key=lambda m: (m.forecast_date, m.id),
    )
    overdue = sorted(
        (m for m in milestones if not m.is_complete and m.forecast_date < as_of),
        key=lambda m: (m.forecast_date, m.id),
    )

    if rate is None or rate >= target:
        rate_status = "GREEN"
    elif (target - rate) / target * 100 > 15:
        rate_status = "RED"
    else:
        rate_status = "AMBER"

    return {
        "as_of": as_of.isoformat(),
        "total": len(milestones),
        "due_to_date": len(due),
        "completed_of_due": len(done_on_due),
        "completion_rate_pct": None if rate is None else str(rate),
        "target_pct": str(target.quantize(Decimal("0.1"))),
        "completion_variance_pts": None if rate is None
        else str((rate - target).quantize(Decimal("0.1"))),
        "completion_status": rate_status,
        "explanation": explain(
            "Completion rate = milestones completed on/before as-of date / milestones whose "
            "baseline date has passed x 100. Status: >= target GREEN; shortfall vs target "
            "> 15% of target RED; otherwise AMBER.",
            {"as_of": as_of.isoformat(), "due_to_date": len(due), "completed_of_due": len(done_on_due),
             "target_pct": str(target), "due_ids": [m.id for m in due],
             "completed_ids": [m.id for m in done_on_due]},
            "No milestones are due yet, so there is no rate and status is GREEN." if rate is None else
            f"{len(done_on_due)} / {len(due)} x 100 = {rate}% against a {target}% target: "
            f"{rate_status}. Milestones not yet due are excluded so early finishes can't inflate it."),
        "slipped": slipped,
        "upcoming": [_m(m) for m in upcoming],
        "overdue": [_m(m, as_of) for m in overdue],
    }


def _m(m: Milestone, as_of: date | None = None) -> dict:
    d = {
        "id": m.id,
        "name": m.name,
        "baseline_date": m.baseline_date.isoformat(),
        "forecast_date": m.forecast_date.isoformat(),
        "critical_path": m.critical_path,
        "owner": m.owner,
    }
    if as_of is not None:
        d["days_overdue"] = (as_of - m.forecast_date).days
    return d
