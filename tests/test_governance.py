"""AI governance: audit trail, human approval gate, explainability, scorecard, limiter.

Every test uses a scripted fake Claude client, so no API key is needed.
"""
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app import agent, config, governance
from app.models import AICallRow, AIReviewRow, AppendOnlyViolation, AuditRow


# --- fakes -------------------------------------------------------------------------

class FakeClaude:
    """One tool call, then a final answer. Reports token usage like the real SDK."""

    def __init__(self, final_text="EDP-MIGR is AMBER: schedule variance -6.0% and blocker I-104.",
                 tool="get_project_rag", fail=False):
        self.final_text, self.tool, self.fail = final_text, tool, fail
        self.calls, self.kwargs = 0, []
        self.messages = self

    def create(self, **kw):
        self.kwargs.append(kw)
        if self.fail:
            raise RuntimeError("upstream 529 overloaded")
        self.calls += 1
        usage = SimpleNamespace(input_tokens=100 * self.calls, output_tokens=10 * self.calls)
        if self.calls == 1 and self.tool:
            return SimpleNamespace(stop_reason="tool_use", usage=usage, content=[SimpleNamespace(
                type="tool_use", id="t1", name=self.tool, input={"project_id": "EDP-MIGR"})])
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=self.final_text)])


@pytest.fixture()
def fake(monkeypatch):
    f = FakeClaude()
    monkeypatch.setattr(agent, "_client", lambda: f)
    return f


def ask(client, q="Why is migration amber?", ip="203.0.113.7", **extra):
    return client.post("/api/agent/ask", json={"question": q, **extra},
                       headers={"X-Forwarded-For": ip})


@pytest.fixture(autouse=True)
def trust_proxy(monkeypatch):
    # Treat X-Forwarded-For as the client address so tests can act as different visitors.
    monkeypatch.setattr(config, "TRUSTED_PROXY_HOPS", 1)


def decide(client, rid, decision, reviewer="Wendell Killette", **kw):
    return client.post(f"/api/reviews/{rid}/decision",
                       json={"decision": decision, "reviewer": reviewer, **kw})


# =================================================================================
# 1. Audit trail: every AI call logged (who, when, model, tools, tokens, outcome)
# =================================================================================

def test_every_ai_call_is_logged_with_who_when_model_tools_tokens_outcome(client, fake):
    r = ask(client, requested_by="Dana (PMO)").json()
    calls = client.get("/api/ai-calls").json()
    assert len(calls) == 1
    c = calls[0]
    assert c["visitor"] == governance.visitor_id("203.0.113.7")        # who (hashed, not raw IP)
    assert c["requested_by"] == "Dana (PMO)"
    assert c["at"]                                                     # when
    assert c["model"] == config.ANTHROPIC_MODEL                        # model
    assert c["tools"] == ["get_project_rag"]                           # tools
    assert (c["input_tokens"], c["output_tokens"]) == (300, 30)        # 100+200, 10+20
    assert c["model_calls"] == 2
    assert c["outcome"] == "OK" and c["review_id"] == r["review_id"]   # outcome
    assert "203.0.113.7" not in str(calls)                             # raw IP never stored
    events = [e["event"] for e in client.get("/api/audit").json()]
    assert "AI_CALL" in events and "TOOL_CALL" in events and "AI_OUTPUT_PENDING_REVIEW" in events


def test_refused_and_failed_calls_are_logged_too(client, monkeypatch):
    # No API key -> UNAVAILABLE
    assert ask(client).status_code == 503
    # Model error -> ERROR, and nothing reaches the review queue
    monkeypatch.setattr(agent, "_client", lambda: FakeClaude(fail=True))
    assert ask(client).status_code == 502
    outcomes = [c["outcome"] for c in client.get("/api/ai-calls").json()]
    assert outcomes == ["ERROR", "UNAVAILABLE"]
    assert client.get("/api/reviews").json() == []


def test_report_narrative_calls_are_logged(client, monkeypatch):
    class OneShot:
        def __init__(self): self.messages = self
        def create(self, **kw):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=50, output_tokens=20),
                                   content=[SimpleNamespace(type="text", text="AMBER, SPI 0.94.")])
    monkeypatch.setattr(agent, "_client", lambda: OneShot())
    client.get("/api/projects/EDP-MIGR/status-report?narrative=true")
    c = client.get("/api/ai-calls").json()[0]
    assert c["kind"] == "REPORT_NARRATIVE" and c["outcome"] == "OK"
    assert (c["input_tokens"], c["output_tokens"]) == (50, 20)


