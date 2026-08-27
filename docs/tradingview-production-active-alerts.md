# TradingView Production Active Alerts

Last reviewed: 2026-08-27.

> **Current operator configuration (verified 2026-08-24).** The live TradingView
> cockpit uses four saved layouts and five Stock Ultimus managed alerts. This
> section is the
> source of truth for the current manual setup; the historical implementation
> notes below are retained for compatibility and audit context.

## Current active set

| # | Alert | Symbol | Timeframe | Role |
| --- | --- | --- | --- | --- |
| 1 | `FAST_V2_2 MNQ CONSOLIDATED` | `MNQ1!` | `1m` | Dynamic entry, prepare, invalidation, levels, and heartbeat payloads |
| 2 | `FAST_V2_2 MES CONSOLIDATED` | `MES1!` | `1m` | Dynamic entry, prepare, invalidation, levels, and heartbeat payloads |
| 3 | `OPTIONS QQQ CONSOLIDATED` | `QQQ` | `15m` | Dynamic long/short context and heartbeat |
| 4 | `OPTIONS SPY CONSOLIDATED` | `SPY` | `15m` | Dynamic long/short context and heartbeat |
| 5 | `OPTIONS VIX CONSOLIDATED` | `VIX` | `1D` | Dynamic elevated/normalized volatility context |

Paused by design: the six former FAST v2.2 explicit MNQ alerts, the accidental
unnamed consolidated duplicate, the explicit QQQ/VIX alerts, Chris IA, and generic legacy alerts. The three
RSI alerts visible in the account are unrelated operator alerts and were not modified.

Chris IA is retired as a supplemental setup layer. Its historical payloads remain
available for audit, but its absence or quarantine no longer blocks readiness.

## Saved layouts

| Layout | Symbol | Timeframe | Main script |
| --- | --- | --- | --- |
| `01 MNQ Entrada 1m` | `MNQ1!` | `1m` | `Stock Ultimus Intraday Futures FAST v2.2` |
| `02 USTEC Confirmacion 15m` | `USTEC.F` | `15m` | `Chris IA Decision Panel v4.4` |
| `03 QQQ Opciones 15m` | `QQQ` | `15m` | `Stock Ultimus Options Underlying Alerts v1` |
| `04 VIX Riesgo Diario` | `VIX` | `1D` | `Stock Ultimus Options Underlying Alerts v1` |

This is the single source of truth for the Stock Ultimus alerts managed in
TradingView. The live set uses consolidated alerts where TradingView exposes
`Any alert() function call`. MNQ and MES now each use one verified FAST v2.2
v23.0 consolidated alert with the production webhook and a 24/7 schedule.

## Historical implementation notes (not the current operator set)

The production TradingView layer recorded on 2026-08-20 was covered as follows:

- Six explicit FAST v2.2 alerts cover MNQ entry, prepare, and invalidation in
  both directions.
- One legacy consolidated FAST v2.1 alert remains active for MES until a
  verified FAST v2.2 consolidated condition can replace it.
- Six explicit options-underlying alerts cover QQQ/SPY long and short context
  plus VIX elevated and normalized risk.
- Three Chris IA v4.1 consolidated alerts cover `MNQ1!`, `USTEC.F`, and
  `US500F`.
- The backend handles scoring, setup-validity percentage, deduplication,
  quarantine, strategy gating, IBKR option-chain checks, and manual-review
  status.

The replaced Chris IA alerts and the old MNQ FAST v2.1 consolidated alert are
paused. The account is now at its 20-alert technical limit: 16 Stock Ultimus
managed slots plus four unrelated user alerts that were not modified.

## Historical managed-set snapshot

