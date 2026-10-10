"""Executive status report assembly and Markdown rendering.

The report is built entirely from engine output. An optional narrative
(written by Claude) may replace the deterministic executive summary, but only
after `narrative_is_grounded` confirms it introduces no number that is not
already in the computed facts.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .evm import compute_evm
from .explain import explain
from .milestones import milestone_health
from .rag import AMBER, GREEN, RED, determine_rag, variance_status
from .raid import raid_log, raid_summary
from .types import Milestone, Project, RaidItem

ICON = {GREEN: "🟢", AMBER: "🟠", RED: "🔴"}


def _signed(v: str | None) -> str:
    if v is None:
        return "n/a"
    return v if v.startswith("-") else f"+{v}"


def build_status_report(project: Project, milestones: list[Milestone],
                        raid_items: list[RaidItem], as_of: date) -> dict:
    evm = compute_evm(project.bac, project.pv, project.ev, project.ac, project.elapsed_days)
    e = evm.as_dict()
    rag = determine_rag(evm, raid_items)
    mh = milestone_health(milestones, as_of, project.milestone_target_pct)
    rs = raid_summary(raid_items)
    log = raid_log(raid_items)

    spi_delta = None if evm.spi is None else str((evm.spi - 1).quantize(Decimal("0.01")))
    cpi_delta = None if evm.cpi is None else str((evm.cpi - 1).quantize(Decimal("0.01")))
    blockers = rs["open_critical_blockers"]

    kpis = [
        {"kpi": "Schedule Performance Index (SPI)", "target": "1.00", "actual": e["spi"],
         "variance": _signed(spi_delta), "status": variance_status(evm.sv_pct),
         "explanation": {**e["explanation"]["spi"], "status_rule":
                         f"Status from SV% {e['sv_pct']}: adverse > 15% RED, > 5% AMBER, else GREEN"}},
        {"kpi": "Cost Performance Index (CPI)", "target": "1.00", "actual": e["cpi"],
         "variance": _signed(cpi_delta), "status": variance_status(evm.cv_pct),
         "explanation": {**e["explanation"]["cpi"], "status_rule":
                         f"Status from CV% {e['cv_pct']}: adverse > 15% RED, > 5% AMBER, else GREEN"}},
        {"kpi": "Milestone Completion Rate", "target": f"{mh['target_pct']}%",
         "actual": None if mh["completion_rate_pct"] is None else f"{mh['completion_rate_pct']}%",
         "variance": None if mh["completion_variance_pts"] is None
         else f"{_signed(mh['completion_variance_pts'])} pts",
         "status": mh["completion_status"], "explanation": mh["explanation"]},
        {"kpi": "Open Critical Blockers", "target": "0", "actual": str(blockers),
         "variance": "Requires escalation" if blockers else "None",
         "status": RED if blockers else GREEN,
         "explanation": explain("Open critical blockers = open ISSUE items flagged blocker; any > 0 is RED",
                                {"blocker_ids": [i.id for i in raid_items
                                                 if i.is_open and i.type == "ISSUE" and i.blocker]},
                                f"{blockers} open critical blocker(s): {'RED' if blockers else 'GREEN'}.")},
    ]

    intervention = [
        {"id": r["id"], "description": r["description"], "owner": r["owner"],
         "why": "Critical-path blocker" if r["critical_path"] else
                "Critical blocker" if r["blocker"] else
                f"{r['score_label']} risk - escalate to sponsor"}
        for r in log
        if r["blocker"] or (r["band"] == "HIGH" and not r["mitigated"])
    ]

    report = {
        "project_id": project.id,
        "title": f"Executive Status Report: {project.name}",
        "program": project.program,
        "sponsor": project.sponsor,
        "delivery_lead": project.delivery_lead,
        "reporting_period": as_of.isoformat(),
        "overall_rag": rag["status"],
        "rag_reasons": rag["reasons"],
        "rag_explanation": rag["explanation"],
        "executive_intervention_required": rag["executive_intervention_required"],
        "evm": e,
        "kpis": kpis,
        "key_accomplishments": list(project.accomplishments),
        "upcoming_milestones": mh["upcoming"],
        "overdue_milestones": mh["overdue"],
        "blockers_requiring_intervention": intervention,
        "top_risks": [r for r in log if r["score"] is not None][:5],
        "raid_summary": rs,
    }
    report["executive_summary"] = deterministic_summary(report)
    report["summary_source"] = "deterministic"
    return report


def deterministic_summary(r: dict) -> str:
    e = r["evm"]
    name = r["title"].replace("Executive Status Report: ", "")
    s = [f"{name} is at {r['overall_rag']} status."]
    if r["rag_reasons"]:
        s.append("Drivers: " + "; ".join(x["message"] for x in r["rag_reasons"][:3]) + ".")
    else:
        s.append("Schedule and cost are within the 5% tolerance and no critical blockers are open.")
    s.append(f"SPI is {e['spi']} and CPI is {e['cpi']}"
             + (f"; schedule variance is {e['sv_days']} days against baseline." if e["sv_days"] else "."))
    if r["blockers_requiring_intervention"]:
        n = len(r["blockers_requiring_intervention"])
        s.append(f"{n} item{'s' if n != 1 else ''} need{'s' if n == 1 else ''} executive attention.")
    return " ".join(s)


# --- narrative grounding guard ----------------------------------------------

_NUM = re.compile(r"(?<![A-Za-z])-?\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    out = set()
    for tok in _NUM.findall(text):
        t = tok.replace(",", "").lstrip("-")
        try:
            out.add(str(Decimal(t).normalize()))
        except Exception:
            pass
    return out


def narrative_is_grounded(narrative: str, facts: dict) -> tuple[bool, list[str]]:
    """True if every number in the narrative already appears in the facts.

    Identifiers like 'R-101' or 'Sprint 12' count as facts only if they appear
    in the facts too, so the model cannot invent a sprint or a risk ID.
    """
    import json
    allowed = _numbers(json.dumps(facts, default=str))
    found = _numbers(narrative)
    unknown = sorted(found - allowed)
    return (not unknown, unknown)


# --- Markdown rendering -----------------------------------------------------

def _money(v: str | None) -> str:
    if v is None:
        return "n/a"
    d = Decimal(v)
    return f"-${abs(d):,.2f}" if d < 0 else f"${d:,.2f}"


def render_markdown(r: dict) -> str:
    L = []
    L.append(f"# {r['title']}")
    L.append("")
    L.append(f"**Reporting Period:** {r['reporting_period']}  ")
    L.append(f"**Program:** {r['program']} · **Sponsor:** {r['sponsor']} · "
             f"**Delivery Lead:** {r['delivery_lead']}  ")
    L.append(f"**Overall RAG Status:** {ICON[r['overall_rag']]} **{r['overall_rag']}**")
    L.append("")
    callout = {"RED": "CAUTION", "AMBER": "WARNING", "GREEN": "NOTE"}[r["overall_rag"]]
    L.append(f"> [!{callout}]")
    L.append(f"> {r['executive_summary']}")
    L.append("")
    L.append("## Key Performance Indicators")
    L.append("")
    L.append("| KPI Metric | Target | Actual | Variance / Status |")
    L.append("|---|---|---|---|")
    for k in r["kpis"]:
        L.append(f"| {k['kpi']} | {k['target']} | {k['actual'] or 'n/a'} | "
                 f"{ICON[k['status']]} {k['status'].title()} ({k['variance']}) |")
    L.append("")
    L.append("## Key Accomplishments")
    L.append("")
    L.extend([f"- {a}" for a in r["key_accomplishments"]] or ["- None reported this period."])
    L.append("")
    L.append("## Upcoming Milestones (next 30 days)")
    L.append("")
    if r["upcoming_milestones"]:
        L.append("| Milestone | Baseline | Forecast | Critical Path | Owner |")
        L.append("|---|---|---|---|---|")
        for m in r["upcoming_milestones"]:
            L.append(f"| {m['name']} | {m['baseline_date']} | {m['forecast_date']} | "
                     f"{'Yes' if m['critical_path'] else 'No'} | {m['owner']} |")
    else:
        L.append("None in the next 30 days.")
    L.append("")
    L.append("## Blockers Requiring Intervention")
    L.append("")
    if r["blockers_requiring_intervention"]:
        L.append("> [!IMPORTANT]")
        for b in r["blockers_requiring_intervention"]:
            L.append(f"> **{b['id']}** — {b['description']} *(Owner: {b['owner'] or 'UNASSIGNED'}; "
                     f"{b['why']})*  ")
    else:
        L.append("None.")
    L.append("")
    L.append("## RAID Log — Top Exposures")
    L.append("")
    L.append("| Risk ID | Category | Description | Prob | Imp | Score | Mitigation Strategy | Owner | Status |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for x in r["top_risks"]:
        L.append(f"| {x['id']} | {x['category']} | {x['description']} | {x['probability']} | "
                 f"{x['impact']} | **{x['score_label']}** | {x['mitigation'] or '—'} | "
                 f"{x['owner'] or '—'} | {x['status'].title()} |")
    L.append("")
    L.append("## Earned Value Detail")
    L.append("")
    e = r["evm"]
    L.append("| BAC | PV | EV | AC | SV | CV | EAC | VAC |")
    L.append("|---|---|---|---|---|---|---|---|")
    L.append("| " + " | ".join(_money(e[k]) for k in ("bac", "pv", "ev", "ac", "sv", "cv", "eac", "vac"))
             + " |")
    L.append("")
    L.append(f"*All figures computed by deterministic engines. Summary source: {r['summary_source']}.*")
    return "\n".join(L) + "\n"
