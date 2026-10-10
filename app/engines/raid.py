"""RAID log scoring and summarisation (Risks, Assumptions, Issues, Dependencies)."""
from __future__ import annotations

from .explain import explain
from .risk import HIGH, LOW, MEDIUM, score_risk
from .types import ISSUE, RAID_STATUSES, RAID_TYPES, RISK, RaidItem


class RaidInputError(ValueError):
    pass


def validate_item(item: RaidItem) -> None:
    if item.type not in RAID_TYPES:
        raise RaidInputError(f"type must be one of {RAID_TYPES}")
    if item.status not in RAID_STATUSES:
        raise RaidInputError(f"status must be one of {RAID_STATUSES}")
    if item.type == RISK and (item.probability is None or item.impact is None):
        raise RaidInputError("A RISK needs both probability and impact (1-5)")
    if item.type == ISSUE and item.impact is None:
        raise RaidInputError("An ISSUE needs an impact (1-5); its probability is fixed at 5")
    if item.type != ISSUE and (item.blocker or item.critical_path):
        raise RaidInputError("blocker / critical_path flags apply to ISSUE items only")
    if item.critical_path and not item.blocker:
        raise RaidInputError("critical_path requires blocker=true")


def score_item(item: RaidItem) -> dict:
    """Return the item as a dict with its computed exposure score (if scorable)."""
    validate_item(item)
    p = item.effective_probability
    scored = score_risk(p, item.impact) if (p is not None and item.impact is not None) else None
    if scored:
        ex = scored.explanation()
        if item.type == ISSUE:
            ex["inputs"]["probability_basis"] = "fixed at 5: an issue has already happened"
            ex["reasoning"] = "Issue, so probability is fixed at 5. " + ex["reasoning"]
        ex["inputs"]["mitigation_plan"] = bool(item.mitigation.strip())
        ex["inputs"]["owner"] = item.owner or None
        ex["reasoning"] += (" Mitigated: it has both a mitigation plan and a named owner."
                            if item.is_mitigated else
                            " Not mitigated: it needs both a mitigation plan and a named owner.")
    else:
        ex = explain("Risk Exposure = Probability (1-5) x Impact (1-5)",
                     {"probability": p, "impact": item.impact},
                     f"Not scored: this {item.type.lower()} has no probability/impact recorded, "
                     "so it carries no exposure score and cannot change RAG status.")
    return {
        "id": item.id,
        "project_id": item.project_id,
        "type": item.type,
        "category": item.category,
        "description": item.description,
        "probability": p,
        "impact": item.impact,
        "score": scored.score if scored else None,
        "band": scored.band if scored else None,
        "score_label": scored.label if scored else None,
        "required_action": scored.action if scored else None,
        "review_interval_days": scored.review_interval_days if scored else None,
        "escalate_to_sponsor": scored.escalate_to_sponsor if scored else False,
        "mitigation": item.mitigation,
        "owner": item.owner,
        "status": item.status,
        "mitigated": item.is_mitigated,
        "blocker": item.blocker,
        "critical_path": item.critical_path,
        "explanation": ex,
    }


def raid_log(items: list[RaidItem], include_closed: bool = False) -> list[dict]:
    """Scored RAID log, highest exposure first, then by id for a stable order."""
    rows = [score_item(i) for i in items if include_closed or i.is_open]
    rows.sort(key=lambda r: (-(r["score"] or 0), r["id"]))
    return rows


def raid_summary(items: list[RaidItem]) -> dict:
    open_items = [i for i in items if i.is_open]
    scored = [score_item(i) for i in open_items]
    by_band = {HIGH: 0, MEDIUM: 0, LOW: 0}
    for r in scored:
        if r["band"]:
            by_band[r["band"]] += 1
    return {
        "open_items": len(open_items),
        "by_type": {t: sum(1 for i in open_items if i.type == t) for t in RAID_TYPES},
        "by_band": by_band,
        "unmitigated_high": sum(1 for r in scored if r["band"] == HIGH and not r["mitigated"]),
        "unmitigated_medium": sum(1 for r in scored if r["band"] == MEDIUM and not r["mitigated"]),
        "open_critical_blockers": sum(1 for i in open_items if i.type == ISSUE and i.blocker),
        "critical_path_blocked": any(i.type == ISSUE and i.critical_path for i in open_items),
        "escalations_required": [r["id"] for r in scored if r["escalate_to_sponsor"]],
    }


__all__ = ["raid_log", "raid_summary", "score_item", "validate_item", "RaidInputError", "LOW"]