| # | Symbol | Timeframe | Pine script | TradingView condition | Slots | Purpose |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `MNQ1!` | `1m` | `stock_ultimus_intraday_futures_fast_v2.pine` | Six explicit `ENTRY`, `PREPARE`, `INVALIDATED` conditions | 6 | FAST v2.2 evidence with closed 5m context |
| 2 | `MES1!` | `1m` | `stock_ultimus_intraday_futures_fast_v2.pine` | Legacy FAST v2.1 `Any alert() function call` | 1 | Coverage retained while FAST v2.2 consolidation is blocked in the TV UI |
| 3 | `QQQ` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | LONG + SHORT explicit conditions | 2 | Options-underlying evidence |
| 4 | `SPY` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | LONG + SHORT explicit conditions | 2 | Options-underlying evidence |
| 5 | `VIX` | `1D` | `stock_ultimus_options_underlying_alerts_v1.pine` | Elevated + Normalized explicit conditions | 2 | Volatility-risk evidence |
| 6 | `MNQ1!` | `1m` | `chris_ia_reversal_engine_pro_v4_1_tv.pine` | `Any alert() function call` | 1 | Supplemental Chris IA timing evidence |
| 7 | `USTEC.F` | `15m` | `chris_ia_reversal_engine_pro_v4_1_tv.pine` | `Any alert() function call` | 1 | Chris IA v4.1 NAS100 reversal evidence |
| 8 | `US500F` | `15m` | `chris_ia_reversal_engine_pro_v4_1_tv.pine` | `Any alert() function call` | 1 | Chris IA v4.1 S&P 500 reversal evidence |

## Futures decision view (FAST v2.2)

The current futures Pine turns the `MNQ1!` and `MES1!` charts into a staged
decision view instead of showing isolated markers:

- `WAIT_QUALITY`: ADX or RVOL has not reached the existing production minimum.
- `ARMED_LONG` / `ARMED_SHORT`: price is within the configured ATR distance of
  ORB or VWAP and the baseline quality gate is already clear.
- `TRIGGERED_LONG` / `TRIGGERED_SHORT`: a confirmed one-minute close fired the
  existing ORB/VWAP event. This is the point to evaluate, not an order.
- `INVALIDATED`: price crossed the active plan's technical invalidation.

The middle-right panel now leads with `ACCIÓN AHORA` and explains `POR QUÉ`.
It separates the 1-minute price trigger from the 5-minute quality context,
shows the next trigger, missing confirmations, the conditional risk plan, and
the rule that an alert is evidence to evaluate rather than permission to trade.
Armed backgrounds and chart markers provide advance notice.
The default 10-bar cooldown suppresses repeated recross alerts that represent
the same setup rather than a new opportunity.

FAST v2.2 also sends explicit `direction`, `entry_price`, `tp1_price`, and
`tp2_price` fields. The backend maps continuous contracts correctly: `MES1!`
to the S&P 500/MES family and `MNQ1!` to the Nasdaq/MNQ family. Its quality
explanation uses the same four checks as the chart: ADX, RVOL, VWAP alignment,
and DMI direction. ADX/RVOL/VWAP remain mandatory; opposing DMI lowers the
visible quality score without silently discarding an otherwise valid trigger.

The Chris IA pane uses `CT BLOQ L/S` in orange for a high-scoring trigger that
still opposes the 60-minute trend or MTF majority. It is deliberately not named
`REBOTE` on the chart: a pattern score near 100 measures fit to the reversal
pattern, not probability of success or entry authorization.

## Live upgrade status (FAST v2.2 / Chris IA v4.1)

The repository versions now add a low-priority decision funnel without
relaxing the confirmed-entry rules:

- `PREPARE/WATCH` fires once when a setup becomes armed and carries the exact
  trigger, missing confirmations, priority, and bars armed.
- `SETUP_INVALIDATED/WATCH_CANCELED` closes the early-warning cycle when its
  conditions disappear before entry.
- FAST shows VWAP, DMI, next trigger, missing conditions, and armed duration;
  Chris IA shows the price trigger, missing checks, MTF balance, and next step.
- The backend records these events as `WATCH_ONLY` with low priority and does
  not send them through the mobile `ENTRY` channel.
- A confirmed `ENTRY` remains high priority and keeps the current manual-review
  and risk gates.

As of 2026-08-20 FAST v2.2 is compiled and visible on MNQ/MES. MNQ has the six
verified explicit v2.2 conditions; its old v2.1 alert is paused. MES retains its
legacy consolidated alert because TradingView does not currently expose
`Any alert() function call` for FAST v2.2. Chris IA v4.1 is compiled, visible,
and active through one consolidated alert on each of USTEC.F and US500F; the
two previous Chris alerts are paused.

