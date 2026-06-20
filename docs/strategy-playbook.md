# Stock Ultimus Strategy Playbook

Version: `strategy_playbook_v1`

Status: draft contract for V31/V32 implementation.

Stock Ultimus is a decision-support system. This playbook is the core contract
for how daily strategy candidates should be collected, validated, blocked,
ranked, and explained. It does not authorize automatic order execution.

The playbook is fed by technical, fundamental, CANSLIM, broker, account,
volatility, market-regime, and outcome information. Strategy changes should come
from the Strategy Intelligence Loop, where Morgan researches current market
practice and elite trader/institutional approaches, then converts useful ideas
into testable Stock Ultimus rules.

## Source References

The playbook is aligned with the current local contracts and with external
options-risk references:

- FINRA options overview:
  <https://www.finra.org/investors/investing/investment-products/options>.
  Options sellers accept assignment obligations, options use leverage, and
  options trading requires broker approval.
- OCC options disclosure:
  <https://www.optionseducation.org/optionsoverview/options-disclosure-document>.
  Options trading requires review of standardized options risks before use.
- Interactive Brokers TWS API option-computation documentation:
  <https://interactivebrokers.github.io/tws-api/option_computations.html>.
  Option greeks such as delta require option and underlying market-data
  subscriptions.
- Cboe/options-education material on iron condor strategy:
  <https://www.cboe.com/insights/posts/iron-condor-options-strategy/>.
  Iron condors are neutral/range strategies with defined risk and limited
  reward.

These references are guardrails. Stock Ultimus rules must be implemented as
versioned, testable internal logic.

See also `docs/strategy-intelligence-loop.md` for the research-to-rule process
that governs how new strategies, thresholds, and market-practice improvements
enter this playbook.

## Strategy Intelligence Principles

- Strategies are living rules, not static opinions.
- Technical, fundamental, CANSLIM, IBKR, account, volatility, and outcome data
  should all influence ranking when they are available and fresh.
- Missing or stale data should produce explicit blockers or lower confidence,
  not optimistic readiness.
- Elite trader and institutional research may inspire rules, but it must be
  converted into auditable hypotheses, fixtures, and versioned thresholds before
  affecting production readiness.
- Intraday strategies require stricter freshness, session, event, max-loss, and
  governance rules than non-intraday strategies.
- Outcome data should eventually decide whether a rule remains, changes, or is
  disabled.

## Daily Recommendation Model

Daily output must be a ranked list of decision candidates, not an instruction to
trade.

Allowed recommendation labels:

- `NO_ACTION`: no usable setup exists.
- `WAIT_MARKET`: market/session context blocks evaluation.
- `WAIT_ACCOUNT_CONTEXT`: account, margin, position, or buying-power context is
  missing.
- `WAIT_OPTIONS_DATA`: executable option contract data is missing or invalid.
- `WAIT_TECHNICAL`: option data is executable but technical confirmation is
  absent or stale.
- `RISK_BLOCKED`: a deterministic risk rule blocks the setup.
- `MANUAL_REVIEW`: all mechanical checks pass, but human validation is still
  required.
- `ENTRY_READY`: candidate is ready for manual review only.

No output may use words such as buy, sell, place, submit, execute, or order as a
command. Wording should be framed as "candidate", "setup", "review", or
"validation required".

## Canonical Data Sources

| Source | Purpose | Required freshness | Blocks when stale |
| --- | --- | --- | --- |
| IBKR market data | underlying price, bid/ask, greeks, option chains, positions | same session; option quotes preferably under 15 minutes during market hours | yes, for executable recommendations |
| IBKR account context | buying power, margin, positions, share count, concentration | same session; must be explicit if delayed | yes |
| TradingView | technical strategy context, trend, score, support/resistance, RSI, ADX, range state | same trading day for daily strategies; intraday strategies require matching timeframe | yes, after options data passes |
| Fundamental provider | earnings date, CANSLIM or growth/quality fields, market cap/liquidity classification | latest available vendor update; earnings/event data must be checked daily | yes when a required field is configured |
| Market regime inputs | VIX, index trend, session status, macro/event calendar | same session for VIX/session; current week for macro calendar | yes for regime-sensitive strategies |
| Outcome journal | prior candidates, acted/ignored status, MFE, MAE, realized outcome | append-only after every candidate lifecycle update | no for current safety, yes for parameter changes |