def test_audit_and_ai_call_logs_are_append_only(session, fake):
    agent.ask(session, "status?", visitor="v-test")
    call = session.query(AICallRow).first()
    call.outcome = "TAMPERED"
    with pytest.raises(AppendOnlyViolation):
        session.flush()
    session.rollback()
    with pytest.raises(AppendOnlyViolation):
        session.delete(session.query(AuditRow).first())
        session.flush()
    session.rollback()


# =================================================================================
# 2. Human approval gate
# =================================================================================

def test_every_ai_output_starts_pending_review_and_is_not_published(client, fake):
    r = ask(client).json()
    assert r["status"] == "PENDING_REVIEW" and r["validated"] is False
    assert "answer" not in r and r["draft_answer"]          # labelled a draft, never "the answer"
    rid = r["review_id"]
    assert client.get(f"/api/reviews/{rid}").json()["status"] == "PENDING_REVIEW"
    assert client.get(f"/api/reviews/{rid}/published").status_code == 409


def test_approve_publishes_the_exact_ai_text(client, fake):
    rid = ask(client).json()["review_id"]
    d = decide(client, rid, "approve").json()
    assert d["status"] == "APPROVED" and d["reviewer"] == "Wendell Killette" and d["validated"]
    pub = client.get(f"/api/reviews/{rid}/published").json()
    assert pub["text"] == fake.final_text and pub["reviewer"] == "Wendell Killette"


def test_edit_then_approve_keeps_the_original_and_publishes_the_edit(client, fake):
    rid = ask(client).json()["review_id"]
    assert decide(client, rid, "edit", edited_output="").status_code == 422
    assert decide(client, rid, "edit", edited_output=fake.final_text).status_code == 422  # no change
    edited = "EDP-MIGR is AMBER because of the vendor credential blocker (I-104)."
    d = decide(client, rid, "edit", edited_output=edited, reason="Lead with the blocker").json()
    assert d["status"] == "APPROVED_WITH_EDITS"
    assert d["ai_output"] == fake.final_text and d["final_output"] == edited
    assert client.get(f"/api/reviews/{rid}/published").json()["text"] == edited


def test_reject_requires_a_reason_and_is_never_published(client, fake):
    rid = ask(client).json()["review_id"]
    assert decide(client, rid, "reject").status_code == 422
    assert decide(client, rid, "reject", reason="no").status_code == 422
    assert client.get(f"/api/reviews/{rid}").json()["status"] == "PENDING_REVIEW"
    d = decide(client, rid, "reject", reason="Misses the cost picture").json()
    assert d["status"] == "REJECTED" and d["reason"] == "Misses the cost picture"
    assert client.get(f"/api/reviews/{rid}/published").status_code == 409


def test_decisions_are_final(client, fake):
    rid = ask(client).json()["review_id"]
    assert decide(client, rid, "reject", reason="Not useful").status_code == 200
    assert decide(client, rid, "approve").status_code == 409
    assert decide(client, rid, "edit", edited_output="something else").status_code == 409


@pytest.mark.parametrize("name", [
    "agent", "Claude", "  CLAUDE ", "claude-sonnet-5-5", "Claude (AI)", "AI reviewer", "system",
    "auto-approver", "PMO Bot", "Anthropic", "assistant", "the model", "api", "x"])
def test_ai_cannot_approve_its_own_work(client, fake, name):
    rid = ask(client).json()["review_id"]
    resp = decide(client, rid, "approve", reviewer=name)
    assert resp.status_code in (403, 422)
    assert client.get(f"/api/reviews/{rid}").json()["status"] == "PENDING_REVIEW"


def test_agent_has_no_tool_that_can_review_or_approve(session):
    names = [t["name"] for t in agent.TOOLS]
    assert not [n for n in names if any(w in n for w in ("approve", "decide", "review", "publish"))]
    with pytest.raises(ValueError):
        agent.run_tool(session, "approve_review", {"review_id": 1})


def test_no_bypass_route_exists():
    from app.main import app
    review_writes = [(r.path, m) for r in app.routes for m in getattr(r, "methods", set())
                     if "/reviews" in r.path and m not in ("GET", "HEAD")]
    assert review_writes == [("/api/reviews/{review_id}/decision", "POST")]
    # create_review cannot be told to start in any other status
    import inspect
    assert "status" not in inspect.signature(governance.create_review).parameters


