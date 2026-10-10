"""Project Management & Delivery Agent -- FastAPI service."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import actions, agent, config, governance, repository
from .db import Base, SessionLocal, engine, get_session
from .engines.evm import EVMInputError, compute_evm
from .engines.raid import RaidInputError, score_item
from .engines.report import render_markdown
from .engines.risk import RiskInputError, score_risk
from .engines.types import RaidItem
from .models import AICallRow, AIReviewRow, AuditRow, RaidRow
from .seed import seed

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed(s)
    yield


app = FastAPI(
    title="Project Management & Delivery Agent",
    version="1.0.0",
    description=("PMO agent for multi-stream delivery: RAID scoring, earned value, RAG status, "
                 "executive reports, resource and dependency analysis. Every number comes from "
                 "a deterministic engine; Claude orchestrates and explains. Fictional demo data."),
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class RequestSizeLimit:
    """Reject any request body over MAX_REQUEST_BYTES with 413, whether or not
    the client sends Content-Length (streamed bodies are counted as they arrive)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = config.MAX_REQUEST_BYTES
        headers = dict(scope.get("headers") or [])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            return await self._reject(send, limit)

        seen = 0

        async def counted():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise _TooLarge()
            return msg

        started = False

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, counted, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send, limit)

    @staticmethod
    async def _reject(send, limit):
        resp = JSONResponse({"detail": f"Request body exceeds the {limit}-byte limit."}, status_code=413)
        await send({"type": "http.response.start", "status": 413, "headers": resp.raw_headers})
        await send({"type": "http.response.body", "body": resp.body})


class _TooLarge(Exception):
    pass


app.add_middleware(RequestSizeLimit)


def visitor(request: Request) -> str:
    return governance.visitor_id(
        governance.client_address(request.headers, request.client.host if request.client else None))


def _gov_http(exc: governance.GovernanceError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return HTTPException(exc.status_code, str(exc), headers=headers)


def _404(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except repository.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


# --- request models ---------------------------------------------------------

class RiskScoreIn(BaseModel):
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)


class EVMIn(BaseModel):
    bac: str = Field(description="Budget at completion, e.g. '2000000'")
    pv: str
    ev: str
    ac: str
    elapsed_days: int | None = Field(default=None, ge=0)


class RaidIn(BaseModel):
    type: Literal["RISK", "ASSUMPTION", "ISSUE", "DEPENDENCY"]
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=3, max_length=2000)
    probability: int | None = Field(default=None, ge=1, le=5)
    impact: int | None = Field(default=None, ge=1, le=5)
    mitigation: str = ""
    owner: str = ""
    status: Literal["OPEN", "MONITORING", "CLOSED"] = "OPEN"
    blocker: bool = False
    critical_path: bool = False


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=config.MAX_QUESTION_CHARS)
    requested_by: str = Field(default="", max_length=120)


class ProposeIn(BaseModel):
    action_type: Literal["POST_SLACK_DIGEST", "CREATE_JIRA_ISSUE"]
    project_id: str | None = None
    payload: dict = Field(default_factory=dict)
    requested_by: str = Field(min_length=1, max_length=60)


class DecisionIn(BaseModel):
    approve: bool
    decided_by: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=2000)


class ReviewDecisionIn(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    reviewer: str = Field(min_length=1, max_length=120)
    edited_output: str | None = Field(default=None, max_length=20000)
    reason: str | None = Field(default=None, max_length=2000)


class KillSwitchIn(BaseModel):
    engaged: bool
    actor: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=3, max_length=500)


# --- routes -----------------------------------------------------------------

@app.get("/", include_in_schema=False)
def console():
    return FileResponse(STATIC / "index.html")


@app.get("/governance", include_in_schema=False)
def governance_page():
    return FileResponse(STATIC / "governance.html")


@app.get("/health")
def health(s: Session = Depends(get_session)):
    ks = governance.kill_switch_state(s)
    return {"status": "ok", "status_date": config.STATUS_DATE.isoformat(),
            "agent_enabled": bool(config.ANTHROPIC_API_KEY) and not ks["engaged"],
            "api_key_configured": bool(config.ANTHROPIC_API_KEY),
            "kill_switch_engaged": ks["engaged"], "model": config.ANTHROPIC_MODEL}


