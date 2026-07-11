# TradingView Production Active Alerts

Last reviewed: 2026-07-11.

This is the single source of truth for the active TradingView alert set. The
project intentionally uses five consolidated TradingView alerts, not one alert
per condition, so it stays inside the active-alert limit and avoids noisy,
duplicated signals.

## Operating Decision

Five active TradingView alerts are sufficient for the current production
TradingView layer:

- Two futures alerts cover `MNQ1!` and `MES1!` intraday index-futures evidence.
- Three options-underlying alerts cover `QQQ`, `SPY`, and `VIX` context.
- Those five alerts emit the required logical event codes through Pine
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
| 1 | `MNQ1!` | `5m` | `stock_ultimus_intraday_futures_alerts_v1.pine` | `Any alert() function call` | Intraday futures evidence |
| 2 | `MES1!` | `5m` | `stock_ultimus_intraday_futures_alerts_v1.pine` | `Any alert() function call` | Intraday futures evidence |
| 3 | `QQQ` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Options-underlying evidence |
| 4 | `SPY` | `15m` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Options-underlying evidence |
| 5 | `VIX` | `1D` | `stock_ultimus_options_underlying_alerts_v1.pine` | `Any alert() function call` | Volatility-risk evidence |

Webhook:

```text
https://trading-engine-p097.onrender.com/technical_snapshot
```

Leave the TradingView message field at the default value for alert-function
alerts. The Pine scripts send the JSON payloads.

## Logical Coverage

The five active alerts emit sixteen required logical event codes:

- 10 futures event codes from `MNQ1!` and `MES1!`.
- 6 options-underlying event codes from `QQQ`, `SPY`, and `VIX`.

There are also four optional snapshot/heartbeat event definitions. They are
fallback diagnostics only and are not part of the active production set.

The backend scores, gates, deduplicates, persists, and quarantines these payloads.
The alert itself is evidence only and never an order instruction.

## Strategy Boundaries

TradingView is not the scanner for every possible ticker. In this project it is
the market/technical confirmation layer. Other strategy requirements live in the
engine:

- Best strike, delta, DTE, bid/ask, spread, and executable option-contract
  quality come from IBKR option-chain data and strategy-regime rules.
- CANSLIM quality is a filter/scoring input for equities and cash-secured-put
  candidates; it should improve ranking or block weak setups without requiring
  extra TradingView alerts.
- Large-cap or single-name opportunities should enter through the backend
  universe, data refresh, IBKR chains, and scoring. Do not add one TradingView
  alert per stock unless a measured coverage gap proves the five-alert layer is
  insufficient.
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
python3 scripts/check_daily_radar_contract.py
```

Check real ledger health after live alerts fire:

```bash
python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation
python3 scripts/run_market_open_readiness.py --market-closed-ok
```

The expected operating model is:

- `active_tradingview_alert_count=5`.
- `logical_event_coverage_count=16`.
- Local coverage validators expose this split as
  `production_active_alert_count` plus `logical_event_count`.
- `execution_authorized=false`.
- `not_order_instruction=true`.
