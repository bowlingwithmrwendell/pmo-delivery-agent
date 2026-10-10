"""API tests against the seeded fictional portfolio (status date 2026-10-09)."""
from types import SimpleNamespace

from app import agent


def test_portfolio_lands_each_stream_on_its_designed_status(client):
    p = client.get("/api/portfolio").json()
    rag = {x["project_id"]: x["rag"] for x in p["projects"]}
    assert rag == {"EDP-INFRA": "GREEN", "EDP-MIGR": "AMBER", "EDP-ANLY": "RED", "EDP-SEC": "AMBER"}
    assert p["program_rag"] == "RED"
    assert p["counts"] == {"GREEN": 1, "AMBER": 2, "RED": 1}


def test_red_stream_lists_every_trigger(client):
    r = client.get("/api/projects/EDP-ANLY/rag").json()
    codes = {x["code"] for x in r["reasons"]}
    assert codes == {"SCHEDULE_VARIANCE", "COST_VARIANCE", "CRITICAL_PATH_BLOCKED", "UNMITIGATED_HIGH_RISK"}


def test_status_report_matches_spec_template(client):
    r = client.get("/api/projects/EDP-MIGR/status-report").json()
    assert r["overall_rag"] == "AMBER"
    kpi = {k["kpi"]: k for k in r["kpis"]}
    assert kpi["Schedule Performance Index (SPI)"]["actual"] == "0.94"
    assert kpi["Schedule Performance Index (SPI)"]["variance"] == "-0.06"
    assert kpi["Cost Performance Index (CPI)"]["variance"] == "+0.02"
    assert kpi["Milestone Completion Rate"]["actual"] == "80.0%"   # 4 of 5 due
    assert kpi["Open Critical Blockers"]["actual"] == "1"
    assert kpi["Open Critical Blockers"]["status"] == "RED"
    assert [m["id"] for m in r["upcoming_milestones"]] == ["M-205"]
    md = client.get("/api/projects/EDP-MIGR/status-report?format=markdown").text
    assert "| KPI Metric | Target | Actual | Variance / Status |" in md
    assert "$2,000,000.00" in md and "16 (HIGH)" in md


def test_resources_overallocation_gaps_and_spofs(client):
    r = client.get("/api/resources").json()
    util = {u["person_id"]: u for u in r["utilisation"]}
    assert util["U1"]["utilisation_pct"] == "120.0"   # 20 + 20 + 8 = 48 of 40 h
    assert util["U1"]["over_by_hours"] == "8.00"
    assert util["U3"]["utilisation_pct"] == "115.0"   # 30 + 16 = 46 of 40 h
    assert util["U6"]["flag"] == "UNDERUTILISED"      # 16 of 40 h = 40%
    gaps = {(g["project_id"], g["skill"]): g["fte_short"] for g in r["skills_gaps"]}
    assert gaps[("EDP-MIGR", "data-migration")] == "0.25"   # 2.0 - (40/40 + 30/40)
    assert gaps[("EDP-ANLY", "data-modeling")] == "0.50"    # nobody assigned
    spof = {s["skill"]: s for s in r["single_points_of_failure"]}
    assert set(spof) == {"cloud-architecture", "delivery-management", "power-bi", "terraform"}
    assert spof["cloud-architecture"]["severity"] == "CRITICAL"  # sole holder is overallocated


def test_dependencies_seeded(client):
    r = client.get("/api/dependencies").json()
    st = {d["id"]: d["status"] for d in r["dependencies"]}
    assert st == {"D-1": "ON_TRACK", "D-2": "CONFLICT", "D-3": "AT_RISK", "D-4": "SATISFIED"}
    assert r["cycles"] == []


def test_adding_unmitigated_high_risk_turns_green_stream_red(client):
    resp = client.post("/api/projects/EDP-INFRA/raid", json={
        "type": "RISK", "category": "Technical", "description": "Region capacity shortage",
        "probability": 4, "impact": 5})
    assert resp.status_code == 201
    body = resp.json()
    assert body["score_label"] == "20 (HIGH)" and body["id"] == "R-403"
    assert client.get("/api/projects/EDP-INFRA/rag").json()["status"] == "RED"


