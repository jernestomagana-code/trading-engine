# Stock Ultimus Daily Radar Runbook

This runbook keeps the Super Engine Bolsa daily question tied to the real
Stock Ultimus decision engine.

## Manual Run

Run the full refresh and read cycle:

```bash
python3 scripts/run_daily_radar.py --preview 5
```

Read the current cloud radar without refreshing IBKR:

```bash
python3 scripts/run_daily_radar.py --skip-bridge --preview 5
```

Save the raw GPT-facing response for audit:

```bash
python3 scripts/run_daily_radar.py --json-out runtime/daily_radar_latest.json
```

The helper reads secrets from environment variables first, then from macOS
Keychain:

- Ingest token: `TRADING_ENGINE_INGEST_TOKEN`, `SNAPSHOT_INGEST_TOKEN`, or
  Keychain service `stock-ultimus-snapshot-ingest`
- Read token: `READ_ACCESS_TOKEN`, `STOCK_ULTIMUS_READ_TOKEN`, or Keychain
  service `stock-ultimus-read-access-token`

The script never places orders and never prints tokens.

## Suggested Windows

Use windows when IBKR can provide reliable bid/ask option data:

- Pre-market diagnostic: 08:35 local time
- Regular session radar: 10:15 local time
- Optional refresh: 12:30 local time

If the engine returns `WAIT_MARKET_WINDOW`, recheck during a valid market/options
window. Do not convert `WAIT_MARKET` into an actionable opportunity.

## Launchd Template

Create one LaunchAgent per desired window. Replace paths if this repository is
moved.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.stockultimus.daily-radar.1015</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/ernestomagana04/Documents/Stock Ultimus/scripts/run_daily_radar.py</string>
    <string>--preview</string>
    <string>5</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/ernestomagana04/Documents/Stock Ultimus</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>15</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/private/tmp/stock_ultimus_daily_radar.out</string>
  <key>StandardErrorPath</key>
  <string>/private/tmp/stock_ultimus_daily_radar.err</string>
</dict>
</plist>
```

Install only after TWS/IBKR Gateway is normally available at the scheduled
times.

## Validation

Before relying on automation, run:

```bash
python3 scripts/check_daily_radar_contract.py
python3 scripts/verify_production_read_auth.py
python3 scripts/run_daily_radar.py --skip-bridge --preview 3
```

Then ask Super Engine Bolsa:

```text
que oportunidades tengo hoy?
```

Expected behavior:

- It calls the Stock Ultimus Action before answering.
- It does not use Web Search to invent tickers.
- It reports `NO_DATA`, `WAIT_MARKET_WINDOW`, blockers, or manual-review
  candidates exactly as returned by the backend.
- It states that no live order is authorized.