Internet-sourced data may enrich a decision only when the provider, timestamp,
and field mapping are preserved in the snapshot. Unattributed web text must not
override deterministic blockers.

## Universal Snapshot Fields

Every strategy candidate should include:

- `ticker`
- `strategy`
- `decision_version`
- `strategy_version`
- `ruleset_version`
- `snapshot_version`
- `source_timestamps`
- `underlying_price`
- `market_session`
- `technical`
- `fundamental`
- `account_context`
- `selected_contract` or `selected_structure`
- `risk`
- `main_blocker`
- `blockers`
- `required_missing_fields`
- `score_components`
- `explanation`
- `manual_review_required`

## Universal Executable Option Gate

For single-leg option strategies, `selected_contract` is executable only when
all fields below are present and valid:

- `strike`
- `expiration`
- `dte`
- `bid`
- `ask`
- `mid`
- `spread`
- `spread_pct`
- `delta`

For multi-leg strategies, every leg must pass the same contract gate, and the
structure must include net credit/debit, width, max risk, max reward estimate,
and breakeven estimates when calculable.

If the technical signal is confirmed but executable option data is incomplete,
the decision must be `WAIT_OPTIONS_DATA`, not `WAIT_TECHNICAL`.

## Universal Risk Blockers

Apply these before marking any setup `ENTRY_READY`:

- `BROKER_DATA_STALE`
- `ACCOUNT_CONTEXT_MISSING`
- `INSUFFICIENT_BUYING_POWER`
- `MARGIN_IMPACT_UNKNOWN`
- `POSITION_CONTEXT_MISSING`
- `CONCENTRATION_LIMIT_EXCEEDED`
- `CORRELATION_LIMIT_EXCEEDED`
- `EVENT_RISK_ACTIVE`
- `EARNINGS_SOON`
- `OPTION_DATA_INCOMPLETE`
- `OPTION_SPREAD_TOO_WIDE`
- `LOW_OPTION_VOLUME`
- `LOW_OPEN_INTEREST`
- `DELTA_OUT_OF_RANGE`
- `DTE_OUT_OF_RANGE`
- `TECHNICAL_NOT_CONFIRMED`
- `FUNDAMENTAL_FILTER_FAILED`
- `MANUAL_REVIEW_REQUIRED`

Risk blockers are deterministic. GPT, dashboard text, TradingView labels, or
manual notes may explain a blocker but may not remove it.

## Ranking Model

Only candidates that are not blocked by `WAIT_MARKET`, `WAIT_ACCOUNT_CONTEXT`,
`WAIT_OPTIONS_DATA`, or `RISK_BLOCKED` may be ranked for same-day manual review.
V31 exposes the first version as `strategy_score_components_v1`.
V31 daily ranking is exposed as `strategy_daily_ranking_v1` through
`/v31_daily_rankings` and `/gpt_v31_daily_rankings`. It separates candidates
into `top_manual_review`, `watchlist`, `blocked`, and `research_only`.
V31 also exposes `freshness_gates_v1` for IBKR snapshot, TradingView technical,
market/regime, fundamental/CANSLIM, and account-context freshness. Critical
stale or unknown freshness blocks a candidate from actionable daily ranking even
when its individual decision state remains auditable.
V31 preserves these source timestamps under `source_context_timestamps_v1`,
excluding sensitive balances, account identifiers, and position details from the
canonical decision payload.

Recommended score bands:

- `90-100`: strongest manual-review candidate; all required data fresh and
  aligned.
- `75-89`: valid but lower-priority candidate.
- `60-74`: watchlist or manual-review only when portfolio context favors it.
- `<60`: no-action or research-only.

Recommended score components:

| Component | Weight | Notes |
| --- | ---: | --- |
| Technical fit | 25 | Strategy-specific trend/range/RSI/ADX/support/resistance rules. |
| Option quality | 25 | Bid/ask, spread, delta, DTE, volume, open interest, greeks availability. |
| Risk fit | 25 | Buying power, margin, concentration, correlation, event risk. |
| Fundamental fit | 15 | CANSLIM/growth/quality/event filters when applicable. |
| Outcome evidence | 10 | Historical forward-test score once V32 data is durable. |