As of 2026-08-24 this historical arrangement has been superseded: MNQ and MES
each have one active FAST v2.2 v23.0 consolidated alert using `Any alert()
function call` and the production webhook.

Webhook:

```text
https://trading-engine-p097.onrender.com/technical_snapshot
```

Leave the TradingView message field at the default value for alert-function
alerts. The Pine scripts send the JSON payloads.

Important: TradingView stores a snapshot of the Pine script when an alert is
created. Saving a newer Pine version does not update an already-running alert.
After changing either production Pine script, edit and save each affected
project alert so TradingView rebuilds it from the current chart/script version;
if the alert cannot be refreshed in place, pause the old alert and create its
replacement before removing it. Never leave both versions active because they
would send duplicate events.

The current MES/MNQ futures payload must include `session_state`,
`premarket_high`, `premarket_low`, `major_event_window`, and
`risk_daily_status`. A real signal that lacks them is preserved in quarantine,
shown in the console, and cannot become `ENTRY_READY` until the project alert
has been refreshed to the current Pine version.

The FAST consolidated condition emits one `SESSION_SNAPSHOT` heartbeat per
hour during the regular session when no actionable event fires on that bar.
This is active on the retained MES alert. The MNQ explicit-condition fallback
does not carry the heartbeat until TradingView exposes the consolidated FAST
v2.2 condition; entry/prepare/invalidation coverage remains active.

Notification channels for all Stock Ultimus-managed alerts:

- `Webhook URL`: enabled and pointed to the production endpoint above.
- `Notify in app`: disabled. Direct TradingView mobile pushes would bypass the
  Stock Ultimus `ENTRY`-only filter.
- `Show toast notification`: disabled unless the operator explicitly needs a
  local TradingView-only visual reminder.
- Mobile delivery: handled centrally by Stock Ultimus/Pushover after event
  classification. `WATCH`, `REBOTE`, risk, health, and diagnostic events remain
  in the ledger and console without reaching the phone.
- A TradingView event named `ENTRY` is still only evidence. If the backend
  classifies it as `WATCH_ONLY` because confirmation, risk, portfolio, or
  capacity fails, it appears in the daily futures history with its levels and
  reason but correctly does not reach the phone.

## Logical Coverage

The managed alerts cover twenty required logical event codes:

- 10 futures event codes from `MNQ1!` and `MES1!`.
- 6 options-underlying event codes from `QQQ`, `SPY`, and `VIX`.
- 4 required Chris IA entry event codes from `USTEC.F` and `US500F`.

The three coverage contracts define 33 logical event codes in total. In
addition to the 20 required codes, the remaining codes represent optional
snapshot/heartbeat diagnostics and Chris IA `WATCH`/`REBOTE` observations. They
may be stored and shown in the console, but they do not add TradingView alert
slots and do not generate the project's filtered mobile `ENTRY` notification.

The backend scores, gates, deduplicates, persists, and quarantines these payloads.
The alert itself is evidence only and never an order instruction.

## Strategy Boundaries

TradingView is not the scanner for every possible ticker. In this project it is
the market/technical confirmation layer. Other strategy requirements live in the
engine:

- Best strike, delta, DTE, bid/ask, spread, IV/volatility richness, and
  executable option-contract quality come from IBKR option-chain data and
  strategy-regime rules. For naked puts, the backend must avoid promoting
  contracts where the option premium is cheap versus IV Rank/Percentile,
  IV/HV spread, or absolute IV thresholds.
- CANSLIM quality is a filter/scoring input for equities and cash-secured-put
  candidates; it should improve ranking or block weak setups without requiring
  extra TradingView alerts.
- Large-cap or single-name opportunities should enter through the backend
  universe, data refresh, IBKR chains, and scoring. Do not add one TradingView
  alert per stock unless a measured coverage gap proves the managed layer is
  insufficient.