def test_ungrounded_output_cannot_be_approved_unchanged(client, monkeypatch):
    monkeypatch.setattr(agent, "_client",
                        lambda: FakeClaude("We will recover 37% of the slip by Sprint 14."))
    r = ask(client).json()
    assert r["grounded"] is False
    rid = r["review_id"]
    assert decide(client, rid, "approve").status_code == 422                      # fails closed
    assert decide(client, rid, "edit", edited_output="We will recover 37% soon.").status_code == 422
    ok = decide(client, rid, "edit", edited_output="Recovery depends on clearing blocker I-104.")
    assert ok.json()["status"] == "APPROVED_WITH_EDITS"


def test_report_uses_claude_summary_only_after_human_approval(client, monkeypatch):
    class OneShot:
        def __init__(self): self.messages = self
        def create(self, **kw):
            return SimpleNamespace(content=[SimpleNamespace(type="text",
                                                            text="Migration is AMBER: SPI 0.94.")])
    monkeypatch.setattr(agent, "_client", lambda: OneShot())
    det = client.get("/api/projects/EDP-MIGR/status-report").json()["executive_summary"]
    rep = client.get("/api/projects/EDP-MIGR/status-report?narrative=true").json()
    rid = rep["narrative_review"]["id"]
    assert rep["executive_summary"] == det                      # draft not used
    url = f"/api/projects/EDP-MIGR/status-report?narrative_review={rid}"
    assert client.get(url).status_code == 409                   # pending -> refused
    assert client.get(f"/api/projects/EDP-SEC/status-report?narrative_review={rid}").status_code == 404
    decide(client, rid, "approve")
    after = client.get(url).json()
    assert after["executive_summary"] == "Migration is AMBER: SPI 0.94."
    assert "human-validated" in after["summary_source"] and "Wendell Killette" in after["summary_source"]


def test_publishing_fails_closed_on_any_unexpected_state(session, fake):
    rid = agent.ask(session, "q?", visitor="v1")["review_id"]
    row = session.get(AIReviewRow, rid)
    # Someone forces the status column without a reviewer: still not publishable.
    session.execute(update(AIReviewRow).where(AIReviewRow.id == rid)
                    .values(status="APPROVED", final_output="text"))
    session.commit()
    session.refresh(row)
    with pytest.raises(governance.ReviewError):
        governance.published_text(row)
    for status in ("PENDING_REVIEW", "REJECTED", "approved", "", "UNKNOWN"):
        row.status = status
        with pytest.raises(governance.ReviewError):
            governance.published_text(row)
    session.rollback()


def test_a_concurrent_decision_cannot_overwrite_the_first(session, fake):
    rid = agent.ask(session, "q?", visitor="v1")["review_id"]
    session.get(AIReviewRow, rid)   # loaded as PENDING_REVIEW in this session
    from app.db import SessionLocal
    with SessionLocal() as other:    # another reviewer decides first
        governance.decide_review(other, rid, "reject", "Pat Lee", reason="Out of date")
    with pytest.raises(governance.ReviewError) as e:
        governance.decide_review(session, rid, "approve", "Wendell Killette")
    assert e.value.status_code == 409
    session.expire_all()
    assert session.get(AIReviewRow, rid).status == "REJECTED"


def test_reviewer_token_enforced_when_configured(client, fake, monkeypatch):
    monkeypatch.setattr(config, "REVIEWER_TOKEN", "s3cret")
    rid = ask(client).json()["review_id"]
    assert decide(client, rid, "approve").status_code == 401
    ok = client.post(f"/api/reviews/{rid}/decision", headers={"X-Reviewer-Token": "s3cret"},
                     json={"decision": "approve", "reviewer": "Wendell Killette"})
    assert ok.status_code == 200


def test_outbound_actions_refuse_ai_approvers_and_reasonless_rejection(client):
    aid = client.post("/api/actions", json={"action_type": "CREATE_JIRA_ISSUE", "requested_by": "agent",
                                            "payload": {"summary": "x"}}).json()["id"]
    for who in ("Claude (AI)", "PMO bot", "claude-sonnet-5-5"):
        assert client.post(f"/api/actions/{aid}/decision",
                           json={"approve": True, "decided_by": who}).status_code == 409
    assert client.post(f"/api/actions/{aid}/decision",
                       json={"approve": False, "decided_by": "Wendell"}).status_code == 409
    r = client.post(f"/api/actions/{aid}/decision",
                    json={"approve": False, "decided_by": "Wendell", "reason": "Duplicate ticket"}).json()
    assert r["status"] == "REJECTED" and "Duplicate ticket" in r["result"]


