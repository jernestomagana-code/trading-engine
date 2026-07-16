# TradingView Futures Alert Set

This is the production futures confirmation layer for Stock Ultimus. These
alerts provide technical evidence only; they do not authorize orders.

## Real-Time Delivery Model

The futures alerts are event-driven, not batch-driven:

1. TradingView fires the Pine `alert()` payload from `MNQ1!` or `MES1!`.
2. The webhook posts immediately to `/technical_snapshot`.
3. The backend normalizes both `strategy` and `strategy_context` as
   `INTRADAY_INDEX_FUTURES`.
4. Entry events and risk invalidations are persisted and evaluated immediately.
5. Pushover is attempted immediately for entry triggers and risk invalidations,
   deduped by session date, ticker, event code, and price.

The 5-minute V32 actionable-signal watcher remains a fallback/safety net for
operator reminders. It is not the primary timing mechanism for intraday futures.
Session snapshots, validation payloads, and non-actionable events are persisted
or skipped as appropriate but do not create push noise.

Operational interpretation:

- A `SESSION_SNAPSHOT` confirms that TradingView, webhook, and ledger are alive.
  It is not an opportunity and should not enter manual review.
- ORB/VWAP entry triggers and risk invalidations are the only intraday futures
  events that should create immediate operator attention.
- If an entry trigger is technically valid but account risk, portfolio, NLV, or
  premarket context is incomplete, the backend should still send the timing
  alert as `MANUAL_REVIEW` with the blocker shown. That alert is evidence to
  inspect manually, not permission to trade.
- `ENTRY_READY` is reserved for a clean technical trigger plus clear risk,
  portfolio, premarket context, and explicit no-order guardrails.

## Production Active Alerts

Keep only these two futures alerts active in TradingView:

| Active alert | Symbol | Timeframe | TradingView condition | Role |
| --- | --- | --- | --- | --- |
| `Stock Ultimus Intraday Futures Alerts v1` | `MNQ1!` | `5m` | `Any alert() function call` | Consolidated MNQ futures evidence |
| `Stock Ultimus Intraday Futures Alerts v1` | `MES1!` | `5m` | `Any alert() function call` | Consolidated MES futures evidence |

Use the deployed webhook URL:

```text
https://trading-engine-p097.onrender.com/technical_snapshot
```

Leave the TradingView message field at the default value for alert-function
alerts. The Pine script sends the JSON payload itself.

## Logical Event Coverage

The two active alerts above dynamically emit these ten event codes. Do not
create these as separate active alerts unless the consolidated alert-function
setup is unavailable:

| Event code | Symbol | Role |
| --- | --- | --- |
| `MNQ_ORB_BREAKOUT_LONG_5M` | `MNQ1!` | Entry confirmation |
| `MNQ_ORB_BREAKOUT_SHORT_5M` | `MNQ1!` | Entry confirmation |
| `MNQ_VWAP_RECLAIM_LONG_5M` | `MNQ1!` | Entry confirmation |
| `MNQ_VWAP_REJECT_SHORT_5M` | `MNQ1!` | Entry confirmation |
| `MNQ_RISK_INVALIDATION_5M` | `MNQ1!` | Invalidation |
| `MES_ORB_BREAKOUT_LONG_5M` | `MES1!` | Entry confirmation |
| `MES_ORB_BREAKOUT_SHORT_5M` | `MES1!` | Entry confirmation |
| `MES_VWAP_RECLAIM_LONG_5M` | `MES1!` | Entry confirmation |
| `MES_VWAP_REJECT_SHORT_5M` | `MES1!` | Entry confirmation |
| `MES_RISK_INVALIDATION_5M` | `MES1!` | Invalidation |

## Optional Health Alerts

Keep these paused unless the plan has spare active alert capacity. They are
heartbeat/context signals, not decision-making alerts, so operational health no
longer requires them while TradingView active-alert capacity is limited:

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

Validate the logical event matrix:

```bash
python3 scripts/print_tradingview_alert_setup.py --validate
```

Print every fallback setup record:

```bash
python3 scripts/print_tradingview_alert_setup.py
```

Print one exact alert message:

```bash
python3 scripts/print_tradingview_alert_setup.py --event-code MNQ_ORB_BREAKOUT_LONG_5M --messages-only
```

## TradingView Fields

Recommended setup:

- Add `tradingview/stock_ultimus_intraday_futures_alerts_v1.pine` to `MNQ1!`
  on the `5m` chart.
- Create one TradingView alert with condition `Stock Ultimus Intraday Futures Alerts v1`
  / `Any alert() function call`.
- Use the webhook URL above.
- Leave the message box as TradingView's default for alert-function alerts; the
  script sends the JSON payload itself.
- Repeat the same setup on `MES1!` `5m`.

Fallback setup if alert-function alerts are not available in the plan:

- Choose the matching chart symbol and `5m` timeframe.
- Choose the matching Pine alert condition from `condition_hint`.
- Name the alert exactly as `alert_name`.
- Paste the generated JSON message.
- Keep the alert active.
- This fallback consumes ten active-alert slots instead of two, so it is not the
  preferred production setup.

Legacy, duplicate, RSI, crossing-price, or generic text-message alerts should
remain paused. If one fires anyway, the backend persists it in the TradingView
ledger but marks it `QUARANTINED` and does not feed it into the decision engine.

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

The immediate futures push can still say `MANUAL_REVIEW` when the technical
trigger is real but risk, portfolio, or premarket context is incomplete. That is
intentional: the push is a timing alert, not order authorization.
