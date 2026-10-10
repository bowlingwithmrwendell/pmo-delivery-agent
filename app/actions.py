"""Human-in-the-loop gate for every outbound action.

Nothing leaves this service on its own. The agent (or a user) can only
PROPOSE an action; a named human must approve it before it runs. Rejected
and approved decisions are both written to the audit log.

v1 integrations:
  * POST_SLACK_DIGEST  -- posts the executive report to Slack if SLACK_WEBHOOK_URL
                          is configured; otherwise records a dry run.
  * CREATE_JIRA_ISSUE  -- always a dry run in v1 (records the ticket it would create).
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from . import config
from .models import AuditRow, PendingActionRow

ACTION_TYPES = ("POST_SLACK_DIGEST", "CREATE_JIRA_ISSUE")


class ActionError(ValueError):
    pass


def audit(s: Session, actor: str, event: str, detail: dict) -> None:
    s.add(AuditRow(actor=actor, event=event, detail=detail))


def _as_dict(r: PendingActionRow) -> dict:
    return {"id": r.id, "action_type": r.action_type, "project_id": r.project_id,
            "payload": r.payload, "status": r.status, "requested_by": r.requested_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "result": r.result}


def propose(s: Session, action_type: str, payload: dict, requested_by: str,
            project_id: str | None = None) -> dict:
    if action_type not in ACTION_TYPES:
        raise ActionError(f"action_type must be one of {ACTION_TYPES}")
    row = PendingActionRow(action_type=action_type, payload=payload,
                           requested_by=requested_by, project_id=project_id)
    s.add(row)
    s.flush()
    audit(s, requested_by, "ACTION_PROPOSED", {"action_id": row.id, "type": action_type})
    s.commit()
    return _as_dict(row)


def list_actions(s: Session, status: str | None = None) -> list[dict]:
    q = s.query(PendingActionRow)
    if status:
        q = q.filter(PendingActionRow.status == status)
    return [_as_dict(r) for r in q.order_by(PendingActionRow.id.desc())]


def decide(s: Session, action_id: int, approve: bool, decided_by: str, reason: str = "") -> dict:
    from .governance import is_ai_identity  # local import: governance imports this module
    if not decided_by or not decided_by.strip():
        raise ActionError("decided_by (a named human approver) is required")
    if is_ai_identity(decided_by):
        raise ActionError("An action cannot be approved by the agent, the AI or the system")
    if not approve and len((reason or "").strip()) < 5:
        raise ActionError("A reason (at least 5 characters) is required to reject")
    row = s.get(PendingActionRow, action_id)
    if row is None:
        raise LookupError(f"No action {action_id}")
    if row.status != "PENDING":
        raise ActionError(f"Action {action_id} is already {row.status}")

    row.decided_by = decided_by.strip()
    row.decided_at = datetime.now(timezone.utc)
    if not approve:
        row.status = "REJECTED"
        row.result = f"Rejected by approver; nothing was sent. Reason: {reason.strip()}"
    else:
        row.status = "EXECUTED"
        row.result = _execute(row)
    audit(s, row.decided_by, "ACTION_APPROVED" if approve else "ACTION_REJECTED",
          {"action_id": row.id, "type": row.action_type, "result": row.result})
    s.commit()
    return _as_dict(row)


def _execute(row: PendingActionRow) -> str:
    if row.action_type == "POST_SLACK_DIGEST":
        if not config.SLACK_WEBHOOK_URL:
            return "DRY RUN: SLACK_WEBHOOK_URL not configured; digest recorded but not sent."
        text = row.payload.get("markdown") or row.payload.get("text") or ""
        resp = httpx.post(config.SLACK_WEBHOOK_URL, json={"text": text[:39000]}, timeout=10)
        return f"Posted to Slack (HTTP {resp.status_code})."
    if row.action_type == "CREATE_JIRA_ISSUE":
        return ("DRY RUN: Jira integration is not enabled in v1; ticket recorded: "
                f"{row.payload.get('summary', '(no summary)')}")
    return "Unknown action type; nothing executed."
