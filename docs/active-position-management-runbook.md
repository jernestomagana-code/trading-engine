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
- `position_context_summary`: how many locally saved position contexts were
  applied to the current broker rows.

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

- Manual JSON from the console: save ticker, gamma wall, call wall, put wall,
  zero gamma, and notes. This writes `runtime/gamma_contexts.json`.
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