@app.get("/api/portfolio", tags=["Portfolio"])
def get_portfolio(s: Session = Depends(get_session)):
    return repository.portfolio(s)


@app.get("/api/projects/{project_id}/rag", tags=["Portfolio"])
def get_rag(project_id: str, s: Session = Depends(get_session)):
    return _404(repository.project_rag, s, project_id)


@app.get("/api/projects/{project_id}/evm", tags=["Milestone health"])
def get_evm(project_id: str, s: Session = Depends(get_session)):
    return _404(repository.project_evm, s, project_id)


@app.post("/api/evm/calculate", tags=["Milestone health"])
def calc_evm(body: EVMIn):
    """What-if earned value calculation for any figures (nothing is stored)."""
    try:
        return compute_evm(body.bac, body.pv, body.ev, body.ac, body.elapsed_days).as_dict()
    except EVMInputError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/projects/{project_id}/milestones", tags=["Milestone health"])
def get_milestones(project_id: str, as_of: date | None = None, s: Session = Depends(get_session)):
    return _404(repository.project_milestones, s, project_id, as_of)


@app.get("/api/raid", tags=["RAID"])
def get_raid(project_id: str | None = None, include_closed: bool = False,
             s: Session = Depends(get_session)):
    return _404(repository.project_raid, s, project_id, include_closed)


@app.post("/api/projects/{project_id}/raid", status_code=201, tags=["RAID"])
def add_raid(project_id: str, body: RaidIn, s: Session = Depends(get_session)):
    """Add a RAID item. The exposure score is always computed by the server."""
    _404(repository.get_project, s, project_id)
    prefix = body.type[0]
    nums = [int(m.group(1)) for (rid,) in s.query(RaidRow.id)
            if (m := re.match(r"^[A-Z]-(\d+)$", rid))]
    new_id = f"{prefix}-{max(nums, default=0) + 1:03d}"
    item = RaidItem(id=new_id, project_id=project_id, **body.model_dump())
    try:
        scored = score_item(item)
    except (RaidInputError, RiskInputError) as exc:
        raise HTTPException(422, str(exc)) from exc
    s.add(RaidRow(id=new_id, project_id=project_id, **body.model_dump()))
    actions.audit(s, "api", "RAID_ITEM_ADDED", {"id": new_id, "project_id": project_id})
    s.commit()
    return scored


@app.post("/api/risk/score", tags=["RAID"])
def post_score(body: RiskScoreIn):
    return score_risk(body.probability, body.impact).as_dict()


@app.get("/api/projects/{project_id}/status-report", tags=["Executive reporting"])
def get_report(project_id: str, format: Literal["json", "markdown"] = "json",
               narrative: bool = Query(False, description="Ask Claude to DRAFT the summary. The draft "
                                       "is queued PENDING_REVIEW; the report keeps the "
                                       "deterministic summary."),
               narrative_review: int | None = Query(None, description="Use this Claude draft as the "
                                                    "summary. Refused (409) unless a human approved it."),
               s: Session = Depends(get_session), who: str = Depends(visitor)):
    report = _404(repository.status_report, s, project_id)
    if narrative_review is not None:
        row = s.get(AIReviewRow, narrative_review)
        if row is None or row.kind != "REPORT_NARRATIVE" or row.project_id != project_id:
            raise HTTPException(404, f"No report narrative {narrative_review} for {project_id}")
        try:
            text = governance.published_text(row)
        except governance.ReviewError as exc:
            raise _gov_http(exc) from exc
        report = {**report, "executive_summary": text,
                  "summary_source": f"Claude draft #{row.id}, {row.status.replace('_', ' ').lower()} "
                                    f"by {row.reviewer} (human-validated)"}
    elif narrative:
        try:
            report = agent.narrate_summary(report, s=s, visitor=who)
        except governance.AIBlocked as exc:
            report["summary_source"] = f"deterministic (AI draft refused: {exc})"
        except (agent.AgentUnavailable, agent.AgentError) as exc:
            report["summary_source"] = f"deterministic ({exc})"
    if format == "markdown":
        return PlainTextResponse(render_markdown(report), media_type="text/markdown")
    return report


