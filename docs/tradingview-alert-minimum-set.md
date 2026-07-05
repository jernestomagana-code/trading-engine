# TradingView Minimum Alert Set

This is the first production coverage matrix for Stock Ultimus TradingView
alerts. These alerts provide technical evidence only; they do not authorize
orders.

## Phase 1 Core Alerts

Create these ten alerts first, all on 5 minute charts:

| Alert name | Symbol | Condition hint | Role |
| --- | --- | --- | --- |
| `MNQ_ORB_BREAKOUT_LONG_5M` | `MNQ1!` | ORB Breakout Long | Entry confirmation |
| `MNQ_ORB_BREAKOUT_SHORT_5M` | `MNQ1!` | ORB Breakout Short | Entry confirmation |
| `MNQ_VWAP_RECLAIM_LONG_5M` | `MNQ1!` | VWAP Reclaim Long | Entry confirmation |
| `MNQ_VWAP_REJECT_SHORT_5M` | `MNQ1!` | VWAP Reject Short | Entry confirmation |
| `MNQ_RISK_INVALIDATION_5M` | `MNQ1!` | Risk Invalidation | Invalidation |
| `MES_ORB_BREAKOUT_LONG_5M` | `MES1!` | ORB Breakout Long | Entry confirmation |
| `MES_ORB_BREAKOUT_SHORT_5M` | `MES1!` | ORB Breakout Short | Entry confirmation |
| `MES_VWAP_RECLAIM_LONG_5M` | `MES1!` | VWAP Reclaim Long | Entry confirmation |
| `MES_VWAP_REJECT_SHORT_5M` | `MES1!` | VWAP Reject Short | Entry confirmation |
| `MES_RISK_INVALIDATION_5M` | `MES1!` | Risk Invalidation | Invalidation |

## Phase 1 Health Alerts

Add these two after the core alerts are present:

| Alert name | Symbol | Condition hint | Role |
| --- | --- | --- | --- |
| `MNQ_SESSION_SNAPSHOT_5M` | `MNQ1!` | Session Snapshot | Heartbeat/snapshot |
| `MES_SESSION_SNAPSHOT_5M` | `MES1!` | Session Snapshot | Heartbeat/snapshot |

## Required Pine Plot Names

The Pine scripts used by these alerts must expose plots with these exact names:

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

## Generate Setup Messages

Validate the matrix:

```bash
python3 scripts/print_tradingview_alert_setup.py --validate
```

Print every setup record:

```bash
python3 scripts/print_tradingview_alert_setup.py
```

Print one exact alert message:

```bash
python3 scripts/print_tradingview_alert_setup.py --event-code MNQ_ORB_BREAKOUT_LONG_5M --messages-only
```

## TradingView Fields

Use the deployed webhook URL:

```text
https://trading-engine-p097.onrender.com/technical_snapshot
```

For each alert:

- Choose the matching chart symbol and `5m` timeframe.
- Choose the matching Pine alert condition from `condition_hint`.
- Name the alert exactly as `alert_name`.
- Paste the generated JSON message.
- Keep the alert active.

If an alert condition title differs in TradingView, use the Pine condition that
matches the same event semantics and keep the Stock Ultimus alert name/event code
unchanged.

## Next Phase

After the futures alerts are receiving real ledger events, add market-regime
confirmations for options:

- `SPY_MARKET_REGIME_15M`
- `QQQ_MARKET_REGIME_15M`
