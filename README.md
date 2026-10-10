# Project Management & Delivery Agent

**A PMO agent for multi-stream delivery that an executive can trust, because the AI never does the math.**

The agent oversees a multi-stream program. It scores the RAID log, tracks milestone health with earned value, sets RAG status against explicit criteria, builds C-level status reports, and finds overallocated people, skills gaps and single points of failure across teams.

Claude plans the work and explains the results. Every number comes from deterministic, tested Python.

> Built by **Wendell Killette — [Agile by Killette](https://agilebykillette.com)**. Companion to the [Equity Compensation Management Agent](https://github.com/bowlingwithmrwendell/equity-comp-agent). All data is fictional.

---

## The governance I applied

| Choice | What it means in this build |
|---|---|
| **Bounded authority** | Claude can *read* engine results and *propose* an action. It has no tool that writes project data and no tool that sends anything. |
| **Deterministic math** | SV, CV, SPI, CPI, EAC, risk exposure, RAG, utilisation and float are computed in Python using `Decimal`. The model is never asked for a figure. |
| **Grounding check** | Every number in Claude's answer is checked against the tool results it received. Invented figures are flagged (`grounded: false`), and an ungrounded output cannot be approved unchanged. |
| **Always human-validated** | Every AI output (agent answers and report-summary drafts) is stored **`PENDING_REVIEW`** and is never published until a named human **approves**, **edits then approves**, or **rejects it with a reason**. Decisions are final. There is no bypass route, and the AI, agents, bots and automated systems are refused as reviewers. Outbound actions (Slack digest, Jira ticket) go through the same kind of named-human gate. |
| **Audit trail** | Every AI call is logged with **who** (salted-hash visitor ID and optional name), **when**, **model**, **tools**, **input/output tokens** and **outcome** (`OK`, `ERROR`, `RATE_LIMITED`, `CAP_REACHED`, `KILL_SWITCH`, `UNAVAILABLE`). Every tool call, RAID change, review decision and approval is also written to the audit log. Both logs are append-only (the ORM refuses UPDATE and DELETE). |
| **Explainable scores** | Every score returns `explanation: {formula, inputs, reasoning}`. That covers risk exposure, every EVM metric, RAG, milestone rate and slip, utilisation, skills gaps, single points of failure, dependency float and each executive-report KPI. |
| **Governance scorecard** | `/governance` shows the model card, data policy, limits, the kill switch and a live **% human-validated**. |
| **Limiter** | Per-visitor rate limit and daily cap, a global daily cap and token budget, `max_tokens`, maximum tool turns, and request-size and question-length limits. All are set in `.env`. |
| **Fails closed** | If the kill-switch state or usage counts can't be read, the AI call is refused. A review in any state other than approved is never published. If two reviewers race, only the first decision lands. |

---

## What it does

| Capability | Endpoint | Engine |
|---|---|---|
| Program portfolio with RAG per stream | `GET /api/portfolio` | `rag.py` |
| RAG status with every triggering reason | `GET /api/projects/{id}/rag` | `rag.py` |
| Earned value: SV, CV, SPI, CPI, EAC, ETC, VAC, TCPI, SV in days | `GET /api/projects/{id}/evm` | `evm.py` |
| What-if earned value for any figures | `POST /api/evm/calculate` | `evm.py` |
| Milestone completion rate, slipped, overdue, upcoming | `GET /api/projects/{id}/milestones` | `milestones.py` |
| Scored RAID log (program-wide or per stream) | `GET /api/raid` | `raid.py`, `risk.py` |
| Add a RAID item (the server computes the score) | `POST /api/projects/{id}/raid` | `raid.py` |
| Score a hypothetical risk | `POST /api/risk/score` | `risk.py` |
| Executive status report (JSON or Markdown) | `GET /api/projects/{id}/status-report` | `report.py` |
| Utilisation, skills gaps, single points of failure | `GET /api/resources` | `resources.py` |
| Cross-project dependency conflicts and cycles | `GET /api/dependencies` | `dependencies.py` |
| Ask the agent in plain English (returns a **draft**, `PENDING_REVIEW`) | `POST /api/agent/ask` | Claude + all of the above |
| Review queue for AI output | `GET /api/reviews`, `GET /api/reviews/{id}` | `governance.py` |
| Approve / edit-then-approve / reject (reason required) | `POST /api/reviews/{id}/decision` | `governance.py` |
| Human-approved text only (409 otherwise) | `GET /api/reviews/{id}/published` | `governance.py` |
| Report with an approved Claude summary | `GET /api/projects/{id}/status-report?narrative_review={id}` | `report.py` + review gate |
| AI call log | `GET /api/ai-calls` | `governance.py` |
| Governance scorecard (page and JSON) | `/governance`, `GET /api/governance` | `governance.py` |
| Kill switch (runtime, needs `ADMIN_TOKEN`) | `POST /api/governance/kill-switch` | `governance.py` |
| Propose, list and decide outbound actions | `/api/actions`, `/api/actions/{id}/decision` | `actions.py` |
| Audit log | `GET /api/audit` | `actions.py` |

There is also a web console at `/` (with a **Human review** tab), the governance scorecard at `/governance`, and interactive API docs at `/docs`.

---

## AI governance controls

### The human review gate

```
Claude output ──► PENDING_REVIEW ──┬─ approve ───────────────► APPROVED            ─► published
                                   ├─ edit, then approve ────► APPROVED_WITH_EDITS ─► published (edit; original kept)
                                   └─ reject + reason ───────► REJECTED            ─► never published
```

* **No bypass.** The only write route is `POST /api/reviews/{id}/decision`. `create_review()` takes no status argument, and the agent has no review or approve tool. Tests check all three.
* **The AI can't approve its own work.** A reviewer must be a named person. Names that identify an AI or automation (`Claude`, `claude-sonnet-5-5`, `Claude (AI)`, `agent`, `PMO Bot`, `system`, `auto-approver`, …) are refused. Set `REVIEWER_TOKEN` to also require a reviewer token header.
* **Fails closed.** Only `APPROVED` / `APPROVED_WITH_EDITS` with a named reviewer is published. An output with unverified numbers can't be approved unchanged: the reviewer must edit those numbers out or reject it. Decisions use compare-and-set, so a second decision gets `409`.

### Limiter (all in `.env`)

| Setting | Default | What it does |
|---|---|---|
| `RATE_LIMIT_PER_MINUTE` | 5 | AI requests per visitor per minute (`429` + `Retry-After`) |
| `DAILY_CAP_PER_VISITOR` | 25 | AI requests per visitor per UTC day |
| `DAILY_CAP_GLOBAL` | 200 | AI requests across all visitors per UTC day |
| `DAILY_TOKEN_BUDGET` | 400000 | Input + output tokens across all visitors per UTC day |
| `MAX_TOKENS` | 1024 | `max_tokens` on every agent model call |
| `NARRATIVE_MAX_TOKENS` | 400 | `max_tokens` for a report-summary draft |
| `MAX_AGENT_TURNS` | 6 | Tool round trips per question |
| `MAX_REQUEST_BYTES` | 16384 | Largest request body (`413` above it) |
| `MAX_QUESTION_CHARS` | 1000 | Longest question (`422` above it) |
| `TRUSTED_PROXY_HOPS` | 0 | Set to `1` behind Render so each visitor is identified correctly |

Refused calls never reach the model, and they are logged with their outcome. Visitors are identified by a salted hash (`VISITOR_SALT`); raw IP addresses are not stored.

### Kill switch

* `AI_ENABLED=false` turns every model call off from the environment.
* With `ADMIN_TOKEN` set, the switch can be flipped at runtime from `/governance` (or `POST /api/governance/kill-switch` with `X-Admin-Token`). Each change is recorded with who did it and why.
* The deterministic engines keep working either way.

> **Note:** the append-only rule is enforced in the application (ORM). If a deployment needs it enforced at the database level too, add a PostgreSQL `REVOKE UPDATE, DELETE` or a trigger on `audit_log`, `ai_call_log` and `kill_switch_events`.

---

## The rules, exactly as implemented

**Risk exposure** = Probability (1–5) × Impact (1–5)

| Band | Score | Required action |
|---|---|---|
| LOW | 1–6 | Log and monitor monthly |
| MEDIUM | 8–12 | Active mitigation strategy required; review bi-weekly |
| HIGH | 15–25 | Escalate immediately to Executive Sponsor; weekly mitigation tracking |

The product of two whole numbers from 1 to 5 can never be 7, 11, 13 or 14, so the bands have no gaps. An **issue** has already happened, so its probability is fixed at 5.

**RAG status.** The overall status is the worst one triggered.

| Status | Triggered by |
|---|---|
| 🟢 GREEN | Adverse schedule and cost variance both ≤ 5%, no critical blockers, no unmitigated medium or high risks |
| 🟠 AMBER | Adverse variance > 5% and ≤ 15%; an unmitigated MEDIUM risk; a mitigated HIGH risk (weekly tracking); a critical blocker that is not on the critical path |
| 🔴 RED | Adverse variance > 15%; a blocker on the critical path; an unmitigated HIGH risk (executive intervention required) |

* Schedule variance % = SV ÷ PV × 100. Cost variance % = CV ÷ EV × 100.
* Only *adverse* variance counts. Being ahead of schedule or under budget never turns a stream amber.
* Exactly 5.0% is still green ("within 5%"). Exactly 15.0% is still amber ("between 5% and 15%").
* *Mitigated* means the item has both a mitigation strategy and a named owner.

**Resources.** Overallocated means more than 100% of capacity; underutilised means under 50%. A single point of failure is a skill some stream needs that only one person holds. It is rated *critical* when that person is overallocated or the skill serves more than one stream.

**Dependencies.** A conflict is a provider milestone forecast to land after the consumer's need-by date. "At risk" means less than 5 days of float remain. Circular dependencies between streams are also detected.

---

## The demo portfolio (fictional)

*Enterprise Data Platform Migration*, status date 2026-10-09:

| Stream | RAG | Why |
|---|---|---|
| Cloud Infrastructure & Landing Zone | 🟢 GREEN | SPI 0.98, CPI 1.02, no blockers |
| Data Migration & Vendor API Integration | 🟠 AMBER | SPI 0.94 (−6%), vendor credential blocker, two high risks under mitigation |
| Analytics & BI Modernization | 🔴 RED | −20% schedule, −25% cost, critical path blocked, unmitigated high risk |
| Security & Compliance | 🟠 AMBER | On budget and schedule, but an unmitigated medium risk |

---

## Run it

### With Docker (PostgreSQL included)

```bash
cp .env.example .env          # optional: add ANTHROPIC_API_KEY; tune limits / kill switch
docker compose up --build
```

Then open <http://localhost:8000>. Everything except the "Ask the agent" tab works without an API key.

### Without Docker

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload  # uses a local SQLite file
```

### Tests

```bash
python -m pytest -q
```

There are 98 tests. Expected values are calculated by hand in the test comments, including the 5% and 15% RAG boundaries, divide-by-zero handling, the approval gate and the grounding check. `tests/test_governance.py` proves each governance requirement:

* AI calls are logged with who, when, model, tools, tokens and outcome, including refusals and errors.
* The logs are append-only.
* Every output starts `PENDING_REVIEW`.
* Approve, edit-then-approve and reject-with-reason each work, and decisions are final.
* 14 AI or automation identities are refused as reviewers, and no bypass route exists.
* Ungrounded output and odd states fail closed, and concurrent decisions are safe.
* Every score on every endpoint carries a formula, inputs and reasoning.
* The scorecard and its live % human-validated work, and the kill switch works from the runtime, the environment and an unreadable state.
* The rate limit, daily caps, token budget, `max_tokens`, request size and `.env` loading all work.

The Claude agent is tested with a scripted fake client, so the tests need no API key.

---

## Deploy the live sandbox (Render, free)

1. Push this repo to GitHub.
2. In Render, choose **New → Blueprint** and select the repo. `render.yaml` creates one free Docker web service.
3. In the service's **Environment** settings, add `ANTHROPIC_API_KEY`. Type it there yourself. Never commit it.

The sandbox keeps its data in SQLite inside the container, so the fictional portfolio reseeds every time the free instance wakes and visitors' edits never pile up. For a persistent deployment, point `DATABASE_URL` at PostgreSQL. No code changes are needed.

## Secrets

| Name | Where | Needed? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Render environment; GitHub Actions secret only for the optional live check | Only for "Ask the agent" |
| `ANTHROPIC_MODEL` | Render environment | No (defaults to `claude-sonnet-5-5`) |
| `ADMIN_TOKEN` | Render environment | No (enables the runtime kill switch) |
| `REVIEWER_TOKEN` | Render environment | No (requires a token for review decisions) |
| `VISITOR_SALT` | Generated by `render.yaml` | No |
| `SLACK_WEBHOOK_URL` | Render environment | No (approved digests run as a dry run without it) |
| `DATABASE_URL` | Set by Docker Compose / Render | No |

CI (`.github/workflows/ci.yml`) runs the tests and builds and health-checks the Docker image on every push. It needs **no secrets**. A live Claude smoke test can be run by hand from the Actions tab.

---

## Project layout

```
app/
  engines/        deterministic calculations (no I/O, no AI)
    risk.py  raid.py  evm.py  rag.py  milestones.py
    resources.py  dependencies.py  report.py  types.py
    explain.py    {formula, inputs, reasoning} on every score
  agent.py        Claude tool-use loop + grounding check (drafts only)
  governance.py   AI-call log, human review gate, kill switch, limiter
  actions.py      outbound-action approval gate + audit log
  repository.py   database -> engine types -> results
  models.py       SQLAlchemy schema      seed.py  fictional portfolio
  main.py         FastAPI routes, request-size limit
  static/         web console (index.html) + governance scorecard (governance.html)
db/schema.sql     PostgreSQL schema (generated)
tests/            98 tests (engines, API, governance)
docs/SPEC_NOTES.md  how the original specification was interpreted
```
