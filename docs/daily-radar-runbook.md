# Stock Ultimus Daily Radar Runbook

## Purpose

`scripts/run_daily_radar.py` is the local operator command for the daily Stock
Ultimus workflow. It refreshes the IBKR bridge, reads the GPT-facing V31 daily
rankings from Render, and prints a concise manual-review radar.

It never submits orders. `ENTRY_READY` still means ready for manual validation
only.

## Manual Command

From the project root:

```bash
python3 scripts/run_daily_radar.py
```

By default, this uses `DAILY_RADAR_FAST=1` for the IBKR bridge. The fast mode
limits option symbols, contracts per symbol, and market-data wait time so the
daily radar can publish a usable snapshot without waiting through the full
research universe.

Useful variants:

```bash
python3 scripts/run_daily_radar.py --skip-bridge
python3 scripts/run_daily_radar.py --allow-partial
python3 scripts/run_daily_radar.py --full-bridge
python3 scripts/run_daily_radar.py --json-out runtime/daily_radar_latest.json
python3 scripts/run_daily_radar.py --audit-out runtime/daily_radar_audit.jsonl
```

The command reads secrets from environment variables first, then macOS Keychain:

- Ingest: `TRADING_ENGINE_INGEST_TOKEN` or Keychain service
  `stock-ultimus-snapshot-ingest`
- Read: `READ_ACCESS_TOKEN` or Keychain service
  `stock-ultimus-read-access-token`

Tokens are not printed.

## GPT Action Health Check

After any Render deploy, GPT Builder schema import, or `READ_ACCESS_TOKEN`
rotation, run:

```bash
python3 scripts/monitor_gpt_action_health.py
```

The monitor checks that:

- `/gpt_v31_daily_rankings` rejects an unauthenticated request.
- The same endpoint accepts the current read token from environment or Keychain.
- The payload includes `data_readiness`, `top_recommendations`,
  `blocked_or_waiting`, and the no-order guardrails.
- `/gpt_v31_daily_now` returns `response_mode =
  copy_answer_to_user_exactly`, a non-empty `answer_to_user`, and a first line
  that keeps the "no autoriza ordenes" guardrail.

It writes a redacted latest health record to:

```bash
runtime/gpt_action_health_latest.json
```

If it fails with HTTP 401 on the authenticated request, the backend token and
the hidden API key configured inside the Super Engine Bolsa GPT Action are out
of sync. Re-copy the Keychain value into the GPT Action authentication field and
save/update the GPT. Do not paste the token into prompts, docs, screenshots, or
logs.

## Daily Audit Trail

`scripts/run_daily_radar.py` appends a redacted JSONL record by default:

```bash
runtime/daily_radar_audit.jsonl
```

Each record captures the generated time, readiness status, state counts, top
manual-review candidates, blocked/waiting candidates, selected contracts, and
`WAIT_OPTIONS_DATA` diagnostics. It does not store tokens.

Disable audit writing for a one-off run with:

```bash
python3 scripts/run_daily_radar.py --audit-out ""
```

## Manual Review Inbox

Use the quick inbox for the reminder-driven workflow:

```text
https://trading-engine-p097.onrender.com/v31_manual_review_inbox
```

Mark each setup as `REVIEWING`, `WATCHLIST`, `REJECTED`, `EXPIRED`, or
`APPROVED_FOR_MANUAL_TRADE` if it applies. `APPROVED_FOR_MANUAL_TRADE` is only
for a setup that is already `ENTRY_READY` and has passed your manual validation
of contract, liquidity, spread, events, account risk, and the manual broker
ticket. It is not an automated order instruction.

After the review, run:

```bash
python3 scripts/run_daily_outcome_evaluation.py --dry-run
```

## WAIT_OPTIONS_DATA Review

When the radar reports `WAIT_OPTIONS_DATA`, do not promote the ticker manually.
Review the diagnostic printed by the command:

- `Campos faltantes frecuentes` points to missing executable option fields.
- `Bloqueadores frecuentes` shows the dominant blocker labels.
- The common required option fields remain `strike`, `expiration`, `dte`, `bid`,
  `ask`, `mid`, `spread`, `spread_pct`, and `delta`.

The corrective action is to refresh/enrich IBKR option-chain data, not to change
the decision state.

## Executive View

The backend exposes a same-source command center:

- JSON: `/v31_command_center.json`
- HTML: `/v31_command_center`

This view is derived from the same V31 ranking and readiness payload used by
`/gpt_v31_daily_rankings`, so it should agree with Super Engine Bolsa.

## Suggested Windows

Recommended daily checks:

- Pre-market preparation: run after TWS is connected and option data is expected
  to be available.
- Market open validation: rerun after option bid/ask spreads stabilize.
- Intraday review: rerun only when you want a fresh manual-review radar.

When the endpoint says `operational_readiness = WAIT_MARKET_WINDOW`, the correct
action is to reconsult during a reliable market/options window. Do not convert
`WAIT_MARKET` or `WAIT_MARKET_OPEN` into a trade idea.

## launchd Template

Create a local LaunchAgent only after choosing the exact times you want. Use the
project path below and adjust `StartCalendarInterval` to your schedule.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.stockultimus.daily-radar</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/ernestomagana04/Documents/Stock Ultimus/scripts/run_daily_radar.py</string>
    <string>--allow-partial</string>
    <string>--json-out</string>
    <string>/Users/ernestomagana04/Documents/Stock Ultimus/runtime/daily_radar_latest.json</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/ernestomagana04/Documents/Stock Ultimus</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>8</integer>
      <key>Minute</key>
      <integer>35</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>10</integer>
      <key>Minute</key>
      <integer>15</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/stock_ultimus_daily_radar.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/stock_ultimus_daily_radar.err</string>
</dict>
</plist>
```

## Validation

Before relying on the workflow after code changes, run:

```bash
python3 scripts/monitor_gpt_action_health.py --no-write
python3 scripts/check_daily_radar_contract.py
python3 scripts/check_v32_outcomes_tracking.py
python3 scripts/run_daily_outcome_evaluation.py --dry-run
```

The first check protects the GPT daily-radar response contract, including the
`WAIT_MARKET` policy. The second protects the V32 journal/outcome/performance
loop.
