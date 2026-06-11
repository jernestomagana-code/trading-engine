# Stock Ultimus Agent Guide

## Project Context

Stock Ultimus is a hybrid local/cloud trading decision engine. The long-term
objective is to become an auditable trading decision operating system for
options: ingestion, normalization, strategy scoring, risk gating, explanation,
monitoring, learning, and product-grade governance.

The local bridge, expected as `ibkr_bridge.py`, connects to Interactive Brokers through `ib_insync`. It reads market prices, positions, option chains, evaluates Naked Put and Covered Call candidates, and publishes a master snapshot to Render.

The cloud app, expected as `app/main.py`, runs FastAPI on Render. It receives snapshots through POST endpoints, stores temporary JSON files under `runtime/`, and exposes GET endpoints for system state, HTML dashboards, and per-ticker decisions consumable by GPT.

TradingView can send technical alerts through webhooks. Those technical snapshots are stored as JSON and may be combined with IBKR data by the decision engine.

The system must remain a decision assistant. It must not place live orders automatically.

For personal use, Stock Ultimus may surface high-conviction opportunities for
manual validation. For any future commercial use, it must be treated as a
platform-grade analytics and decision-support product, not as an ungoverned
auto-trading service.

## Product Direction

Stock Ultimus should mature from a personal trading helper into a disciplined
decision platform:

- Data layer: IBKR, TradingView, market/session state, account context,
  positions, events, liquidity, and volatility inputs.
- Normalization layer: one stable, versioned snapshot contract for downstream
  decisions and GPT consumption.
- Strategy layer: modular strategy evaluators such as Naked Put, Covered Call,
  Iron Condor, position management, and future research-approved strategies.
- Risk layer: capital, margin, concentration, liquidity, spread, event risk,
  assignment risk, delta exposure, and user/profile constraints.
- Decision layer: canonical blocker priority and one source of truth for
  readiness.
- Explanation layer: per-ticker rationale, missing fields, blockers, and next
  required validation.
- Learning layer: outcomes, forward-test history, rule performance, and
  parameter review evidence.
- Security/governance layer: secrets handling, authentication, authorization,
  audit logs, versioned rules, disclosures, commercial readiness, user/account
  isolation, and compliance review before third-party use.

The product should get more powerful by becoming more measurable, explainable,
auditable, and risk-aware. It should not become more aggressive by bypassing
data quality, risk blockers, or human validation.

## Current Known Version

V29.1 has the blocker priority working correctly:

- If the technical signal is confirmed but executable option contract data is missing, the decision should be `WAIT_OPTIONS_DATA`.
- It should not incorrectly classify that state as `WAIT_TECHNICAL`.

## V30 Objective

Enrich option contracts from `ibkr_bridge.py` and publish executable contract data in the master snapshot.

Required option fields:

- `strike`
- `expiration`
- `dte`
- `bid`
- `ask`
- `mid`
- `spread`
- `spread_pct`
- `delta`

Only mark a candidate as `ENTRY_READY` when:

- the technical signal is confirmed,
- all required executable option fields are present and valid,
- risk rules pass,
- and no manual-review blocker remains.

## Non-Negotiables

- Never add automatic order execution.
- Never let GPT, dashboards, or UI copy override deterministic blocker logic.
- Never weaken blocker priority for `WAIT_OPTIONS_DATA`.
- Prefer explicit blockers over optimistic readiness.
- Keep cloud decisions explainable by ticker.
- Keep snapshots JSON-serializable and stable for GPT consumption.
- Preserve enough raw snapshot context to reconstruct why a decision was made.
- Treat `ENTRY_READY` as "ready for manual review", not as authorization to trade.
- Version decision rules, strategy rules, and snapshot contracts when behavior changes.
- Before any commercial or multi-user release, require legal/compliance review,
  user/account isolation, risk-profile handling, disclosures, and audit logging.
- Treat broker credentials, webhook secrets, account snapshots, positions,
  balances, and runtime files as sensitive data.
- Do not expose secrets, account identifiers, raw tokens, or unnecessary
  personally identifiable/account-specific data through logs, dashboards,
  endpoints, GPT payloads, or fixtures.

## Canonical Decision Direction

Future work after V30 should converge on one canonical decision engine instead
of accumulating overlapping historical engines. Preferred canonical states:

- `NO_DATA`
- `WAIT_MARKET`
- `WAIT_ACCOUNT_CONTEXT`
- `WAIT_OPTIONS_DATA`
- `WAIT_TECHNICAL`
- `RISK_BLOCKED`
- `MANUAL_REVIEW`
- `ENTRY_READY`

Every decision should include:

- `decision_version`
- `strategy_version`
- `ruleset_version`
- `snapshot_version`
- `main_blocker`
- `blockers`
- `required_missing_fields`
- `risk_notes`
- `explanation`
- enough selected contract data to audit the result by ticker

## Recommended Agent Workflow

Use agents only after the real project files are present in this workspace.

Persistent roles:

- Project Goal Guardian: keeps the final objective, safety rules, blocker priority, and manual-decision model intact across all work.
- Market Strategy Researcher: reviews changing market practices and proposes research-backed strategy or parameter updates as testable rules.
- Information Security Guardian: reviews secrets, authentication, authorization,
  data exposure, logging, dependency risk, endpoint hardening, and multi-user
  isolation before security-sensitive changes are accepted.

On-demand implementation roles:

- Explorer: map current data flow from IBKR snapshot to cloud decision.
- Bridge Worker: enrich option contract data in `ibkr_bridge.py`.
- Cloud Worker: update FastAPI schemas/endpoints/dashboard handling in `app/main.py`.
- Risk/Decision Worker: enforce `ENTRY_READY` gating and blocker priority.
- QA Worker: build fixtures/tests for snapshot states such as `WAIT_OPTIONS_DATA`, `WAIT_TECHNICAL`, and `ENTRY_READY`.

Each worker should own a disjoint write scope to avoid conflicts.

See `docs/agents/operating-model.md` for the full coordination model.

## Acceptance Criteria For V30

- Master snapshot includes the required option fields for candidate contracts.
- Missing or invalid strike/expiration/dte/bid/ask/mid/spread/spread_pct/delta keeps the decision at `WAIT_OPTIONS_DATA`.
- Confirmed technical signal plus incomplete option data never becomes `ENTRY_READY`.
- Complete option data plus passing risk rules can become `ENTRY_READY`.
- Tests or fixture checks cover incomplete and complete option-data scenarios.
- Dashboard and GPT-facing endpoints expose the same decision state consistently.
- No code path submits IBKR orders automatically.

## Post-V30 Direction

V31 should consolidate a canonical decision engine with shared schema modules
and one blocker source of truth.

V32 should add outcomes and performance tracking so every signal can be judged
against later market behavior.

V33 should prepare product-grade operation: multi-user boundaries, paper-trading
or simulation mode, audit exports, risk profiles, disclosures, and commercial
readiness review.