# =================================================================================
# 3. Explainability: every score returns formula, inputs, reasoning
# =================================================================================

def _is_explained(x):
    return (isinstance(x, dict) and x.get("formula") and isinstance(x.get("inputs"), dict)
            and x.get("reasoning"))


SCORE_KEYS = ("score_label", "utilisation_pct", "fte_short", "float_days", "slip_days",
              "completion_rate_pct", "kpi", "severity")


def _walk(node, path="$"):
    """Yield (path, dict) for every dict that carries a score."""
    if isinstance(node, dict):
        if any(k in node for k in SCORE_KEYS) or ("rag" in node and "project_id" in node):
            yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("url", [
    "/api/portfolio", "/api/projects/EDP-ANLY/rag", "/api/projects/EDP-MIGR/evm",
    "/api/projects/EDP-MIGR/milestones", "/api/raid?include_closed=true", "/api/resources",
    "/api/dependencies", "/api/projects/EDP-MIGR/status-report"])
def test_every_score_returns_formula_inputs_and_reasoning(client, url):
    body = client.get(url).json()
    found = list(_walk(body))
    missing = [p for p, d in found if not _is_explained(d.get("explanation"))]
    assert found or "evm" in url or "rag" in url
    assert missing == [], missing
    if "spi" in body:                       # EVM: one explanation per metric
        for k in ("sv", "cv", "spi", "cpi", "sv_pct", "cv_pct", "eac", "etc", "vac", "tcpi", "sv_days"):
            assert _is_explained(body["explanation"][k]), k
    if "reasons" in body:                   # RAG
        assert _is_explained(body["explanation"])


def test_explanations_show_the_actual_arithmetic(client):
    r = client.post("/api/risk/score", json={"probability": 4, "impact": 4}).json()
    assert r["explanation"]["inputs"] == {"probability": 4, "impact": 4}
    assert "4 x 4 = 16" in r["explanation"]["reasoning"] and "HIGH" in r["explanation"]["reasoning"]
    e = client.get("/api/projects/EDP-MIGR/evm").json()["explanation"]
    assert e["spi"]["reasoning"].startswith("940000.00 / 1000000.00 = 0.94")
    rag = client.get("/api/projects/EDP-MIGR/rag").json()["explanation"]
    assert rag["inputs"]["sv_pct"] == "-6.0" and "AMBER" in rag["reasoning"]
    u = {x["person_id"]: x for x in client.get("/api/resources").json()["utilisation"]}
    assert "48.00 / 40.00 x 100 = 120.0%" in u["U1"]["explanation"]["reasoning"]
    issue = next(i for i in client.get("/api/raid").json()["items"] if i["type"] == "ISSUE")
    assert issue["explanation"]["reasoning"].startswith("Issue, so probability is fixed at 5")


# =================================================================================
# 4. Governance scorecard page
# =================================================================================

def test_scorecard_page_and_data(client, fake):
    page = client.get("/governance")
    assert page.status_code == 200
    for text in ("Model card", "Data policy", "Limits", "Kill switch", "human-validated"):
        assert text in page.text
    g = client.get("/api/governance").json()
    assert g["model_card"]["model"] == config.ANTHROPIC_MODEL and g["model_card"]["tools"]
    assert g["data_policy"]["data"].startswith("Fictional")
    assert g["limits"]["max_tokens_per_call"] == config.MAX_TOKENS
    assert g["kill_switch"]["engaged"] is False
    assert g["human_validation"]["pct_human_validated"] is None        # nothing yet


def test_scorecard_percent_human_validated_is_live(client, fake):
    a = ask(client).json()["review_id"]
    fake.calls = 0
    ask(client, "Second question?")
    hv = client.get("/api/governance").json()["human_validation"]
    assert hv["total_ai_outputs"] == 2 and hv["pct_human_validated"] == 0.0
    decide(client, a, "approve")
    hv = client.get("/api/governance").json()["human_validation"]
    assert hv["pct_human_validated"] == 50.0 and hv["pending_review"] == 1
    assert hv["pct_published_human_validated"] == 100.0