@app.get("/api/resources", tags=["Resource optimisation"])
def get_resources(s: Session = Depends(get_session)):
    return repository.resources(s)


@app.get("/api/dependencies", tags=["Dependencies"])
def get_dependencies(s: Session = Depends(get_session)):
    return repository.dependencies(s)


@app.post("/api/agent/ask", tags=["Agent"])
def ask_agent(body: AskIn, s: Session = Depends(get_session), who: str = Depends(visitor)):
    """Returns a DRAFT answer stored PENDING_REVIEW. It is published only after a named
    human approves, edits or rejects it via /api/reviews/{id}/decision."""
    try:
        return agent.ask(s, body.question, visitor=who, requested_by=body.requested_by)
    except governance.AIBlocked as exc:
        raise _gov_http(exc) from exc
    except agent.AgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except agent.AgentError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/actions", status_code=201, tags=["Approvals"])
def propose_action(body: ProposeIn, s: Session = Depends(get_session)):
    payload = dict(body.payload)
    if body.action_type == "POST_SLACK_DIGEST" and body.project_id and "markdown" not in payload:
        report = _404(repository.status_report, s, body.project_id)
        payload = {"title": report["title"], "markdown": render_markdown(report)}
    try:
        return actions.propose(s, body.action_type, payload, body.requested_by, body.project_id)
    except actions.ActionError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/actions", tags=["Approvals"])
def get_actions(status: str | None = None, s: Session = Depends(get_session)):
    return actions.list_actions(s, status)


@app.post("/api/actions/{action_id}/decision", tags=["Approvals"])
def decide_action(action_id: int, body: DecisionIn, s: Session = Depends(get_session)):
    try:
        return actions.decide(s, action_id, body.approve, body.decided_by, body.reason)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except actions.ActionError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/audit", tags=["Approvals"])
