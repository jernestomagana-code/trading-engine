# Stock Ultimus Market Open Operator Runbook

This runbook is for evidence collection and manual review only. It never
authorizes automated execution or strategy-parameter changes.

## Pre-open block

Run the readiness report:

```bash
python3 scripts/run_market_open_readiness.py --market-closed-ok
```

It writes:

```bash
runtime/market_open_readiness_latest.json
runtime/market_open_checklist_latest.json
```

Expected early status before live alerts fire:

- `WAITING_TV`: TradingView contracts are valid, but real alerts have not
  reached the ledger yet.
- `WAITING_IBKR`: TradingView is reviewable, but IBKR option-chain coverage is
  not yet `COVERAGE_REVIEWABLE`.
- `READY_FOR_EVIDENCE`: evidence collection is open, but not enough to trust
  `ENTRY_READY`.
- `READY_FOR_MANUAL_REVIEW`: evidence is reviewable for the manual inbox.

## Live-open sequence

1. Confirm TradingView alert panel shows the expected alert set.
   - 12 MNQ/MES futures alerts.
   - 8 SPY/QQQ/VIX options-underlying alerts.
   - NQ/ES remain out of scope because MNQ/MES already cover the same signal
     semantics.

2. Refresh IBKR when TWS/IB Gateway is connected:

```bash
python3 ibkr_bridge.py --once
```

3. Check combined TradingView health:

```bash
python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation
```

4. Re-run go/no-go:

```bash
python3 scripts/run_market_open_readiness.py
```

5. Start post-open monitor cycles:

```bash
python3 scripts/run_post_open_monitor.py
```

For repeated checks:

```bash
python3 scripts/run_post_open_monitor.py --watch --cycles 6 --interval-seconds 300
```

## Post-open interpretation

- `alert_level=OK`: no immediate infrastructure issue.
- `alert_level=WATCH`: evidence is still arriving or IBKR is not reviewable.
- `alert_level=ACTION`: inspect quarantined TradingView payloads, broken
  coverage, or other blockers before trusting the manual review flow.

The monitor writes:

```bash
runtime/post_open_monitor_latest.json
```

## Guardrails

- `ENTRY_READY` means manual review only.
- `WAIT_*` must never be promoted manually into an actionable setup.
- Parameter changes remain blocked until each strategy/regime has at least 30
  complete closed paper outcomes.
- All reports must preserve `execution_authorized=false` and
  `not_order_instruction=true`.
