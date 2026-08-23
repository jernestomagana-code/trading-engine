# TradingView Options Underlying Alert Set

This is the minimum TradingView confirmation layer for options strategies.
IBKR remains the candidate source for option chains; TradingView confirms the
underlying technical context for SPY, QQQ, and VIX. These alerts are evidence
only and never authorize orders.

The six active conditions here are enough for the current options-underlying
TradingView layer. Single-name large-cap, CANSLIM, best strike, best delta, and
best DTE decisions must come from the backend universe, IBKR chain evidence, and
strategy-regime rules, not from recreating one TradingView alert per ticker.

## Production Active Alerts

Keep these six options-underlying conditions active in TradingView:

| Active alert | Symbol | Timeframe | TradingView condition | Role |
| --- | --- | --- | --- | --- |
| `Stock Ultimus Underlying Tech Confirm Long/Short` | `QQQ` | `15m` | Two explicit conditions | QQQ options evidence |
| `Stock Ultimus Underlying Tech Confirm Long/Short` | `SPY` | `15m` | Two explicit conditions | SPY options evidence |
| `Stock Ultimus VIX Risk Elevated/Normalized` | `VIX` | `1D` | Two explicit conditions | Volatility-risk evidence |

Use webhook `https://trading-engine-p097.onrender.com/technical_snapshot`.
The live conditions use the production webhook and the script's alertcondition
messages. They are evidence only and never order instructions.

## Logical Event Coverage

The six active conditions cover these six decision-making event codes. This is
the verified fallback because the saved TradingView Pine snapshot does not
expose `Any alert() function call`:

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

Current verified setup:

- Add the Pine script to `QQQ` on the `15m` chart.
- Create `Underlying Tech Confirm Long` and `Underlying Tech Confirm Short`.
- Use webhook `https://trading-engine-p097.onrender.com/technical_snapshot`.
- Repeat LONG/SHORT for `SPY` on `15m`.
- On `VIX` `1D`, create `VIX Risk Elevated` and `VIX Risk Normalized`.

This consumes six active-alert slots. Replace it with three consolidated alerts
only after a saved Pine snapshot exposes and successfully creates a verified
`Any alert() function call` condition.

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
