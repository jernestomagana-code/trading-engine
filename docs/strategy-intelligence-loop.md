# Strategy Intelligence Loop

Version: `strategy_intelligence_loop_v1`

Status: operating contract for Morgan and the strategy layer.

This loop is the heart of Stock Ultimus: strategies should be dictated by the
best available technical, fundamental, CANSLIM, broker, account, volatility,
market-regime, and outcome information. The system should improve by learning
which rules work, which rules fail, and which elite-market practices can be
translated into safe, testable decision-support logic.

Stock Ultimus must not become a copy-trading engine, signal room, or automatic
execution system. Elite trader research is an input to rule design, not an
override of deterministic blockers.

## Mission

Maintain a living, evidence-backed strategy intelligence layer that:

- watches current market structure and strategy practice,
- studies how respected traders, institutional desks, exchanges, and educators
  frame risk and opportunity,
- converts useful ideas into testable internal hypotheses,
- validates those hypotheses with fixtures, forward tests, and outcome data,
- promotes only reviewed rules into the production playbook,
- keeps recommendations conservative, explainable, and manual-review only.

## Strategy Intelligence Inputs

| Input | Role | Required evidence |
| --- | --- | --- |
| IBKR data | Confirms executable contracts, spreads, greeks, positions, buying power, and account context. | Runtime snapshot with timestamps and selected contract data. |
| TradingView data | Confirms strategy-specific technical context across intraday and non-intraday timeframes. | Versioned alert payload and source timeframe. |
| Fundamental/CANSLIM data | Filters underlying quality, growth, event risk, and strategy eligibility. | Provider, timestamp, field mapping, pass/fail details. |
| Market regime data | Detects volatility, trend, breadth, rates, macro events, and liquidity windows. | Source timestamp and regime classification. |
| Elite practice research | Identifies high-quality strategy structures, risk conventions, and market adaptations. | Dated source, author/institution context, and implementation hypothesis. |
| Outcome journal | Measures whether prior candidates worked, failed, or were invalidated. | Stable decision ID, MFE, MAE, follow-up window, acted/ignored status. |

## Elite Practice Research Standard

Morgan may monitor:

- exchange and clearing education from Cboe, OCC/OIC, CME, Nasdaq, and similar
  market-structure sources,
- Interactive Brokers and broker documentation when broker mechanics matter,
- institutional research from asset managers, banks, volatility desks, and
  market-data firms,
- books, interviews, letters, or public material from respected traders and
  portfolio managers,
- high-quality practitioner material when it includes explicit risk controls,
  sizing logic, invalidation rules, and enough detail to become testable.

Morgan must not promote:

- unsupported social-media calls,
- screenshots of P/L without rules,
- guru claims without drawdown or risk context,
- strategies that rely on martingale sizing,
- strategies that need automatic execution to be safe,
- ideas that cannot be expressed as auditable blockers, thresholds, or
  experiment definitions.

The system may learn from "top trader" practices, but it must translate them
into Stock Ultimus rules. It should never blindly mirror another trader's
position, timing, allocation, or ticker recommendation.

## Research To Rule Funnel

Every new idea moves through these stages:

1. `OBSERVED_PRACTICE`: Morgan records the source, market context, strategy
   premise, and risk logic.
2. `RESEARCH_HYPOTHESIS`: the idea is rewritten as a testable Stock Ultimus
   hypothesis.
3. `RADAR_ONLY`: the idea can appear in research dashboards but cannot affect
   `ENTRY_READY`.
4. `FORWARD_TEST`: fixtures and paper/observation windows track whether the
   idea improves candidate quality.
5. `RULE_PROPOSAL`: Morgan proposes exact thresholds, blockers, score changes,
   and affected strategies.
6. `REVIEWED_RULE`: Athena, Atlas, Quinn, Ledger/Vega, and Sentinel review the
   safety, tests, data contracts, and compliance surface.
7. `PRODUCTION_PLAYBOOK`: the rule receives a version bump and becomes part of
   the canonical strategy playbook.

No idea may jump directly from research to `ENTRY_READY`.

## Intraday Vs Non-Intraday Strategy Families

Intraday families:

- Futures context.
- 0DTE or same-day index/ETF options, research-only until a separate risk model
  exists.
- Opening range, VWAP, momentum exhaustion, and macro-event windows.

Intraday requirements:

- same-session market data,
- matching TradingView timeframe,
- session/liquidity window,
- event calendar awareness,
- explicit max loss and invalidation model,
- no auto-execution,
- default `MANUAL_REVIEW` or `RADAR_ONLY` until governance is implemented.

Non-intraday families:

- Naked Put.
- Cash Secured Put.
- Covered Call.
- Iron Condor.
- Future debit/vertical/defined-risk strategies after research approval.

Non-intraday requirements:

- same-day technical and broker snapshots,
- executable option data,
- earnings/event checks,
- fundamental/CANSLIM filters when configured,
- account and concentration risk,
- outcome tracking by DTE, delta, spread, IV, and market regime.

## Daily Morgan Review

Morgan's scheduled review should produce:

- market regime summary,
- volatility and liquidity notes,
- intraday opportunity/risk context,
- non-intraday opportunity/risk context,
- strategy enable/disable/radar-only recommendations,
- parameter-change candidates,
- new research hypotheses,
- required data fields or provider gaps,
- tests and fixtures needed before behavior changes.

This review may update research notes. It may not change production readiness
without a reviewed implementation task.

## Decision Engine Relationship

The decision engine owns final state. Morgan owns research proposals.

Allowed influence:

- adjust score weights after reviewed version bump,
- add blockers after reviewed version bump,
- add required data fields after reviewed version bump,
- move strategies between `ENABLED`, `RADAR_ONLY`, and `DISABLED`,
- create research experiments and forward-test cohorts.

Forbidden influence:

- remove `WAIT_OPTIONS_DATA`,
- bypass technical confirmation,
- bypass account/risk blockers,
- mark incomplete contracts as ready,
- turn `ENTRY_READY` into an order instruction,
- publish third-party advice without compliance review.

## Required Artifacts

Each promoted rule must include:

- source note,
- hypothesis,
- affected strategy,
- data fields required,
- blocker or score change,
- fixtures,
- expected dashboard/GPT wording,
- `strategy_version` or `ruleset_version` bump,
- rollback condition,
- outcome metric to review later.

## First Implementation Backlog

- Maintain `docs/strategy_research_notes/` for Morgan observations and
  hypotheses.
- Maintain `config/strategy_registry.json` with `ENABLED`, `RADAR_ONLY`, and
  `DISABLED` states.
- Keep `scripts/validate_strategy_intelligence.py` passing in the integrity
  guard.
- Keep V31 registry caps active so `RADAR_ONLY` strategies cannot produce
  `ENTRY_READY`.
- Add freshness scoring for technical, fundamental, CANSLIM, IBKR, and regime
  inputs.
- Add daily ranking explainability: technical fit, fundamental fit, CANSLIM,
  option quality, risk fit, regime fit, and outcome evidence.
- Add intraday governance before any 0DTE or futures recommendation can become
  more than `RADAR_ONLY`.
- Add forward-test reports that compare proposed rules against current rules.
