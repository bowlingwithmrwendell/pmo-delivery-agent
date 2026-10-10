"""Claude as orchestrator -- never as calculator.

Claude reads a plain-English request, chooses which deterministic engine to
call, and explains the result in the PMO voice. It has no tool that writes
the database and no tool that sends anything: outbound actions can only be
PROPOSED, and a named human must approve them.

Guards on every AI call:
  1. Kill switch and limiter run first and fail closed (governance.guard).
  2. Every tool call is written to the audit log, and every AI call is logged
     with who, when, model, tools, tokens and outcome (ai_call_log).
  3. The answer is checked for numbers that did not come from a tool result
     (grounded = false). An ungrounded output cannot be approved as-is.
  4. The answer is a DRAFT stored PENDING_REVIEW. Only a named human can
     approve, edit-then-approve or reject it. The agent has no review tool.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from . import actions, config, governance, repository
from .engines.report import narrative_is_grounded, render_markdown
from .engines.risk import score_risk

SYSTEM_PROMPT = """\
IDENTITY & ROLE:
You are an enterprise Senior Delivery Director and Project Management Office (PMO) Agent
for Agile by Killette. Your mission is to provide objective risk assessment, track milestone
completion, manage cross-project dependencies, balance resource allocations, and produce
clear executive summaries.

GOVERNANCE RULES (non-negotiable):
- You never calculate, estimate, round or invent a number. Every figure you state must come
  from a tool result in this conversation, quoted as returned. If no tool provides a figure,
  say it is not available.
- RAG status, risk exposure scores, SPI/CPI/SV/CV and utilisation come only from the tools.
  Do not re-derive or second-guess them; explain the reasons the tools return.
- You cannot change project data. You cannot send anything. If the user wants a report
  shared, use propose_slack_digest -- it only queues a request that a named human must
  approve. Tell the user it is awaiting approval.
- The data is a fictional demonstration portfolio. Do not present it as real.

COMMUNICATION & FORMATTING:
- Tone: professional, objective, direct, and risk-aware.
- RAG criteria: GREEN = on schedule, cost within 5% tolerance, no critical blockers.
  AMBER = schedule/cost variance 5-15%, or unmitigated medium risks. RED = variance > 15%,
  critical path blocked, or executive intervention required.
- Risk exposure = Probability (1-5) x Impact (1-5). LOW 1-6 monitor monthly; MEDIUM 8-12
  active mitigation, review bi-weekly; HIGH 15-25 escalate to Executive Sponsor, weekly tracking.
