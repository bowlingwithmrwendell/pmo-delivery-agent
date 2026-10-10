"""RAG (Red / Amber / Green) status determination.

Specification:
    GREEN  On schedule, cost within 5% tolerance, no critical blockers.
    AMBER  Schedule/cost variance between 5% and 15%; unmitigated medium risks present.
    RED    Schedule/cost variance > 15%; critical path blocked; executive intervention required.

How the spec is applied (documented so every decision is auditable):
  * Schedule variance % = SV / PV x 100.  Cost variance % = CV / EV x 100.
  * Only ADVERSE variance (behind schedule / over budget) degrades status.
    Being ahead or under budget never turns a project amber.
  * Boundaries: exactly 5.0% is still GREEN ("within 5%"); exactly 15.0% is
    AMBER ("between 5% and 15%"); anything above 15% is RED.
  * "Executive intervention required" = an open HIGH risk (15-25) with no
    mitigation plan or owner. A HIGH risk that IS mitigated is under weekly
    tracking and holds the project at AMBER.
  * A critical blocker that is not on the critical path holds AMBER
    (GREEN requires "no critical blockers"); one on the critical path is RED.
  * The overall status is the worst status triggered. Every trigger is
    returned as a reason so the result can be explained, not just asserted.
"""
from __future__ import annotations

from decimal import Decimal

from .evm import EVMResult
from .explain import explain
from .raid import score_item
from .risk import HIGH, MEDIUM
from .types import ISSUE, RaidItem

GREEN, AMBER, RED = "GREEN", "AMBER", "RED"
_ORDER = {GREEN: 0, AMBER: 1, RED: 2}

TOLERANCE_PCT = Decimal("5")
RED_THRESHOLD_PCT = Decimal("15")


def worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _ORDER[s]) if statuses else GREEN


def variance_status(variance_pct: Decimal | None) -> str:
    """RAG for a single signed variance percentage (negative = adverse)."""
    if variance_pct is None:
        return GREEN
    adverse = -variance_pct if variance_pct < 0 else Decimal(0)
    if adverse > RED_THRESHOLD_PCT:
        return RED
    if adverse > TOLERANCE_PCT:
        return AMBER
    return GREEN


def determine_rag(evm: EVMResult, raid_items: list[RaidItem]) -> dict:
    reasons: list[dict] = []

    def add(status: str, code: str, message: str):
        reasons.append({"status": status, "code": code, "message": message})

    sched = variance_status(evm.sv_pct)
    cost = variance_status(evm.cv_pct)
    if sched != GREEN:
        add(sched, "SCHEDULE_VARIANCE",
            f"Schedule variance {evm.sv_pct.quantize(Decimal('0.1'))}% is outside the 5% tolerance"
            + (" and beyond the 15% red threshold" if sched == RED else ""))
    if cost != GREEN:
        add(cost, "COST_VARIANCE",
            f"Cost variance {evm.cv_pct.quantize(Decimal('0.1'))}% is outside the 5% tolerance"
            + (" and beyond the 15% red threshold" if cost == RED else ""))

    open_items = [i for i in raid_items if i.is_open]
    for item in open_items:
        desc = item.description.rstrip(". ")
        if item.type == ISSUE and item.blocker:
            if item.critical_path:
                add(RED, "CRITICAL_PATH_BLOCKED",
                    f"{item.id} is blocking the critical path: {desc}")
            else:
                add(AMBER, "CRITICAL_BLOCKER",
                    f"{item.id} is an open critical blocker: {desc}")
            continue  # the blocker rule already governs this item
        scored = score_item(item)
        if scored["band"] == HIGH:
            if not scored["mitigated"]:
                add(RED, "UNMITIGATED_HIGH_RISK",
                    f"{item.id} scores {scored['score_label']} with no mitigation owner/plan "
                    "- executive intervention required")
            else:
                add(AMBER, "HIGH_RISK_UNDER_MITIGATION",
                    f"{item.id} scores {scored['score_label']}; mitigation active, weekly tracking")
        elif scored["band"] == MEDIUM and not scored["mitigated"]:
            add(AMBER, "UNMITIGATED_MEDIUM_RISK",
                f"{item.id} scores {scored['score_label']} with no mitigation owner/plan")

    overall = worst(GREEN, *(r["status"] for r in reasons))
    reasons.sort(key=lambda r: -_ORDER[r["status"]])
    pct = lambda v: None if v is None else str(v.quantize(Decimal("0.1")))  # noqa: E731
    if reasons:
        why = (f"{len(reasons)} rule(s) triggered; the worst is {overall}: "
               + "; ".join(f"[{r['status']}] {r['code']}" for r in reasons) + ".")
    else:
        why = ("No rule triggered: adverse schedule and cost variance are both within 5%, "
               "no critical blockers are open and no medium/high risk is unmitigated, so GREEN.")
    explanation = explain(
        "Overall RAG = worst status triggered. Variance: adverse > 15% RED, > 5% AMBER "
        "(SV% = SV/PV x 100, CV% = CV/EV x 100). Blocker on critical path RED, other critical "
        "blocker AMBER. Unmitigated HIGH risk RED, mitigated HIGH AMBER, unmitigated MEDIUM AMBER.",
        {"sv_pct": pct(evm.sv_pct), "cv_pct": pct(evm.cv_pct),
         "tolerance_pct": str(TOLERANCE_PCT), "red_threshold_pct": str(RED_THRESHOLD_PCT),
         "open_raid_items_evaluated": [i.id for i in open_items]},
        f"Schedule {sched}, cost {cost}. " + why)
    return {
        "status": overall,
        "schedule_status": sched,
        "cost_status": cost,
        "executive_intervention_required": overall == RED,
        "reasons": reasons,
        "explanation": explanation,
    }
