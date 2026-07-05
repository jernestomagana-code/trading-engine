# Stock Ultimus Next Market Day Checklist

Use this checklist at the next live market open. It is evidence collection and
manual review only.

## Before open

1. Open TWS or IB Gateway.
2. Confirm API access is enabled and the live/paper port matches `.env`.
3. Open TradingView alerts panel.
4. Confirm these alert groups are active:
   - 12 MNQ/MES futures alerts.
   - 8 SPY/QQQ/VIX options-underlying alerts.
5. Run:

```bash
python3 scripts/run_market_open_readiness.py --market-closed-ok
```

Expected before live alerts:

- `WAITING_TV` is acceptable before TradingView fires real payloads.
- `WAITING_IBKR` is acceptable before IBKR chain coverage is refreshed.
- `FOUNDATION_BLOCKED` is not acceptable; resolve the printed blocker first.

## At open

1. Refresh IBKR:

```bash
python3 ibkr_bridge.py --once
```

2. Check TradingView bundle:

```bash
python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation
```

3. Re-run go/no-go:

```bash
python3 scripts/run_market_open_readiness.py
```

4. Start monitor:

```bash
python3 scripts/run_post_open_monitor.py --watch --cycles 6 --interval-seconds 300
```

## What good looks like

- TradingView coverage remains `coverage_valid=true`.
- TradingView eventually moves to `real_e2e_confirmed=true`.
- IBKR eventually reports `primary_gap=COVERAGE_REVIEWABLE`.
- Quarantine count stays `0`.
- Go/no-go moves from `WAITING_TV` or `WAITING_IBKR` into
  `READY_FOR_EVIDENCE` or `READY_FOR_MANUAL_REVIEW`.

## Stop conditions

Pause manual review and inspect blockers if any of these appear:

- `FOUNDATION_BLOCKED`
- `TV_CONFIG_BLOCKED`
- `TV_QUARANTINE_EVENTS`
- `UNKNOWN_OR_QUARANTINED_TRADINGVIEW_PAYLOADS`
- `IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE` after repeated live refresh attempts
- any report where `execution_authorized` is not `false`
- any report where `not_order_instruction` is not `true`

## After close

1. Run outcome evaluation:

```bash
python3 scripts/run_daily_outcome_evaluation.py
```

2. Review performance gate:

```bash
python3 scripts/check_v32_strategy_performance.py
```

Do not change strategy parameters until each strategy/regime has at least 30
complete closed paper outcomes.
