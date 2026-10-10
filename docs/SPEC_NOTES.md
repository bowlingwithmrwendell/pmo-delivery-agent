# Specification notes

This file records how the original *Project Management & Delivery Agent* specification was turned into working software: what was kept, how ambiguous rules were interpreted, and what was changed and why.

## Kept as specified

* The identity, role, four core functions, tone and formatting rules. They live in the agent's system prompt in `app/agent.py`.
* Risk exposure = Probability × Impact on 1–5 scales, with the LOW / MEDIUM / HIGH bands and actions.
* SV, CV, SPI and CPI, plus EAC, ETC, VAC, TCPI and schedule variance in days.
* The executive report structure: RAG status, executive summary, KPI table, key accomplishments, upcoming milestones, blockers requiring intervention, and RAID log table. The demo data deliberately reproduces the sample RAID rows (R-101, R-102, R-103) and the sample KPI picture (SPI 0.94, CPI 1.02, one open critical blocker, AMBER overall).

## Interpretations (the spec was silent or ambiguous)

| Question | Decision |
|---|---|
| Which variance % for RAG? | Schedule = SV ÷ PV; cost = CV ÷ EV (standard PMI definitions). |
| Does a favourable variance count? | No. Only adverse variance degrades status. |
| Is exactly 5% or 15% amber? | 5.0% is green ("within 5%"); 15.0% is amber ("between 5% and 15%"); above 15% is red. |
| What makes a risk "mitigated"? | It has both a mitigation strategy and a named owner. |
| What does a HIGH risk do to RAG? | Unmitigated, it means executive intervention is needed: RED. Mitigated (under weekly tracking), it holds the stream at AMBER. This matches the sample, where two mitigated HIGH risks give an AMBER report. |
| Critical blocker vs. critical path? | A blocker *on* the critical path is RED. One that is not on it holds AMBER, because GREEN requires "no critical blockers". This matches the sample report: AMBER overall with one open blocker. |
| How do issues get a score? | An issue has already happened, so its probability is 5. |
| Milestone completion rate | Completed ÷ milestones whose *baseline* date has passed, so finishing early can't inflate the rate. |

## Changed, and why

1. **The model no longer does the math.** The spec's Python runner sends a payload to Claude and asks it for the figures, relying on `temperature=0.0` to make the result deterministic. Temperature 0 makes output *more repeatable*. It does not make arithmetic *correct*. In a PMO context, a wrong SPI or risk score sent to a sponsor is a governance failure. All figures now come from tested Python engines, and Claude orchestrates and explains them.
2. **Model ID.** The spec uses `claude-3-5-sonnet-20241022`, which is retired. The model is now set by `ANTHROPIC_MODEL` and defaults to `claude-sonnet-5-5`.
3. **CI syntax error.** The spec's smoke test uses `max_tokens: 50` inside a Python call (it must be `max_tokens=50`), so the workflow would always fail.
4. **Placeholder deploy.** The spec's Lambda deploy step is commented out. It always reports "Deployment completed successfully" while deploying nothing, and it zips the whole repository. This build deploys as a Docker service on Render (matching the Equity Comp Agent). CI runs the real test suite and health-checks the real container.
5. **Secrets.** The spec's secrets table lists Jira, Equity database and Slack values that nothing used, and leaves out the AWS keys the workflow *did* need. This build needs only `ANTHROPIC_API_KEY` (and only for the chat feature). CI needs no secrets at all.
6. **Human approval for outbound actions.** The spec mentions posting executive digests to Slack. Here a digest can only be proposed. A named person must approve it, and both the proposal and the decision are audited.

7. **AI governance hardening (v1.1).** Added after review against the governance requirements:
   * **Audit:** per-call log of who, when, model, tools, tokens and outcome. It covers refusals and errors, and is append-only.
   * **Review gate:** every AI output starts `PENDING_REVIEW`. Reviewers can approve, edit then approve, or reject with a reason. Earlier, a grounded Claude summary replaced the deterministic one automatically. Now it is only a draft until a human approves it.
   * **Explainability:** `{formula, inputs, reasoning}` on every score.
   * **Scorecard:** a `/governance` page.
   * **Kill switch:** set from the environment or at runtime. It fails closed.
   * **Limiter:** per-visitor rate limit, daily caps, token budget, `max_tokens`, request and question size. All settings are in `.env`.

## Deferred to a later version

* A live Jira connector (v1 records the Jira ticket it would create, as a dry run).
* Real telemetry ingestion. v1 uses a seeded, fictional portfolio.