def test_raid_rejects_client_supplied_score_and_bad_items(client):
    assert client.post("/api/projects/EDP-INFRA/raid", json={
        "type": "RISK", "category": "T", "description": "missing impact", "probability": 3}).status_code == 422
    assert client.post("/api/projects/NOPE/raid", json={
        "type": "RISK", "category": "T", "description": "x x", "probability": 3, "impact": 3}).status_code == 404


def test_what_if_endpoints(client):
    assert client.post("/api/risk/score", json={"probability": 3, "impact": 4}).json()["label"] == "12 (MED)"
    assert client.post("/api/risk/score", json={"probability": 6, "impact": 4}).status_code == 422
    e = client.post("/api/evm/calculate", json={"bac": "100", "pv": "50", "ev": "40", "ac": "50"}).json()
    assert (e["spi"], e["cpi"], e["sv_pct"]) == ("0.80", "0.80", "-20.0")


def test_outbound_actions_require_a_named_human(client):
    a = client.post("/api/actions", json={"action_type": "POST_SLACK_DIGEST",
                                          "project_id": "EDP-MIGR", "requested_by": "agent"}).json()
    assert a["status"] == "PENDING" and "Executive Status Report" in a["payload"]["markdown"]
    aid = a["id"]
    assert client.post(f"/api/actions/{aid}/decision",
                       json={"approve": True, "decided_by": "agent"}).status_code == 409
    ok = client.post(f"/api/actions/{aid}/decision", json={"approve": True, "decided_by": "Wendell"}).json()
    assert ok["status"] == "EXECUTED" and ok["result"].startswith("DRY RUN")
    assert client.post(f"/api/actions/{aid}/decision",
                       json={"approve": False, "decided_by": "Wendell",
                             "reason": "Changed my mind"}).status_code == 409
    events = [e["event"] for e in client.get("/api/audit").json()]
    assert "ACTION_PROPOSED" in events and "ACTION_APPROVED" in events


def test_agent_endpoint_without_key_is_503_but_engines_work(client):
    assert client.post("/api/agent/ask", json={"question": "status?"}).status_code == 503
    assert client.get("/health").json()["agent_enabled"] is False


# --- agent orchestration with a fake Claude client ----------------------------

class FakeClaude:
    """Scripted stand-in for the Anthropic client: one tool call, then an answer."""
    def __init__(self, final_text):
        self.final_text, self.calls = final_text, 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(
                type="tool_use", id="t1", name="get_project_rag", input={"project_id": "EDP-MIGR"})])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=self.final_text)])


def test_agent_uses_engines_and_passes_grounding(session):
    r = agent.ask(session, "Why is migration amber?",
                  client=FakeClaude("EDP-MIGR is AMBER: schedule variance -6.0% and blocker I-104."))
    assert r["tools_used"][0]["tool"] == "get_project_rag"
    assert r["grounded"] is True
    assert r["status"] == "PENDING_REVIEW" and r["validated"] is False


def test_agent_invented_number_is_flagged(session):
    r = agent.ask(session, "Forecast?", client=FakeClaude("We will recover 37% of the slip by Sprint 14."))
    assert r["grounded"] is False and "37" in r["unverified_numbers"]


def test_claude_narrative_is_only_a_draft_until_a_human_approves(session):
    from app import repository
    report = repository.status_report(session, "EDP-MIGR")

    class OneShot:
        def __init__(self, text): self.messages = self; self.text = text
        def create(self, **kw):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])

    grounded = agent.narrate_summary(report, client=OneShot("The stream is AMBER with SPI 0.94 and CPI 1.02."),
                                     s=session)
    # Even a fully grounded draft never replaces the summary on its own.
    assert grounded["executive_summary"] == report["executive_summary"]
    assert grounded["narrative_review"]["status"] == "PENDING_REVIEW"
    assert grounded["narrative_review"]["grounded"] is True
    invented = agent.narrate_summary(report, client=OneShot("AMBER; SPI 0.94; recovery expected in 3 weeks."),
                                     s=session)
    assert invented["narrative_review"]["grounded"] is False
    assert invented["narrative_review"]["unverified_numbers"] == ["3"]
    assert invented["executive_summary"] == report["executive_summary"]
