# TradingView Options Underlying Alert Set

This is the minimum TradingView confirmation layer for options strategies.
IBKR remains the candidate source for option chains; TradingView confirms the
underlying technical context for SPY, QQQ, and VIX. These alerts are evidence
only and never authorize orders.

The three active alerts here are enough for the current options-underlying
TradingView layer. Single-name large-cap, CANSLIM, best strike, best delta, and
best DTE decisions must come from the backend universe, IBKR chain evidence, and
strategy-regime rules, not from recreating one TradingView alert per ticker.

## Production Active Alerts

Keep only these three options-underlying alerts active in TradingView:

| Active alert | Symbol | Timeframe | TradingView condition | Role |
| --- | --- | --- | --- | --- |
| `Stock Ultimus Options Underlying Alerts v1` | `QQQ` | `15m` | `Any alert() function call` | Consolidated QQQ options evidence |
| `Stock Ultimus Options Underlying Alerts v1` | `SPY` | `15m` | `Any alert() function call` | Consolidated SPY options evidence |
| `Stock Ultimus Options Underlying Alerts v1` | `VIX` | `1D` | `Any alert() function call` | Consolidated volatility-risk evidence |

Use webhook `https://trading-engine-p097.onrender.com/technical_snapshot`.
Leave the TradingView message field at the default value for alert-function
alerts. The Pine script sends the JSON payload itself.

## Logical Event Coverage

The three active alerts above dynamically emit these six decision-making event
codes. Do not create these as separate active alerts unless the consolidated
alert-function setup is unavailable:

| Event code | Symbol | Timeframe | Role |
| --- | --- | --- | --- |
| `QQQ_TECH_CONFIRM_LONG_15M` | `QQQ` | `15m` | Options confirmation |
| `QQQ_TECH_CONFIRM_SHORT_15M` | `QQQ` | `15m` | Options confirmation |
| `SPY_TECH_CONFIRM_LONG_15M` | `SPY` | `15m` | Options confirmation |
| `SPY_TECH_CONFIRM_SHORT_15M` | `SPY` | `15m` | Options confirmation |
| `VIX_RISK_ELEVATED_D` | `VIX` | `1D` | Volatility risk |
| `VIX_RISK_NORMALIZED_D` | `VIX` | `1D` | Volatility risk |

Leave these optional snapshot alerts paused unless the active-alert plan has
spare capacity. They provide context, but they do not directly change an entry,
exit, or risk decision:

| Alert name | Symbol | Timeframe | Condition hint | Role |
| --- | --- | --- | --- | --- |
| `QQQ_REGIME_SNAPSHOT_15M` | `QQQ` | `15m` | Underlying Regime Snapshot | Heartbeat/snapshot |
| `SPY_REGIME_SNAPSHOT_15M` | `SPY` | `15m` | Underlying Regime Snapshot | Heartbeat/snapshot |

Use this Pine source:

```text
tradingview/stock_ultimus_options_underlying_alerts_v1.pine
```

## Recommended TradingView Setup

Prefer alert-function alerts instead of manually pasted JSON per condition:

- Add the Pine script to `QQQ` on the `15m` chart.
- Create one alert with condition `Stock Ultimus Options Underlying Alerts v1`
  / `Any alert() function call`.
- Use webhook `https://trading-engine-p097.onrender.com/technical_snapshot`.
- Leave the alert message as TradingView's default for alert-function alerts;
  the script sends the JSON payload itself.
- Repeat for `SPY` on `15m`.
- Repeat for `VIX` on `1D`.

The generated setup-message commands below remain useful as a fallback when a
plan requires individual alert conditions or for validating expected payload
shape. The fallback consumes six active-alert slots instead of three, so it is
not the preferred production setup.

## Required Pine Plot Names

- `VWAP`
- `ORH`
- `ORL`
- `ADX`
- `ATR`
- `RVOL`
- `PMH`
- `PML`
- `STOP`
- `TARGET`
- `RSI`
- `EMA_FAST`
- `EMA_SLOW`
- `TREND_STRENGTH`

## Commands

Validate the matrix:

```bash
python3 scripts/print_tradingview_options_underlying_alert_setup.py --validate
```

Print all setup messages:

```bash
python3 scripts/print_tradingview_options_underlying_alert_setup.py
```

Print one exact message:

```bash
python3 scripts/print_tradingview_options_underlying_alert_setup.py --event-code QQQ_TECH_CONFIRM_LONG_15M --messages-only
```

Check health:

```bash
python3 scripts/run_tradingview_options_underlying_alert_health.py --market-closed-ok
```

Audit production:

```bash
python3 scripts/run_tradingview_options_underlying_production_audit.py --market-closed-ok
```

## Policy

Do not recreate old RSI crossing alerts. RSI is now a field inside the enriched
payload together with VWAP, ADX, ATR, RVOL, EMAs, trend state, market regime,
logical stop, logical target, raw payload, and idempotency hash.

Legacy, duplicate, RSI, crossing-price, or generic text-message alerts should
remain paused. If one fires anyway, the backend persists it in the TradingView
ledger but marks it `QUARANTINED` and does not feed it into the decision engine.

Options `ENTRY_READY` requires reviewable IBKR chain evidence plus this
underlying TradingView confirmation layer. Until then, options stay in manual
review/evidence collection mode.
