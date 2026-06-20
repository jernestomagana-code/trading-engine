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
- `docs/strategy-playbook.md` now defines the first versioned strategy playbook
  for daily data sources, freshness, blockers, ranking, and manual-review
  recommendation labels.
- `docs/strategy-intelligence-loop.md` now defines Morgan's research-to-rule
  process for market practice, elite trader/institutional research, intraday vs
  non-intraday review, and safe promotion into versioned rules.
- `config/strategy_registry.json` and `docs/strategy_research_notes/` provide
  the first validated Strategy Intelligence implementation artifacts.
- V31 consumes `config/strategy_registry.json` so `RADAR_ONLY` strategies are
  capped out of `ENTRY_READY` with explicit registry blockers.
- V31 exposes `strategy_score_components_v1` for technical, option quality,
  risk, fundamental/CANSLIM, regime, outcome evidence, and registry state.
- V31 exposes `strategy_daily_ranking_v1` through `/v31_daily_rankings` and
  `/gpt_v31_daily_rankings`.
- V31 exposes `freshness_gates_v1` and uses stale/unknown critical source data
  to keep candidates out of actionable daily ranking.
- V31 preserves source timestamps as `source_context_timestamps_v1` so
  fundamental/CANSLIM and account-context freshness can be scored without
  exposing sensitive values.
- Strategy Intelligence helpers have been extracted to `strategy_intelligence.py`.
- V31 decision and selected-contract payload schemas have been extracted to
  `v31_contracts.py` as `v31_decision_contract_schema_v1` and
  `selected_contract_v1`.
- Source-specific freshness fixtures now cover IBKR, TradingView technical,
  market regime, fundamental/CANSLIM, and account context.
- V31 schema fixtures now cover enabled recommendations, registry caps,
  selected-contract versioning, and the no-order flag.
- V31 surface compatibility fixtures now check API/GPT parity, selected-contract
  parity, daily-ranking GPT parity, dashboard visibility, and no-order flags.
- Executable-contract validation and blocker-priority helpers have been
  extracted to `decision_guards.py` with dedicated fixtures.
- Production readiness gates have been added through `production_readiness.py`
  and `/production_readiness` to block unsafe deploy config without exposing
  secrets.
- Redacted audit logging has been added through `audit_log.py`,
  `/audit_log_summary`, and V32 event hooks for decisions, follow-ups, and
  outcomes.
- Runtime retention policy has been added through `runtime_retention.py`,
  `/runtime_retention`, and configurable journal/audit limits.
- Storage isolation gates have been added through `storage_isolation.py` and
  `/storage_isolation`; commercial/multi-user scope is blocked unless durable
  storage, tenant isolation, and account isolation are explicitly enabled.
- Durable storage contract gates have been added through `durable_storage.py`
  and `/durable_storage_contract`; Supabase mode requires an explicit contract
  version, server-side URL/key presence, required journal/audit tables, RLS, and
  service-role-only grants.
- Supabase runtime adapter support has been added for V32 decision journals,
  outcome journals, and audit events; local JSON remains the default personal
  mode.
- Production read-auth middleware has been added for sensitive dashboards,
  GPT/status, decision, audit, readiness, storage, V31, and V32 surfaces while
  leaving health plus ingest/webhook token flows separate.
- Next implementation step: apply the durable storage SQL contract to a real
  Supabase/Postgres backend, configure `READ_ACCESS_TOKEN` and
  `RUNTIME_STORAGE_MODE=supabase`, and validate with a sanitized live IBKR
  snapshot.

Expected work:

- create shared schema modules for snapshots, contracts, blockers, and decisions,
- define canonical states,
- centralize executable option validation,
- centralize risk gating,
- centralize strategy playbook scoring and daily ranking,
- centralize source freshness validation,
- add a strategy research registry for `OBSERVED_PRACTICE`, `RADAR_ONLY`,
  `FORWARD_TEST`, and `PRODUCTION_PLAYBOOK` stages,
- reduce remaining historical decision paths in `app/main.py`,
- validate against a real sanitized IBKR snapshot,
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
  storage deployed in a real backend before production or multi-user use.

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