Until V32 outcome data is durable, `outcome evidence` should be scored as
neutral and clearly labeled as not yet statistically validated.

## Strategy: Naked Put

Purpose: identify cash-secured or margin-supported put-selling candidates where
the user would be willing to own the underlying if assigned.

Required data:

- IBKR: underlying price, put chain, bid/ask/mid, spread, delta, DTE, volume,
  open interest when available, buying power or margin impact.
- TradingView: bullish or constructive trend, score, support proximity, RSI,
  ADX, event-risk fields.
- Fundamental: earnings date, CANSLIM/growth/quality filter when configured,
  minimum liquidity/market-cap classification.
- Account: available cash or margin, existing exposure to ticker/sector,
  assignment capacity.

Readiness rules:

- Put must be out of the money unless explicitly marked as research-only.
- DTE should default to the configured Naked Put readiness range.
- Delta should default to the configured Naked Put readiness range.
- Bid/ask spread must be inside readiness threshold.
- Technical context must be bullish or constructive and not event-blocked.
- Fundamental filter must pass when supplied and configured as required.
- Assignment outcome must be acceptable for manual review.

Primary blockers:

- `WAIT_OPTIONS_DATA` for missing executable put fields.
- `WAIT_TECHNICAL` when put data is complete but trend/support confirmation is
  absent.
- `RISK_BLOCKED` for earnings, insufficient buying power, concentration, wide
  spread, poor liquidity, or failed fundamental filter.

`ENTRY_READY` wording:

`Naked Put candidate ready for manual validation; assignment, margin, earnings,
spread, and portfolio concentration must be reviewed before any trade.`

## Strategy: Cash Secured Put

Purpose: stricter Naked Put variant where full assignment cash must be available
or intentionally reserved.

Additional required data:

- Cash required for assignment: `strike * 100 * contracts`.
- Available cash or explicitly approved reserve.
- Existing cash-reserve commitments.

Readiness rules:

- All Naked Put rules apply.
- Required cash must be available after existing obligations.
- Do not mark ready from margin-only capacity.

Primary blockers:

- `WAIT_ACCOUNT_CONTEXT` when cash availability is missing.
- `RISK_BLOCKED` when assignment cash is insufficient.

## Strategy: Covered Call

Purpose: identify income or position-management candidates against existing
long stock.

Required data:

- IBKR: current position, share count, cost basis when available, call chain,
  executable call contract fields, delta, DTE, spread, volume/open interest.
- TradingView: neutral, extended, resistance-near, bearish, or management
  context depending on intent.
- Fundamental/event: earnings date, corporate actions, dividend/ex-date when
  available.
- Account: tax/account type notes when later implemented.

Readiness rules:

- Position must exist and share count must cover the proposed contract count.
- Call should be out of the money unless explicitly marked as management-only.
- Delta and DTE must be inside configured Covered Call readiness ranges.
- Assignment outcome must be acceptable for manual review.
- Earnings/dividend/corporate-action risk must not be silently ignored.

Primary blockers:

- `WAIT_ACCOUNT_CONTEXT` when position/share count is missing.
- `WAIT_OPTIONS_DATA` for missing executable call fields.
- `WAIT_TECHNICAL` when call data is complete but covered-call context is not
  confirmed.
- `RISK_BLOCKED` for uncovered shares, unacceptable assignment, earnings,
  wide spread, poor liquidity, or event risk.

`ENTRY_READY` wording:

`Covered Call candidate ready for manual validation; assignment outcome,
existing position intent, event risk, and upside tradeoff must be reviewed.`

## Strategy: Iron Condor

Purpose: identify defined-risk, neutral/range candidates where volatility,
range, and liquidity support a short premium structure.

Required data:

- IBKR: four option legs, same expiration, bid/ask/mid/spread/delta for each
  leg, net credit, width, max risk estimate, max reward estimate.
- TradingView: neutral/range classification, RSI near middle band, low ADX,
  no active breakout.
- Market regime: VIX or equivalent volatility context, IV rank when available.
- Risk: max loss, portfolio exposure, same-underlying concentration, event risk.

