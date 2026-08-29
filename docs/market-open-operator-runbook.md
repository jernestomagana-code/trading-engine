# Stock Ultimus Market Open Operator Runbook

This runbook is for evidence collection and manual review only. It never
authorizes automated execution or strategy-parameter changes.

## Current TradingView cockpit (verified 2026-08-27)

Use the four saved layouts in TradingView Desktop:

| Layout | Symbol | Timeframe | Main script |
| --- | --- | --- | --- |
| `01 MNQ Entrada 1m` | `MNQ1!` | `1m` | `Stock Ultimus Intraday Futures FAST v2.2` |
| `02 USTEC Confirmacion 15m` | `USTEC.F` | `15m` | `Chris IA Decision Panel v4.4` |
| `03 QQQ Opciones 15m` | `QQQ` | `15m` | `Stock Ultimus Options Underlying Alerts v1.1` |
| `04 VIX Riesgo Diario` | `VIX` | `1D` | `Stock Ultimus Options Underlying Alerts v1.1` |

The current managed set is five consolidated alerts: FAST v2.2 for `MNQ1!` and
`MES1!`, plus Options Underlying for `QQQ`, `SPY`, and `VIX`. Duplicate,
explicit legacy, and Chris IA alerts remain paused. The operator's RSI alerts
are unrelated and remain untouched. TradingView alerts
are evidence for manual review and never authorize an order.

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

Primary cockpit:

```text
http://127.0.0.1:8765/console
```

Use the local console as the single operator monitor during market hours. It
consolidates account/capacity, IBKR bridge refresh, production/GPT status, V31
manual review, V31 learning/performance, and local operational questions.
Render remains the production backend/API and ChatGPT remains a conversational
interface, but the operator should not need to jump between separate consoles
for normal review.

1. Confirm TradingView alert panel shows the current nine-alert set described
   above. Old per-condition, RSI, crossing-price, duplicate, MES, SPY, and
   generic alerts stay paused and are not part of the active cockpit.
   - NQ/ES remain out of scope because MNQ/MES already cover the same signal
     semantics.
   - More single-name alerts are not required for CANSLIM or large-cap scans;
     those candidates must come from the backend universe, IBKR chains, and
     scoring rules first.

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