def get_audit(limit: int = Query(50, ge=1, le=500), s: Session = Depends(get_session)):
    rows = s.query(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
    return [{"id": r.id, "at": r.at.isoformat(), "actor": r.actor, "event": r.event,
             "detail": r.detail} for r in rows]


# --- human review gate for AI output ---------------------------------------------

@app.get("/api/reviews", tags=["Human review"])
def get_reviews(status: str | None = None, limit: int = Query(50, ge=1, le=200),
                s: Session = Depends(get_session)):
    return governance.list_reviews(s, status, limit)


@app.get("/api/reviews/{review_id}", tags=["Human review"])
def get_review(review_id: int, s: Session = Depends(get_session)):
    row = s.get(AIReviewRow, review_id)
    if row is None:
        raise HTTPException(404, f"No AI output {review_id}")
    return governance.review_dict(row)


@app.post("/api/reviews/{review_id}/decision", tags=["Human review"])
def decide_review(review_id: int, body: ReviewDecisionIn, s: Session = Depends(get_session),
                  x_reviewer_token: str | None = Header(default=None)):
    """approve | edit (edit-then-approve) | reject (reason required). Decisions are final."""
    try:
        governance.check_reviewer_token(x_reviewer_token)
        return governance.decide_review(s, review_id, body.decision, body.reviewer,
                                        body.edited_output, body.reason)
    except governance.ReviewError as exc:
        raise _gov_http(exc) from exc


@app.get("/api/reviews/{review_id}/published", tags=["Human review"])
def get_published(review_id: int, s: Session = Depends(get_session)):
    """The human-approved text. 409 for anything pending or rejected (fails closed)."""
    row = s.get(AIReviewRow, review_id)
    try:
        text = governance.published_text(row)
    except governance.ReviewError as exc:
        raise _gov_http(exc) from exc
    return {"id": row.id, "status": row.status, "text": text, "reviewer": row.reviewer,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None}


# --- AI call log and governance scorecard ------------------------------------------

@app.get("/api/ai-calls", tags=["Governance"])
def get_ai_calls(limit: int = Query(50, ge=1, le=500), s: Session = Depends(get_session)):
    rows = s.query(AICallRow).order_by(AICallRow.id.desc()).limit(limit)
    return [governance.ai_call_dict(r) for r in rows]


@app.get("/api/governance", tags=["Governance"])
def get_governance(s: Session = Depends(get_session), who: str = Depends(visitor)):
    ks = governance.kill_switch_state(s)
    u = governance.usage(s, who)
    outcomes = dict(s.query(AICallRow.outcome, func.count(AICallRow.id)).group_by(AICallRow.outcome).all())
    return {
        "model_card": {
            "provider": "Anthropic",
            "model": config.ANTHROPIC_MODEL,
            "role": "Orchestrator and explainer. Chooses which deterministic engine to call and "
                    "explains the result in plain English.",
            "not_used_for": ["Calculating any figure (SPI, CPI, risk scores, RAG, utilisation)",
                             "Changing project data", "Sending anything outside the service",
                             "Approving its own output or any outbound action"],
            "tools": [t["name"] for t in agent.TOOLS],
            "tool_permissions": "Read-only engine tools, plus propose_slack_digest which only "
                                "queues a request for a named human to approve.",
            "safeguards": ["Numeric grounding check on every output",
                           "Every output PENDING_REVIEW until a named human decides",
                           "Ungrounded output cannot be approved unchanged",
                           "Every AI call logged: who, when, model, tools, tokens, outcome",
                           "Kill switch and per-visitor limits, all fail closed"],
            "known_limits": ["Explanations can be incomplete or poorly prioritised; the engines' "
                             "explanation fields are the authoritative reasoning",
                             "Grounding checks numbers, not wording: a reviewer must still read it",
                             "Demo portfolio only; not validated on real program data"],
        },
        "data_policy": {
            "data": "Fictional demonstration portfolio. No real people, companies or financials.",
            "sent_to_model": "The question, the system prompt and the engine results the model "
                             "requests. No credentials, no visitor identifiers.",
            "visitor_identity": "Client address is salted and hashed for rate limiting; the raw "
                                "address is not stored.",
            "retention": "Sandbox data is reseeded each time the free instance restarts. Audit, "
                         "AI-call and review records are append-only while it runs.",
            "secrets": "ANTHROPIC_API_KEY is read from the environment only; never logged or returned.",
        },
        "limits": {
            "rate_limit_per_minute_per_visitor": config.RATE_LIMIT_PER_MINUTE,
            "daily_cap_per_visitor": config.DAILY_CAP_PER_VISITOR,
            "daily_cap_global": config.DAILY_CAP_GLOBAL,
            "daily_token_budget": config.DAILY_TOKEN_BUDGET,
            "max_tokens_per_call": config.MAX_TOKENS,
            "narrative_max_tokens": config.NARRATIVE_MAX_TOKENS,
            "max_agent_turns": config.MAX_AGENT_TURNS,
            "max_request_bytes": config.MAX_REQUEST_BYTES,
            "max_question_chars": config.MAX_QUESTION_CHARS,
            "reset": "Daily caps reset 00:00 UTC",
        },
        "kill_switch": {**ks, "runtime_control": "enabled (admin token)" if config.ADMIN_TOKEN
                        else "locked (set ADMIN_TOKEN to enable; AI_ENABLED=false always works)"},
        "human_validation": governance.review_stats(s),
        "usage_today": {**u, "calls_by_outcome_all_time": outcomes},
        "review_gate": {"reviewer_token_required": bool(config.REVIEWER_TOKEN)},
    }


@app.post("/api/governance/kill-switch", tags=["Governance"])
def post_kill_switch(body: KillSwitchIn, s: Session = Depends(get_session),
                     x_admin_token: str | None = Header(default=None)):
    if not config.ADMIN_TOKEN:
        raise HTTPException(403, "Runtime kill switch is locked: set ADMIN_TOKEN, or set "
                                 "AI_ENABLED=false in the environment.")
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Admin token required.")
    if governance.is_ai_identity(body.actor):
        raise HTTPException(403, "The kill switch must be operated by a named human.")
    return governance.set_kill_switch(s, body.engaged, body.actor.strip(), body.reason.strip())
