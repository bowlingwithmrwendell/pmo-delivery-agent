"""Fictional demo portfolio: the Enterprise Data Platform Migration program.

All people, companies and figures are invented for demonstration. The data is
designed so the four streams land on GREEN, AMBER, RED and AMBER for different,
explainable reasons. Expected values are hand-calculated in tests/.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import (AssignmentRow, DependencyRow, MilestoneRow, PersonRow, ProjectRow,
                     RaidRow, SkillDemandRow)

PROGRAM = "Enterprise Data Platform Migration"
SPONSOR = "Dana Whitfield (CIO)"

d = date.fromisoformat

PROJECTS = [
    dict(id="EDP-INFRA", name="Cloud Infrastructure & Landing Zone", delivery_lead="Priya Natarajan",
         bac="1200000", pv="600000", ev="590000", ac="580000", elapsed_days=60,
         accomplishments=["AWS landing zone and network baseline delivered on schedule",
                          "IAM federation live for all four delivery streams"]),
    dict(id="EDP-MIGR", name="Data Migration & Vendor API Integration", delivery_lead="Grace Liu",
         bac="2000000", pv="1000000", ev="940000", ac="921000", elapsed_days=66,
         accomplishments=["Wave 1 migration complete: 14 source systems moved",
                          "Critical-path security audit closed with zero high-severity findings",
                          "Pilot reconciliation matched 100% of sampled records"]),
    dict(id="EDP-ANLY", name="Analytics & BI Modernization", delivery_lead="Kenji Watanabe",
         bac="800000", pv="400000", ev="320000", ac="400000", elapsed_days=50,
         accomplishments=["Business requirements signed off by three of four business units"]),
    dict(id="EDP-SEC", name="Security & Compliance", delivery_lead="Aisha Okafor",
         bac="500000", pv="250000", ev="255000", ac="245000", elapsed_days=45,
         accomplishments=["Threat model approved by the security review board"]),
]

MILESTONES = [
    # EDP-INFRA: everything due has landed on time
    ("M-101", "EDP-INFRA", "Landing zone baseline", "2026-08-14", "2026-08-14", "2026-08-14", True, "Priya Natarajan"),
    ("M-102", "EDP-INFRA", "Network & IAM federation", "2026-09-11", "2026-09-10", "2026-09-10", True, "Aisha Okafor"),
    ("M-103", "EDP-INFRA", "Production environment ready", "2026-10-23", "2026-10-23", None, True, "Tom Becker"),
    ("M-104", "EDP-INFRA", "DR failover test", "2026-12-04", "2026-12-04", None, False, "Tom Becker"),
    # EDP-MIGR: 4 of 5 due milestones complete (80%); vendor API slipping
    ("M-201", "EDP-MIGR", "Source system inventory", "2026-07-17", "2026-07-17", "2026-07-17", False, "Grace Liu"),
    ("M-202", "EDP-MIGR", "Data mapping specification", "2026-08-07", "2026-08-10", "2026-08-10", True, "Sofia Ramirez"),
    ("M-203", "EDP-MIGR", "Pilot migration", "2026-08-28", "2026-08-28", "2026-08-28", True, "Marcus Bell"),
    ("M-204", "EDP-MIGR", "Wave 1 migration", "2026-09-18", "2026-09-25", "2026-09-25", True, "Marcus Bell"),
    ("M-205", "EDP-MIGR", "Vendor API integration complete", "2026-10-02", "2026-10-16", None, True, "Priya Natarajan"),
    ("M-206", "EDP-MIGR", "Wave 2 cutover", "2026-11-06", "2026-11-13", None, True, "Marcus Bell"),
    ("M-207", "EDP-MIGR", "Legacy decommission", "2027-01-29", "2027-01-29", None, False, "Grace Liu"),
    # EDP-ANLY: semantic model overdue, MVP slipping
    ("M-301", "EDP-ANLY", "Requirements sign-off", "2026-07-31", "2026-08-14", "2026-08-14", False, "Kenji Watanabe"),
    ("M-302", "EDP-ANLY", "Enterprise semantic model", "2026-09-04", "2026-10-02", None, True, "Kenji Watanabe"),
    ("M-303", "EDP-ANLY", "Executive dashboard MVP", "2026-10-16", "2026-11-20", None, True, "Kenji Watanabe"),
    # EDP-SEC
    ("M-401", "EDP-SEC", "Threat model approved", "2026-08-21", "2026-08-21", "2026-08-21", False, "Aisha Okafor"),
    ("M-402", "EDP-SEC", "Penetration test complete", "2026-10-30", "2026-10-30", None, True, "Daniel Reyes"),
]

# (id, project, type, category, description, prob, impact, mitigation, owner, status, blocker, crit_path)
RAID = [
    ("R-001", "EDP-INFRA", "RISK", "Cost", "Reserved-instance commitments may exceed forecast usage.",
     2, 2, "Quarterly right-sizing review with FinOps.", "Tom Becker", "MONITORING", False, False),
    ("A-002", "EDP-INFRA", "ASSUMPTION", "Technical", "Existing Direct Connect bandwidth covers migration peaks.",
     2, 3, "Bandwidth test scheduled before Wave 2.", "Priya Natarajan", "OPEN", False, False),

    ("R-101", "EDP-MIGR", "RISK", "Technical", "Third-party API rate limits hit during peak hours.",
     4, 4, "Implement Redis caching layer and backoff retry queues.", "Lead Arch", "OPEN", False, False),
    ("R-102", "EDP-MIGR", "RISK", "Staffing", "Backend Lead departure prior to Phase 2 launch.",
     3, 5, "Initiate knowledge transfer sessions; assign shadow dev.", "Delivery Mgr", "OPEN", False, False),
    ("R-103", "EDP-MIGR", "RISK", "Scope", "Unplanned compliance requirement for EU data.",
     2, 4, "Scope Phase 2 isolation layer; adjust sprint 14 backlog.", "PMO", "MONITORING", False, False),
    ("I-104", "EDP-MIGR", "ISSUE", "Vendor", "Vendor has not issued production API credentials.",
     None, 4, "Escalated to vendor account executive; daily follow-up.", "Grace Liu", "OPEN", True, False),
    ("A-105", "EDP-MIGR", "ASSUMPTION", "Technical", "Vendor supports bulk export endpoints for Wave 2.",
     2, 3, "Confirm in vendor technical review.", "Marcus Bell", "OPEN", False, False),

    ("R-301", "EDP-ANLY", "RISK", "Data", "Finance and Sales disagree on revenue definitions for the semantic model.",
     5, 3, "", "", "OPEN", False, False),
    ("I-302", "EDP-ANLY", "ISSUE", "Governance", "Data warehouse schema sign-off pending from Finance.",
     None, 5, "Request CFO decision at next steering committee.", "Kenji Watanabe", "OPEN", True, True),
    ("R-303", "EDP-ANLY", "RISK", "Staffing", "Only one Power BI developer on the stream.",
     3, 3, "Cross-train data engineer on Power BI.", "Kenji Watanabe", "OPEN", False, False),

    ("R-401", "EDP-SEC", "RISK", "Compliance", "New state privacy law may require additional data-retention controls.",
     3, 3, "", "", "OPEN", False, False),
    ("R-402", "EDP-SEC", "RISK", "Vendor", "Pen-test vendor availability in late October.",
     2, 2, "Secondary vendor on standby.", "Daniel Reyes", "CLOSED", False, False),
]

PEOPLE = [
    ("U1", "Priya Natarajan", "Lead Architect", "40", ["cloud-architecture", "aws", "api-integration"]),
    ("U2", "Marcus Bell", "Backend Lead", "40", ["python", "api-integration", "data-migration"]),
    ("U3", "Sofia Ramirez", "Data Engineer", "40", ["data-migration", "sql", "python", "data-modeling"]),
    ("U4", "Kenji Watanabe", "BI Developer", "40", ["power-bi", "sql", "data-modeling"]),
    ("U5", "Aisha Okafor", "Security Engineer", "40", ["security", "compliance", "iam"]),
    ("U6", "Tom Becker", "DevOps Engineer", "40", ["aws", "terraform", "ci-cd", "iam"]),
    ("U7", "Grace Liu", "Delivery Manager", "40", ["delivery-management", "agile"]),
    ("U8", "Daniel Reyes", "Security Analyst", "40", ["security", "compliance"]),
]

ASSIGNMENTS = [
    ("U1", "EDP-INFRA", "20", "cloud-architecture"),
    ("U1", "EDP-MIGR", "20", "api-integration"),
    ("U1", "EDP-ANLY", "8", "cloud-architecture"),
    ("U2", "EDP-MIGR", "40", "data-migration"),
    ("U3", "EDP-MIGR", "30", "data-migration"),
    ("U3", "EDP-ANLY", "16", "sql"),
    ("U4", "EDP-ANLY", "32", "power-bi"),
    ("U5", "EDP-SEC", "24", "security"),
    ("U5", "EDP-INFRA", "8", "iam"),
    ("U6", "EDP-INFRA", "16", "terraform"),
    ("U7", "EDP-MIGR", "20", "delivery-management"),
    ("U7", "EDP-ANLY", "20", "delivery-management"),
    ("U8", "EDP-SEC", "20", "security"),
]

DEMANDS = [
    ("EDP-INFRA", "cloud-architecture", "0.5"),
    ("EDP-INFRA", "terraform", "0.5"),
    ("EDP-INFRA", "iam", "0.2"),
    ("EDP-MIGR", "api-integration", "1.0"),
    ("EDP-MIGR", "data-migration", "2.0"),
    ("EDP-MIGR", "delivery-management", "0.5"),
    ("EDP-ANLY", "power-bi", "1.0"),
    ("EDP-ANLY", "sql", "0.5"),
    ("EDP-ANLY", "data-modeling", "0.5"),
    ("EDP-ANLY", "cloud-architecture", "0.2"),
    ("EDP-SEC", "security", "0.6"),
    ("EDP-SEC", "compliance", "0.25"),
]

DEPENDENCIES = [
    ("D-1", "EDP-INFRA", "M-103", "EDP-MIGR", "2026-10-30", "Wave 2 needs the production environment"),
    ("D-2", "EDP-MIGR", "M-206", "EDP-ANLY", "2026-11-06", "Dashboard MVP needs Wave 2 data in the warehouse"),
    ("D-3", "EDP-SEC", "M-402", "EDP-MIGR", "2026-11-02", "Wave 2 go-live requires a clean pen test"),
    ("D-4", "EDP-SEC", "M-401", "EDP-INFRA", "2026-08-28", "Landing zone hardening follows the threat model"),
]


def seed(session: Session, force: bool = False) -> bool:
    """Load the demo portfolio if the database is empty. Returns True if seeded."""
    if session.query(ProjectRow).count() and not force:
        return False
    for p in PROJECTS:
        session.add(ProjectRow(
            id=p["id"], name=p["name"], program=PROGRAM, sponsor=SPONSOR,
            delivery_lead=p["delivery_lead"], bac=Decimal(p["bac"]), pv=Decimal(p["pv"]),
            ev=Decimal(p["ev"]), ac=Decimal(p["ac"]), elapsed_days=p["elapsed_days"],
            milestone_target_pct=Decimal("85"), accomplishments=p["accomplishments"]))
    session.flush()
    for mid, pid, name, bl, fc, act, cp, owner in MILESTONES:
        session.add(MilestoneRow(id=mid, project_id=pid, name=name, baseline_date=d(bl),
                                 forecast_date=d(fc), actual_date=d(act) if act else None,
                                 critical_path=cp, owner=owner))
    for rid, pid, typ, cat, desc, prob, imp, mit, owner, status, blk, cp in RAID:
        session.add(RaidRow(id=rid, project_id=pid, type=typ, category=cat, description=desc,
                            probability=prob, impact=imp, mitigation=mit, owner=owner,
                            status=status, blocker=blk, critical_path=cp))
    for uid, name, role, cap, skills in PEOPLE:
        session.add(PersonRow(id=uid, name=name, role=role, capacity_hours=Decimal(cap), skills=skills))
    session.flush()
    for uid, pid, hrs, skill in ASSIGNMENTS:
        session.add(AssignmentRow(person_id=uid, project_id=pid, hours_per_week=Decimal(hrs), skill=skill))
    for pid, skill, fte in DEMANDS:
        session.add(SkillDemandRow(project_id=pid, skill=skill, fte_needed=Decimal(fte)))
    session.flush()
    for did, prov, mid, cons, need, desc in DEPENDENCIES:
        session.add(DependencyRow(id=did, provider_project_id=prov, provider_milestone_id=mid,
                                  consumer_project_id=cons, needed_by=d(need), description=desc))
    session.commit()
    return True
