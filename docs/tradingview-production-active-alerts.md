# TradingView Production Active Alerts

Last reviewed: 2026-08-11.

This is the single source of truth for the active TradingView alert set. The
project intentionally uses seven consolidated TradingView alerts, not one alert
per condition, so it stays inside the active-alert limit and avoids noisy,
duplicated signals.

## Operating Decision

Seven active TradingView alerts are sufficient for the current production
TradingView layer:

- Two futures alerts cover `MNQ1!` and `MES1!` intraday index-futures evidence.
- Three options-underlying alerts cover `QQQ`, `SPY`, and `VIX` context.
- Two Chris IA alerts cover reversal confirmation for `USTEC.F` and `US500F`.
- Those seven alerts emit the required logical event codes through Pine
  `alert()` payloads.
- The backend handles scoring, setup-validity percentage, deduplication,
  quarantine, strategy gating, IBKR option-chain checks, and manual-review
  status.

The old per-condition alerts were useful during setup and testing, but they are
not needed for production while the consolidated Pine alert-function setup is
working. They should remain paused to avoid duplicate noise and active-alert
slot pressure.

## Active Set

| # | Symbol | Timeframe | Pine script | TradingView condition | Purpose |
| --- | --- | --- | --- | --- | --- |
| 1 | `MNQ1!` | `1m` | `stock_ultimus_intraday_futures_fast_v2.pine` | `Any alert() function call` | Fast intraday evidence with closed 5m context |
| 2 | `MES1!` | `1m` | `stock_ultimus_intraday_futures_fast_v2.pine` | `Any alert() function call` | Fast intraday evidence with closed 5m context |
| 3 | `QQQ` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Options-underlying evidence |
| 4 | `SPY` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Options-underlying evidence |
| 5 | `VIX` | `1D` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Volatility-risk evidence |
| 6 | `USTEC.F` | `15m` | `chris_ia_reversal_engine_pro.pine` | `Any alert() function call` | Chris IA NAS100 reversal evidence |
| 7 | `US500F` | `15m` | `chris_ia_reversal_engine_pro.pine` | `Any alert() function call` | Chris IA S&P 500 reversal evidence |

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

The FAST v2 consolidated alerts also emit one `SESSION_SNAPSHOT` heartbeat per
hour during the regular session when no actionable event fires on that bar.
This health event never reaches the phone, consumes no additional alert slot,
and lets the console distinguish a quiet market from a stopped TradingView
alert.

Notification channels for all seven project alerts:

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

The seven active alerts emit twenty required logical event codes:

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
  alert per stock unless a measured coverage gap proves the seven-alert layer is
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

- Operator-visible active set: `active_tradingview_alert_count=7`.
- Required logical coverage across all three contracts: `20`.
- Total logical definitions across all three contracts: `33`.
- The combined bundle reports all three contracts (`7` active / `20` required).
  Futures and options-underlying remain the two readiness-gating contracts.
  Chris IA is the supplemental reversal-confirmation contract: its health and
  missing events remain visible without blocking unrelated futures/options
  readiness when no Chris IA entry has occurred yet.
- The seven TradingView alerts were individually reviewed on 2026-07-26:
  webhook enabled and direct `Notify in app` disabled on every project alert.
- On 2026-08-11 the current FAST v2 Pine was saved and verified in TradingView
  with the required context fields and hourly heartbeat. The active `MNQ1!`
  and `MES1!` 1-minute alerts were edited and saved again so TradingView rebuilt
  their script snapshots; both remained active and their stale-version warning
  disappeared.
- `execution_authorized=false`.
- `not_order_instruction=true`.
