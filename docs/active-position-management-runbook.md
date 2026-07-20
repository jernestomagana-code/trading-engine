# Active Position Management Runbook

Stock Ultimus now separates entry discovery from active position management.
The active-position engine reads broker positions, account context, technical
context, support/resistance, event risk, and gamma context when available. It
never authorizes execution.

## Endpoints

- `/v31_active_position_management`: full position-management payload.
- `/gpt_v31_active_positions`: compact GPT-friendly payload.
- `/v31_system_status`: includes `active_position_management_summary`.
- Local console `/active-positions`: same cockpit-local payload used by the
  `Posiciones activas` panel.

## Canonical Review States

- `MONITOR`: position is open and no deterministic action trigger is active.
- `TAKE_PROFIT_REVIEW`: review manual close/buy-back after premium capture.
- `ROLL_REVIEW`: review manual roll only if risk is not increased.
- `ASSIGNMENT_REVIEW`: review possible assignment or called-away outcome.
- `EXIT_REVIEW`: review defensive exit because the thesis may be damaged.
- `RISK_REVIEW`: review concentration, uncovered risk, event risk, or broken
  portfolio constraints.
- `NO_POSITION` / `EXPIRED_OR_CLOSED`: no active management action.

## Management Actions

- `NO_ACTION_RECOMMENDED`: best deterministic action is to wait.
- `REVIEW_CLOSE_OR_BUY_BACK`: manually inspect taking profit.
- `REVIEW_ROLL`: manually inspect roll alternatives.
- `REVIEW_ASSIGNMENT`: manually inspect assignment implications.
- `REVIEW_DEFENSIVE_EXIT`: manually inspect reducing or closing risk.
- `REVIEW_RISK`: manually inspect a risk blocker.
- `REFRESH_DATA`: context is missing or stale; refresh IBKR/technical data.

## Required Evidence

The engine can still produce a cautious output with partial data, but confidence
drops when these are missing:

- Fresh broker/account context.
- Position rows with ticker, type, quantity, strike/expiration for options.
- Option mark and entry credit for premium capture.
- Technical price, trend, support/resistance, and event risk.
- Gamma context such as gamma wall, call wall, put wall, zero gamma, or net
  gamma.

`GAMMA_CONTEXT_MISSING` is a warning, not a blocker. The engine must not invent
gamma levels.

## Operating Rule

Every payload must keep:

- `not_order_instruction: true`
- `execution_authorized: false`
- `can_operate: false`

Any trade, close, roll, or assignment decision remains a manual broker/TWS
review.

## V2 Operating Layer

The active-position payload now includes:

- `thesis`: saved or inferred position thesis, invalidation level, target,
  assignment preference, and thesis-risk flags.
- `scenario_analysis`: simple price-shock scenarios for review, using threshold
  and delta estimates when full greeks are unavailable.
- `portfolio_risk`: aggregate exposure by ticker/strategy, short-put notional,
  uncovered call count, concentration flags, and portfolio-level status.
- `battle_plan`: prioritized daily review steps.
- `management_outcome_template`: fields expected when journaling what the
  operator did after reviewing the recommendation.
- `management_alternatives`: a strategy-specific menu for every open
  position. Long stock compares hold, partial/full covered calls, protective
  put, collar, partial reductions, and full exit. Short puts, covered calls,
  uncovered calls, and long options receive their own close, roll,
  assignment, hedge, and risk-reduction paths.
- `recommendation`: one prioritized path for the operator, including hold/no
  change, its confidence, evidence-based reason, and preferred visible
  contract when applicable. Other paths remain secondary comparisons.
- `strategy_comparison` for long stock: estimates hold, reduce 25%, partial
  covered call, and matching partial collars from the current stock price
  across deep-downside, support, flat, resistance, and strong-upside cases.
  It reports one balanced winner plus separate leaders for capital protection,
  income/recovery, and upside preservation. Scenario weights are review
  weights, not probabilities.
- `option_alternatives_summary`: coverage of preserved option chains and the
  number of alternatives produced across the portfolio.
- `position_context_summary`: how many locally saved position contexts were
  applied to the current broker rows.

Every alternative has an independent data state such as
`READY_FOR_MANUAL_REVIEW`, `WAIT_OPTION_CHAIN`, `WAIT_MARKET_DATA`,
`WAIT_LIQUIDITY`, or `WAIT_UNDERLYING_PRICE`. Ready means that the alternative
has enough evidence to inspect manually; it never authorizes an order.

The bridge preserves the latest non-empty chain per ticker in
`runtime/active_position_option_chains_latest.json`. Daily open prioritizes all
symbols detected in open stock or option positions, in addition to the normal
watchlist, so a later unrelated scan does not erase their management choices.
For held stock, the call scan deliberately samples ITM, ATM, and OTM strikes
instead of limiting management to OTM calls. Overlay sizing is based on real
100-share lots; when 25% is not an exact number of contracts, both the lower
and upper feasible contract counts are compared.

The bridge also downloads daily historical bars for every held underlying even
when a live quote is already available. It stores the result in
`runtime/active_position_technical_latest.json` and calculates SMA 10/20/50,
RSI 14, ATR 14, trend, and 20/50-session support/resistance. Option premium is
never accepted as the underlying price. If directional evidence is incomplete,
the primary recommendation is to make no change until data is complete.
Broken support overrides the overlay comparison in favor of defensive
reduction review. Extreme stock concentration (60% or more of net liquidation)
does the same. A new covered call is not prioritized for an oversold asset, and
no stock reduction may leave an existing short call uncovered.

Local console review events are stored in
`runtime/active_position_management_journal.json`. These are process/outcome
records only; they are not broker instructions.

Editable thesis and entry/fill context is stored locally in
`runtime/active_position_contexts.json`. Use the console's
`Editar tesis y datos de entrada` section on each active-position card to save:

- thesis / entry reason;
- invalidation level;
- target or premium-capture plan;
- entry credit/price and entry date;
- roll or assignment plan.

The next active-position calculation merges this local context before
evaluating exits, scenarios, premium capture, thesis risk, and battle-plan
priority.

## Gamma Without Paid Source

Until a paid gamma provider is connected, use one of these paths:

- Manual JSON from the console: select any ticker with an open position and
  paste the same RSP-style payload containing spot, supports, resistances,
  expected move, call wall, put wall, zero gamma, bias, and notes. This writes
  `runtime/gamma_contexts.json`.
- Imported JSON from any future provider: keep the same schema and set `source`.
- IBKR open-interest approximation: possible later, but it must be labeled as
  OI context, not real dealer gamma.

The motor merges `runtime/gamma_contexts.json` into technical context before
position evaluation.

## State Changes And Performance

- `runtime/active_position_state_alerts.json`: tracks changes from one
  position-management state/action to another.
- `runtime/active_position_management_journal.json`: stores what the operator
  reviewed or decided.
- The console evaluates journal events against the current position payload and
  surfaces pending follow-up count.
