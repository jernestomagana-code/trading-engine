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

## Optional Health Alerts

Keep these paused unless the plan has spare active alert capacity. They are
heartbeat/context signals, not decision-making alerts, so operational health no
longer requires them while the active TradingView plan is capped at 20 alerts:

| Alert name | Symbol | Condition hint | Role |
| --- | --- | --- | --- |
| `MNQ_SESSION_SNAPSHOT_5M` | `MNQ1!` | Session Snapshot | Heartbeat/snapshot |
| `MES_SESSION_SNAPSHOT_5M` | `MES1!` | Session Snapshot | Heartbeat/snapshot |

## Required Pine Plot Names

Use the canonical Pine source in:

```text
tradingview/stock_ultimus_intraday_futures_alerts_v1.pine
```

The Pine script used by these alerts must expose plots with these exact names:

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

Legacy, duplicate, RSI, crossing-price, or old `Any alert() function call`
alerts should remain paused. If one fires anyway, the backend persists it in the
TradingView ledger but marks it `QUARANTINED` and does not feed it into the
decision engine.

If an alert condition title differs in TradingView, use the Pine condition that
matches the same event semantics and keep the Stock Ultimus alert name/event code
unchanged.

Canonical condition titles:

- `ORB Breakout Long`
- `ORB Breakout Short`
- `VWAP Reclaim Long`
- `VWAP Reject Short`
- `Risk Invalidation`
- `Session Snapshot`

## Next Phase

Do not add `NQ1!` or `ES1!` while `MNQ1!` and `MES1!` already cover the same
index signal semantics. The next phase is operational depth, not more equivalent
symbols:

- Confirm real TradingView events are reaching `/technical_snapshot`.
- Keep the two `Session Snapshot` alerts paused unless there is spare active
  alert capacity after all decision-making alerts are recurring.
- Monitor alert health, stale payloads, source attribution, and raw payload
  persistence.
- Close paper outcomes before changing parameters or expanding coverage.

## Operational Commands

Check alert health from the real ledger:

```bash
python3 scripts/run_tradingview_alert_health.py --market-closed-ok
```

Check the first open-market-day checklist:

```bash
python3 scripts/run_tradingview_first_open_day_checklist.py --market-closed-ok
```

Check whether the real end-to-end loop is confirmed:

```bash
python3 scripts/run_tradingview_e2e_check.py --market-closed-ok
```

Audit production coverage, source attribution, raw payload persistence, and
the no-`NQ`/`ES` expansion policy:

```bash
python3 scripts/run_tradingview_production_audit.py --market-closed-ok
```

The visible health summary should read `TV_OK` and `IBKR_OK` before any
`ENTRY_READY` decision is trusted for manual review. Until then, the operational
gate must remain in evidence collection mode.
