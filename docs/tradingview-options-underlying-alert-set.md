# TradingView Options Underlying Alert Set

This is the minimum TradingView confirmation layer for options strategies.
IBKR remains the candidate source for option chains; TradingView confirms the
underlying technical context for SPY, QQQ, and VIX. These alerts are evidence
only and never authorize orders.

## Alerts

Create these eight alerts:

| Alert name | Symbol | Timeframe | Condition hint | Role |
| --- | --- | --- | --- | --- |
| `QQQ_TECH_CONFIRM_LONG_15M` | `QQQ` | `15m` | Underlying Tech Confirm Long | Options confirmation |
| `QQQ_TECH_CONFIRM_SHORT_15M` | `QQQ` | `15m` | Underlying Tech Confirm Short | Options confirmation |
| `SPY_TECH_CONFIRM_LONG_15M` | `SPY` | `15m` | Underlying Tech Confirm Long | Options confirmation |
| `SPY_TECH_CONFIRM_SHORT_15M` | `SPY` | `15m` | Underlying Tech Confirm Short | Options confirmation |
| `QQQ_REGIME_SNAPSHOT_15M` | `QQQ` | `15m` | Underlying Regime Snapshot | Heartbeat/snapshot |
| `SPY_REGIME_SNAPSHOT_15M` | `SPY` | `15m` | Underlying Regime Snapshot | Heartbeat/snapshot |
| `VIX_RISK_ELEVATED_D` | `VIX` | `1D` | VIX Risk Elevated | Volatility risk |
| `VIX_RISK_NORMALIZED_D` | `VIX` | `1D` | VIX Risk Normalized | Volatility risk |

Use this Pine source:

```text
tradingview/stock_ultimus_options_underlying_alerts_v1.pine
```

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

Options `ENTRY_READY` requires reviewable IBKR chain evidence plus this
underlying TradingView confirmation layer. Until then, options stay in manual
review/evidence collection mode.