- The IBKR option layer ranks underlyings dynamically before opening chains.
  It should select only the highest-priority subset per cycle using core
  context, operator priority, positions, large-cap/liquidity tier, technical
  score/confirmation, and CANSLIM pass/score. Chain usage is capped by
  `IBKR_MAX_OPTION_SYMBOLS_PER_RUN` and
  `IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN`.
- Context-only symbols such as `TLT` support market/rates context but should
  not consume option-chain budget unless priority, position, technical, or
  CANSLIM confirmation promotes them.
- `ENTRY_READY` requires the complete backend gate, not merely a TradingView
  event.

## Not In The Active Set

Keep these paused unless a documented fallback is needed:

- Old futures per-condition alerts such as `MNQ_ORB_*`, `MNQ_VWAP_*`,
  `MES_ORB_*`, `MES_VWAP_*`, and `*_RISK_INVALIDATION_*`.
- Old options-underlying per-condition alerts such as `QQQ_TECH_CONFIRM_*`,
  `SPY_TECH_CONFIRM_*`, and `VIX_RISK_*`.
- RSI crossing alerts.
- Generic price-crossing alerts.
- Duplicate manual-test alerts.
- Snapshot/heartbeat alerts unless active-alert capacity is explicitly expanded.

If a legacy alert fires anyway, it should be treated as non-production evidence.
Unknown or stale payloads should be quarantined and must not feed an
`ENTRY_READY` decision.

## Verification

Validate the local logical-event contracts:

```bash
python3 scripts/print_tradingview_alert_setup.py --validate
python3 scripts/print_tradingview_options_underlying_alert_setup.py --validate
python3 scripts/print_tradingview_alert_setup.py --coverage config/tradingview_chris_ia_alert_coverage_v1.json --validate
python3 scripts/check_daily_radar_contract.py
```

Check real ledger health after live alerts fire:

```bash
python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation
python3 scripts/run_market_open_readiness.py --market-closed-ok
```

The expected operating model is:

- Operator-visible Stock Ultimus set: 8 logical source rows using 16 active
  technical-alert slots. Four unrelated user alerts fill the account limit of
  20.
- Required logical coverage across all three contracts: `20`.
- Total logical definitions across all three contracts: `33`.
- The combined bundle reports all three contracts and `20` required logical
  event codes; slot count is tracked separately from logical source rows.
  Futures and options-underlying remain the two readiness-gating contracts.
  Chris IA is the supplemental reversal-confirmation contract: its health and
  missing events remain visible without blocking unrelated futures/options
  readiness when no Chris IA entry has occurred yet.
- The seven-alert configuration was individually reviewed on 2026-07-26:
  webhook enabled and direct `Notify in app` disabled on every project alert.
- On 2026-08-11 the current FAST v2 Pine was saved and verified in TradingView
  with the required context fields and hourly heartbeat. The active `MNQ1!`
  and `MES1!` 1-minute alerts were edited and saved again so TradingView rebuilt
  their script snapshots; both remained active and their stale-version warning
  disappeared.
- On 2026-08-12 FAST v2.1 added the staged decision panel and corrected the
  backend continuous-contract direction/family mapping. Because active alerts
  retain a Pine snapshot, both futures chart studies and their active alerts
  must be saved/rebuilt from v2.1 before these changes are live in TradingView.
- On 2026-08-20 Chris IA v4.1 replaced the old USTEC.F and US500F snapshots.
  Both consolidated alerts are active with webhook delivery, and the previous
  Chris alerts are paused.
- On 2026-08-20 FAST v2.2 compiled and replaced the broken/duplicate chart
  instance. MNQ uses six verified explicit v2.2 alerts and its old consolidated
  v2.1 alert is paused. MES keeps the legacy consolidated alert until the TV
  alert dialog exposes `Any alert() function call` for FAST v2.2.
- On 2026-08-24 TradingView exposed the consolidated condition on both futures.
  `FAST_V2_2 MNQ CONSOLIDATED` and `FAST_V2_2 MES CONSOLIDATED` are active; the
  superseded explicit and legacy alerts are paused.
- `execution_authorized=false`.
- `not_order_instruction=true`.