def test_kill_switch_runtime_control(client, fake, monkeypatch):
    body = {"engaged": True, "actor": "Wendell Killette", "reason": "Cost spike"}
    assert client.post("/api/governance/kill-switch", json=body).status_code == 403    # locked
    monkeypatch.setattr(config, "ADMIN_TOKEN", "adm")
    assert client.post("/api/governance/kill-switch", json=body).status_code == 401
    h = {"X-Admin-Token": "adm"}
    assert client.post("/api/governance/kill-switch", headers=h,
                       json={**body, "actor": "Claude"}).status_code == 403
    assert client.post("/api/governance/kill-switch", headers=h, json=body).json()["engaged"] is True
    assert ask(client).status_code == 503
    assert client.get("/health").json()["agent_enabled"] is False
    assert client.get("/api/ai-calls").json()[0]["outcome"] == "KILL_SWITCH"
    assert fake.kwargs == []                                    # the model was never called
    client.post("/api/governance/kill-switch", headers=h,
                json={"engaged": False, "actor": "Wendell Killette", "reason": "Resolved"})
    assert ask(client).status_code == 200


def test_kill_switch_from_environment(client, fake, monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", False)
    assert ask(client).status_code == 503
    assert client.get("/api/governance").json()["kill_switch"]["source"].startswith("environment")


def test_kill_switch_fails_closed_if_state_unreadable(session, monkeypatch):
    class Broken:
        def query(self, *a, **k): raise RuntimeError("db down")
        def rollback(self): pass
    assert governance.kill_switch_state(Broken())["engaged"] is True


# =================================================================================
# 5. Limiter
# =================================================================================

def test_per_visitor_rate_limit(client, fake, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 2)
    for _ in range(2):
        fake.calls = 0
        assert ask(client).status_code == 200
    r = ask(client)
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"
    fake.calls = 0
    assert ask(client, ip="198.51.100.9").status_code == 200   # another visitor is unaffected
    assert client.get("/api/ai-calls").json()[1]["outcome"] == "RATE_LIMITED"


def test_daily_caps_and_token_budget(client, fake, monkeypatch):
    monkeypatch.setattr(config, "DAILY_CAP_PER_VISITOR", 1)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 429
    monkeypatch.setattr(config, "DAILY_CAP_PER_VISITOR", 100)
    monkeypatch.setattr(config, "DAILY_CAP_GLOBAL", 1)
    assert ask(client, ip="198.51.100.20").status_code == 429
    monkeypatch.setattr(config, "DAILY_CAP_GLOBAL", 100)
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 300)       # first call used 330
    assert ask(client, ip="198.51.100.21").status_code == 429
    outcomes = [c["outcome"] for c in client.get("/api/ai-calls").json()]
    assert outcomes.count("CAP_REACHED") == 3


def test_max_tokens_and_turns_come_from_config(session, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS", 333)
    monkeypatch.setattr(config, "MAX_AGENT_TURNS", 1)
    f = FakeClaude()
    r = agent.ask(session, "q?", client=f, visitor="v1")
    assert [k["max_tokens"] for k in f.kwargs] == [333]
    assert r["draft_answer"].startswith("Stopped")


def test_request_size_and_question_length_limits(client, fake, monkeypatch):
    monkeypatch.setattr(config, "MAX_REQUEST_BYTES", 2048)
    big = client.post("/api/agent/ask", content=b'{"question": "' + b"x" * 5000 + b'"}',
                      headers={"Content-Type": "application/json"})
    assert big.status_code == 413
    assert ask(client, q="x" * (config.MAX_QUESTION_CHARS + 1)).status_code == 422
    assert fake.kwargs == []


def test_limits_are_read_from_environment(monkeypatch):
    for k, v in {"RATE_LIMIT_PER_MINUTE": "7", "DAILY_CAP_PER_VISITOR": "9", "DAILY_CAP_GLOBAL": "11",
                 "MAX_TOKENS": "512", "MAX_REQUEST_BYTES": "4096", "DAILY_TOKEN_BUDGET": "1000",
                 "AI_ENABLED": "false"}.items():
        monkeypatch.setenv(k, v)
    c = importlib.reload(config)
    try:
        assert (c.RATE_LIMIT_PER_MINUTE, c.DAILY_CAP_PER_VISITOR, c.DAILY_CAP_GLOBAL, c.MAX_TOKENS,
                c.MAX_REQUEST_BYTES, c.DAILY_TOKEN_BUDGET, c.AI_ENABLED) == (7, 9, 11, 512, 4096, 1000, False)
    finally:
        monkeypatch.undo()
        importlib.reload(config)
