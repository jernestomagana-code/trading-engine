# Stock Ultimus Agents

This directory defines the agent roles used to keep Stock Ultimus consistent,
conservative, verifiable, and aligned with the long-term product vision.

See also:

- `../product-vision.md`
- `../roadmap.md`

## Persistent Agents

- `project-goal-guardian.md`: protects the final objective, non-negotiables, blocker priority, and manual-decision assistant model.
- `market-strategy-researcher.md`: monitors market-practice changes and proposes research-backed strategy or parameter updates.
- `information-security-guardian.md`: protects secrets, account data, endpoints,
  logs, dependencies, and future multi-user boundaries.

## Implementation Agents

- `explorer.md`: maps current code flow and write scopes without editing files.
- `bridge-worker.md`: enriches and verifies bridge-side IBKR snapshot data.
- `cloud-worker.md`: keeps FastAPI, runtime snapshots, dashboards, and GPT-facing endpoints aligned.
- `risk-decision-worker.md`: enforces blocker priority, risk gates, and readiness rules.
- `qa-worker.md`: owns fixtures, tests, compile checks, and scenario coverage.

## Operating Model

Use `operating-model.md` as the coordination guide. In short:

1. Goal Guardian anchors the product objective and non-negotiables.
2. Information Security Guardian identifies security-sensitive surfaces when
   changes touch credentials, webhooks, endpoints, logs, runtime data, cloud
   config, or multi-user behavior.
3. Explorer maps the current code.
4. Scoped workers change only their owned surfaces.
5. QA Worker verifies behavior.
6. Goal Guardian checks consistency before merge.
7. Market Strategy Researcher proposes market-driven changes only as research notes or testable implementation tasks.

## Supporting Checklists

- `../checklists/strategy-parameter-review.md`
- `../v30/acceptance-checklist.md`
- `../v30/decision-contract.md`