Readiness rules:

- All legs must pass executable option gates.
- Structure must be same-expiration and defined-risk.
- Short deltas must sit inside configured range.
- Net credit must meet minimum credit-to-width threshold.
- Range and volatility context must be confirmed.
- No earnings or major event risk unless strategy is explicitly research-only.

Primary blockers:

- `WAIT_OPTIONS_DATA` for any incomplete leg or missing net-risk fields.
- `WAIT_TECHNICAL` when structure is executable but range/neutral confirmation is
  absent.
- `RISK_BLOCKED` for low/high VIX outside rules, breakout state, wide spreads,
  insufficient credit, event risk, or concentration.

`ENTRY_READY` wording:

`Iron Condor candidate ready for manual validation; max loss, breakevens,
volatility regime, exit plan, and event calendar must be reviewed.`

## Strategy: Futures Intraday

Purpose: track intraday futures context separately from options strategies.

Required data:

- TradingView: strategy context `FUTURES`, timeframe, trend, score, VWAP,
  support/resistance, range/breakout state.
- Market/session: contract/session state, liquidity window, macro-event window.
- Risk: intraday loss limit, max contracts, stop/invalidations if later modeled.

Readiness rules:

- Futures signals must not reuse CANSLIM.
- Futures signals must not mark options `ENTRY_READY`.
- Until a separate futures risk model exists, outputs remain `MANUAL_REVIEW` or
  `WAIT_TECHNICAL`, never auto-actionable.

Primary blockers:

- `WAIT_MARKET` outside configured session/liquidity windows.
- `RISK_BLOCKED` near macro events or when risk profile is missing.
- `MANUAL_REVIEW` until futures-specific risk governance is implemented.

## Strategy: CANSLIM Filter

Purpose: provide a fundamental/growth filter for equity and equity-option
strategies. It is not a standalone trade authorization.

Required data:

- CANSLIM pass/fail or score.
- Source and timestamp.
- Earnings/event fields.
- Optional growth/relative-strength/quality details when provider supports it.

Readiness rules:

- Missing CANSLIM data should be `NOT_PROVIDED` unless the strategy explicitly
  marks it required.
- Failed CANSLIM data blocks strategies that require the filter.
- Passing CANSLIM data may improve ranking but may not bypass option, technical,
  or risk blockers.

Primary blockers:

- `FUNDAMENTAL_FILTER_FAILED`
- `CANSLIM_BLOCKED`
- `CANSLIM_SCORE_BELOW_MIN`

## Daily Workflow

1. Load market/session state.
2. Load IBKR account, positions, underlying prices, and option chains.
3. Load TradingView technical snapshots by ticker and strategy context.
4. Load fundamental/event inputs with source timestamps.
5. Normalize all inputs into the canonical snapshot contract.
6. Build strategy candidates.
7. Apply executable option gates.
8. Apply technical gates.
9. Apply fundamental and event gates.
10. Apply account/risk gates.
11. Assign canonical decision and blockers.
12. Rank only candidates eligible for manual review.
13. Publish dashboard/GPT payloads from the same decision object.
14. Journal candidates and later outcomes for V32 learning.

## Implementation Requirements

- Strategy behavior changes require a `strategy_version` or `ruleset_version`
  bump.
- New source fields require snapshot contract documentation and fixture updates.
- Every blocker state must have a fixture or guard test before release.
- Dashboard and GPT endpoints must consume the same canonical decision payload.
- Runtime snapshots and fixtures must be sanitized before commit.
- No code path may submit, place, or transmit broker orders automatically.

## Open Implementation Tasks

- Extract canonical strategy schemas and blocker helpers from `app/main.py`.
- Add a data-freshness validator shared by dashboard, GPT, and monitor routes.
- Add a ranking function with visible score components.
- Add fundamental-provider adapters with explicit source timestamps.
- Add account risk profile fields: max capital per trade, max sector exposure,
  max contracts, and manual-review overrides.
- Extend fixtures for Cash Secured Put, Iron Condor multi-leg completeness,
  stale data, event risk, and failed fundamental filter.
- Connect V32 outcome metrics to future parameter-review reports.
