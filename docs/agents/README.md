# Stock Ultimus Agents

This directory defines the agent roles used to keep Stock Ultimus consistent,
conservative, verifiable, and aligned with the long-term product vision.

See also:

- `../product-vision.md`
- `../roadmap.md`

## Persistent Agents

- Athena (`project-goal-guardian.md`): protects the final objective, non-negotiables, blocker priority, and manual-decision assistant model.
- Morgan (`market-strategy-researcher.md`): monitors market-practice changes and proposes research-backed strategy or parameter updates.
- Sentinel (`information-security-guardian.md`): protects secrets, account data,
  endpoints, logs, dependencies, and future multi-user boundaries.

## Implementation Agents

- Scout (`explorer.md`): maps current code flow and write scopes without editing files.
- Bridge (`bridge-worker.md`): enriches and verifies bridge-side IBKR snapshot data.
- Nova (`cloud-worker.md`): keeps FastAPI, runtime snapshots, dashboards, and GPT-facing endpoints aligned.
- Atlas (`risk-decision-worker.md`): enforces blocker priority, risk gates, and readiness rules.
- Quinn (`qa-worker.md`): owns fixtures, tests, compile checks, and scenario coverage.
- Vega (`tradingview-signal-guardian.md`): protects TradingView webhook payloads, signal freshness, parsing, and technical blocker behavior.
- Ledger (`ibkr-integration-guardian.md`): protects IBKR data ingestion, option-chain enrichment, snapshot serialization, and no-order-execution boundaries.

## Operating Model

Use `operating-model.md` as the coordination guide. In short:

1. Athena anchors the product objective and non-negotiables.
2. Sentinel identifies security-sensitive surfaces when
   changes touch credentials, webhooks, endpoints, logs, runtime data, cloud
   config, or multi-user behavior.
3. Scout maps the current code.
4. Vega or Ledger review external-interface changes when TradingView or IBKR behavior is touched.
5. Scoped workers change only their owned surfaces.
6. Quinn verifies behavior.
7. Athena checks consistency before merge.
8. Morgan proposes market-driven changes only as research notes or testable implementation tasks.

## Supporting Checklists

- `../checklists/strategy-parameter-review.md`
- `../v30/acceptance-checklist.md`
- `../v30/decision-contract.md`
