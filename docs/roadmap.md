# Stock Ultimus Roadmap

## V30: Contract Enrichment Foundation

V30 is validated locally and remains the safety foundation for later versions.

Objective:

- enrich option contracts from IBKR,
- publish executable contract data in the master snapshot,
- preserve `WAIT_OPTIONS_DATA` blocker priority,
- expose the same decision state through dashboard and GPT-facing endpoints,
- and prevent incomplete option data from becoming `ENTRY_READY`.

V30 is the foundation for everything that follows.

## V31: Canonical Decision Engine

Purpose: replace overlapping historical decision paths with one source of truth.

Current status:

- V31 has started as an explicit versioned API contract backed by the validated
  V29 engine.
- Available surfaces: `/v31_system_status`, `/v31_trade_decision/{ticker}`,
  and `/gpt_v31_trade_decision/{ticker}`.
- Runtime publishing and canonical-state guards are available locally.
- Next implementation step: move schema and blocker-contract helpers out of
  `app/main.py` into shared modules.

Expected work:

- create shared schema modules for snapshots, contracts, blockers, and decisions,
- define canonical states,
- centralize executable option validation,
- centralize risk gating,
- version `decision_version`, `strategy_version`, `ruleset_version`, and
  `snapshot_version`,
- make dashboards and GPT endpoints consume the same decision payload,
- keep backwards-compatible adapters for older snapshots where needed.

Success criteria:

- one function or module owns final decision state,
- fixture tests cover every canonical blocker,
- no dashboard-only or GPT-only decision logic exists,
- historical compatibility is explicit instead of accidental.

## V32: Outcome Tracking And Learning Loop

Purpose: measure whether the engine is actually improving decisions.

Current status:

- Decision journaling uses stable IDs and deduplicates repeated reads.
- Follow-ups track observation count, MFE, and MAE.
- Outcomes can be recorded and summarized through V32 endpoints.
- The flow passes local guards but still needs durable, isolated, auditable
  storage before production or multi-user use.

Expected work:

- store every decision snapshot,
- record whether candidates were acted on, ignored, or invalidated,
- track market outcome after fixed windows,
- track option-specific outcomes such as premium capture, assignment risk,
  max adverse excursion, max favorable excursion, and liquidity/slippage notes,
- build parameter review reports,
- propose ruleset changes as reviewable tasks, not automatic behavior changes.

Success criteria:

- every `ENTRY_READY` and major blocker can be evaluated later,
- strategy performance is visible by ticker, regime, DTE, delta, spread, and
  volatility context,
- parameter changes are evidence-backed and versioned.

## V33: Product-Grade Platform Readiness

Purpose: prepare the system for controlled multi-user or commercial evaluation.

Expected work:

- user/account isolation,
- secure credential boundaries,
- authenticated customer-facing endpoints,
- safe logging and redaction,
- runtime-data retention policy,
- profile-level risk limits,
- audit exports,
- disclosure and terms workflow,
- paper-trading or simulation mode,
- operational monitoring,
- deployment hardening,
- legal/compliance review before third-party trading-account connectivity.

Success criteria:

- one user's data cannot leak into another user's decisions,
- every decision can be audited by snapshot and ruleset version,
- no automatic order execution exists,
- product language stays in analytics/decision-support territory unless legal
  review approves otherwise.

## Later Research Tracks

Potential future tracks must start as research notes and become testable rules
before implementation:

- volatility regime classifier,
- earnings/event avoidance model,
- portfolio concentration and correlation engine,
- assignment probability model,
- options liquidity score,
- tax-aware and account-type-aware constraints,
- strategy disable/enable rules by market regime,
- broker abstraction beyond IBKR.