- Use clean Markdown tables and short callouts. Lead with the answer.
"""

TOOLS = [
    {"name": "get_portfolio",
     "description": "Program-level view: every project with RAG, SPI, CPI, variance % and top reason.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_project_rag",
     "description": "RAG status for one project with every triggering reason.",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                      "required": ["project_id"]}},
    {"name": "get_evm",
     "description": "Earned value metrics for one project: BAC, PV, EV, AC, SV, CV, SPI, CPI, SV%, CV%, EAC, ETC, VAC, TCPI, SV in days.",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                      "required": ["project_id"]}},
    {"name": "get_raid_log",
     "description": "Scored RAID log (risks, assumptions, issues, dependencies). Omit project_id for the whole program.",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}}}},
    {"name": "score_risk",
     "description": "Score a hypothetical risk: exposure = probability x impact, with band and required action.",
     "input_schema": {"type": "object", "properties": {
         "probability": {"type": "integer", "minimum": 1, "maximum": 5},
         "impact": {"type": "integer", "minimum": 1, "maximum": 5}},
         "required": ["probability", "impact"]}},
    {"name": "get_milestone_health",
     "description": "Milestone completion rate vs target, slipped, overdue and upcoming milestones for one project.",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                      "required": ["project_id"]}},
    {"name": "get_resource_analysis",
     "description": "Utilisation per person across all projects, overallocation, skills gaps and single points of failure.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_dependency_analysis",
     "description": "Cross-project dependencies: conflicts, at-risk items, slip days and circular dependencies.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_status_report",
     "description": "Full executive status report data for one project (RAG, KPIs, accomplishments, milestones, blockers, top risks).",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                      "required": ["project_id"]}},
    {"name": "propose_slack_digest",
     "description": "Queue the executive status report for posting to Slack. Does NOT send it; a named human must approve.",
     "input_schema": {"type": "object", "properties": {"project_id": {"type": "string"}},
                      "required": ["project_id"]}},
]


def run_tool(s: Session, name: str, args: dict) -> dict:
    pid = args.get("project_id")
    if name == "get_portfolio":
        return repository.portfolio(s)
    if name == "get_project_rag":
        return repository.project_rag(s, pid)
    if name == "get_evm":
        return repository.project_evm(s, pid)
    if name == "get_raid_log":
        return repository.project_raid(s, pid)
    if name == "score_risk":
        return score_risk(args["probability"], args["impact"]).as_dict()
    if name == "get_milestone_health":
        return repository.project_milestones(s, pid)
    if name == "get_resource_analysis":
        return repository.resources(s)
    if name == "get_dependency_analysis":
        return repository.dependencies(s)
    if name == "get_status_report":
        return repository.status_report(s, pid)
    if name == "propose_slack_digest":
        report = repository.status_report(s, pid)
        return actions.propose(s, "POST_SLACK_DIGEST",
                               {"title": report["title"], "markdown": render_markdown(report)},
                               requested_by="agent", project_id=pid)
    raise ValueError(f"Unknown tool {name}")


class AgentUnavailable(RuntimeError):
    pass


def _client():
    if not config.ANTHROPIC_API_KEY:
        raise AgentUnavailable("ANTHROPIC_API_KEY is not configured; the deterministic API "
                               "endpoints still work.")
    from anthropic import Anthropic
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


class AgentError(RuntimeError):
    pass


def _usage(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    return (int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0))


def ask(s: Session, question: str, max_turns: int | None = None, client=None,
        visitor: str = "local", requested_by: str = "") -> dict:
    """Answer a question. The answer is a DRAFT: it is stored PENDING_REVIEW and
    is only published after a named human approves it."""
    kind = "AGENT_ASK"
    question = question[:config.MAX_QUESTION_CHARS]
    governance.guard(s, visitor, kind, requested_by)          # kill switch + limiter, fail closed
    try:
        client = client or _client()
    except AgentUnavailable as exc:
        governance.log_ai_call(s, visitor=visitor, requested_by=requested_by, kind=kind,
                               model=config.ANTHROPIC_MODEL, tools=[], model_calls=0,
                               input_tokens=0, output_tokens=0, outcome="UNAVAILABLE", detail=str(exc))
        s.commit()
        raise

    max_turns = max_turns or config.MAX_AGENT_TURNS
    messages = [{"role": "user", "content": question}]
    tool_trace: list[dict] = []
    facts: list = []
    tin = tout = calls = 0

    def log(outcome, detail="", review_id=None):
        governance.log_ai_call(s, visitor=visitor, requested_by=requested_by, kind=kind,
                               model=config.ANTHROPIC_MODEL, tools=[t["tool"] for t in tool_trace],
                               model_calls=calls, input_tokens=tin, output_tokens=tout,
                               outcome=outcome, detail=detail, review_id=review_id)

    try:
        answer = None
        for _ in range(max_turns):
            resp = client.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=config.MAX_TOKENS,
                                          system=SYSTEM_PROMPT, tools=TOOLS, messages=messages)
            calls += 1
            i, o = _usage(resp)
            tin, tout = tin + i, tout + o
            if resp.stop_reason != "tool_use":
                answer = "".join(b.text for b in resp.content if b.type == "text").strip()
                break

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = run_tool(s, block.name, dict(block.input))
                    is_error = False
                except Exception as exc:  # surfaced to the model, never swallowed silently
                    out = {"error": str(exc)}
                    is_error = True
                facts.append(out)
                tool_trace.append({"tool": block.name, "input": dict(block.input), "error": is_error})
                actions.audit(s, "agent", "TOOL_CALL",
                              {"tool": block.name, "input": dict(block.input), "error": is_error})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, default=str), "is_error": is_error})
            messages.append({"role": "user", "content": results})
    except Exception as exc:
        s.rollback()
        log("ERROR", f"{type(exc).__name__}: {exc}")
        s.commit()
        raise AgentError("The model call failed; nothing was published.") from exc

    if answer is None:
        answer = "Stopped: the request needed more tool steps than allowed."
        grounded, unknown = True, []
    else:
        grounded, unknown = narrative_is_grounded(answer, {"question": question, "facts": facts})

    review = governance.create_review(
        s, kind=kind, prompt=question, ai_output=answer, model=config.ANTHROPIC_MODEL,
        tools_used=[t["tool"] for t in tool_trace], grounded=grounded, unverified_numbers=unknown,
        requested_by=requested_by, visitor=visitor)
    log("OK", "answer stored PENDING_REVIEW", review.id)
    s.commit()
    return {"review_id": review.id, "status": review.status, "validated": False,
            "draft_answer": answer, "tools_used": tool_trace, "grounded": grounded,
            "unverified_numbers": unknown, "model": config.ANTHROPIC_MODEL,
            "usage": {"model_calls": calls, "input_tokens": tin, "output_tokens": tout},
            "notice": "Draft only. This AI output is PENDING_REVIEW and is not published until a "
                      "named human approves, edits or rejects it."}


def narrate_summary(report: dict, client=None, s: Session | None = None,
                    visitor: str = "local", requested_by: str = "") -> dict:
    """Ask Claude to draft the executive summary.

    The draft is NEVER placed in the report directly. It is queued
    PENDING_REVIEW; the report keeps the deterministic summary until a human
    approves the draft (see GET status-report?narrative_review=<id>).
    """
    kind = "REPORT_NARRATIVE"
    own = s is None
    if own:
        from .db import SessionLocal
        s = SessionLocal()
    try:
        governance.guard(s, visitor, kind, requested_by)
        try:
            client = client or _client()
        except AgentUnavailable as exc:
            governance.log_ai_call(s, visitor=visitor, requested_by=requested_by, kind=kind,
                                   model=config.ANTHROPIC_MODEL, tools=[], model_calls=0,
                                   input_tokens=0, output_tokens=0, outcome="UNAVAILABLE",
                                   detail=str(exc))
            s.commit()
            raise
        facts = {k: report[k] for k in ("title", "overall_rag", "rag_reasons", "kpis", "evm",
                                        "key_accomplishments", "upcoming_milestones",
                                        "blockers_requiring_intervention")}
        prompt = ("Write a 3-4 sentence executive summary for this status report. Use only numbers "
                  "that appear in the JSON, exactly as written. No headings.\n\n"
                  + json.dumps(facts, default=str))
        try:
            resp = client.messages.create(model=config.ANTHROPIC_MODEL,
                                          max_tokens=config.NARRATIVE_MAX_TOKENS,
                                          system=SYSTEM_PROMPT,
                                          messages=[{"role": "user", "content": prompt}])
        except Exception as exc:
            governance.log_ai_call(s, visitor=visitor, requested_by=requested_by, kind=kind,
                                   model=config.ANTHROPIC_MODEL, tools=[], model_calls=1,
                                   input_tokens=0, output_tokens=0, outcome="ERROR",
                                   detail=f"{type(exc).__name__}: {exc}")
            s.commit()
            raise AgentError("The model call failed; the deterministic summary is used.") from exc
        tin, tout = _usage(resp)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        ok, unknown = narrative_is_grounded(text, facts)
        review = governance.create_review(
            s, kind=kind, prompt=f"Executive summary for {report['project_id']}", ai_output=text,
            model=config.ANTHROPIC_MODEL, tools_used=[], grounded=ok and bool(text),
            unverified_numbers=unknown, requested_by=requested_by, visitor=visitor,
            project_id=report["project_id"])
        governance.log_ai_call(s, visitor=visitor, requested_by=requested_by, kind=kind,
                               model=config.ANTHROPIC_MODEL, tools=[], model_calls=1,
                               input_tokens=tin, output_tokens=tout, outcome="OK",
                               detail="narrative stored PENDING_REVIEW", review_id=review.id)
        s.commit()
        note = "" if ok else f"; grounding check failed: unverified numbers {unknown}"
        return {**report,
                "summary_source": f"deterministic (Claude draft #{review.id} awaiting human review{note})",
                "narrative_review": {"id": review.id, "status": review.status, "grounded": ok,
                                     "unverified_numbers": unknown, "draft": text}}
    finally:
        if own:
            s.close()
