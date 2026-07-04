# Stock Ultimus Daily Radar Runbook

This runbook keeps the Super Engine Bolsa daily question tied to the real
Stock Ultimus decision engine.

## Official GPT

Use `SUPER ENGINE BOLSA` as the official ChatGPT interface.

- Official GPT ID: `g-6a3c670ccb248191ac792583b2ca38bf`
- Retired legacy GPT ID: `g-69e832e2ddfc8191a74d5a8ba38af5a2`
- Legacy display name: `SUPER ENGINE BOLSA LEGACY - NO USAR`

Avoid continuing old chats tied to the retired legacy GPT. Start daily radar
questions from the official GPT so the `getDailyNow` Action is available.

The official GPT Action must use:

- Recommended model: `GPT-5.3 Instant`
- Authentication: API Key / Custom
- Header: `X-Stock-Ultimus-Read-Token`
- Primary operation for opportunity questions: `getDailyNow`

If ChatGPT shows a prompt to switch to the creator's recommended model, switch
before asking for the daily radar.

## Manual Run

Daily open checklist:

```bash
python3 scripts/daily_open_checklist.py
```

This is the friendly first check for the daily GPT workflow. It verifies:

- TWS/IB Gateway API port reachability.
- READ and ingest token availability without printing secrets.
- Runtime freshness.
- Production read-auth.
- V32 operator status, active alerts, and next required action.

It writes the latest redacted checklist to:

```bash
runtime/daily_open_checklist_latest.json
```

When you want the checklist to refresh and publish before reading the GPT
operator state, use explicit flags:

```bash
python3 scripts/daily_open_checklist.py --refresh --publish
```

On a market holiday or when intentionally validating with older runtime files,
use:

```bash
python3 scripts/daily_open_checklist.py --publish --allow-stale-publish
```

The checklist never places orders. A `WAIT_MARKET` result is healthy on closed
market days and must not be treated as permission to operate.

Proactive nudge preflight:

```bash
python3 scripts/v32_nudge_preflight_check.py
```

This reads production `/v32_operator_nudge_preflight`, verifies the read token
without printing it, writes:

```bash
runtime/v32_nudge_preflight_latest.json
```

Use this before the next market day to confirm the five nudge slots, first-day
checklist, and response playbook are available. If it returns `READY`, ask the
official GPT:

```text
haz preflight de nudges y dame checklist del lunes
```

Actionable V32 notifications:

```bash
python3 scripts/v32_operator_notify.py
```

This reads `/gpt_v32_operator_today` and writes:

```bash
runtime/v32_operator_notify_latest.json
```

It suppresses `WAIT_MARKET`-only noise. To show a local laptop notification
only when there is an `ACTION`, `RISK`, or manual-review-ready alert:

```bash
python3 scripts/v32_operator_notify.py --macos-notify
```

Operational-100 preflight:

```bash
python3 scripts/stock_ultimus_operational_100_check.py
```

This is the fastest way to verify the five operating-model gates in one pass:

- GPT Action/backend read health.
- Manual review inbox/history/learning dashboard links.
- Outcome and learning dry-run.
- Cloud operational audit.
- Post-close real outcome write readiness.

By default it does not persist outcome evaluations. After market close, and
only with a fresh post-review/post-close snapshot, run:

```bash
python3 scripts/stock_ultimus_operational_100_check.py --real-outcomes-after-close
```

That explicit flag runs the real outcome-evaluation write while preserving
`execution_authorized=false` and `not_order_instruction=true`.
It also refuses the real write if GPT Action health, the cloud operational
audit, or the outcome dry-run fails first.

Preferred one-command operating-day cycle:

```bash
python3 scripts/run_operating_day.py --allow-partial
```

This runs the read-only IBKR refresh, reads the daily radar, evaluates pending
paper outcomes/manual reviews, checks GPT Action health, and writes a redacted
report to:

```bash
runtime/operating_day_latest.json
```

If IBKR/TWS is not responding, inspect:

```bash
runtime/ibkr_bridge_health_latest.json
```

The most common fix is to open or unlock TWS/IB Gateway, confirm API access is
enabled, and rerun the operating-day cycle. A failed bridge must not be treated
as permission to operate; it means broker checks can be stale or unavailable.

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

Append a redacted daily audit record:

```bash
python3 scripts/run_daily_radar.py --audit-out runtime/daily_radar_audit.jsonl
```

The helper reads secrets from environment variables first, then from macOS
Keychain:

- Ingest token: `TRADING_ENGINE_INGEST_TOKEN`, `SNAPSHOT_INGEST_TOKEN`, or
  Keychain service `stock-ultimus-snapshot-ingest`
- Read token: `READ_ACCESS_TOKEN`, `STOCK_ULTIMUS_READ_TOKEN`, or Keychain
  service `stock-ultimus-read-access-token`

The script never places orders and never prints tokens.

## GPT Action Health

After a deploy, GPT Builder schema import, or `READ_ACCESS_TOKEN` rotation, run:

```bash
python3 scripts/monitor_gpt_action_health.py
```

This checks that `/gpt_v31_daily_rankings` rejects unauthenticated requests,
accepts the current read token, returns data-readiness diagnostics, exposes
`top_recommendations` and `blocked_or_waiting`, verifies
`/gpt_v31_daily_answer`, verifies the GPT's primary `/gpt_v31_daily_now`
surface, and preserves no-order guardrails. It writes a redacted latest health
record to:

```bash
runtime/gpt_action_health_latest.json
```

If the authenticated request returns 401, the backend token and the hidden API
key inside the official GPT Action are out of sync. Re-copy the Keychain value
into the GPT Action authentication field without pasting it into prompts, docs,
screenshots, or logs. After saving the Action, use its built-in `Test` button on
`getDailyNow`, then ask the published GPT `que oportunidades tengo hoy?`.

## Suggested Windows

Use windows when IBKR can provide reliable bid/ask option data:

- Pre-market diagnostic: 08:35 local time
- Regular session radar: 10:15 local time
- Optional refresh: 12:30 local time

If the engine returns `WAIT_MARKET_WINDOW`, recheck during a valid market/options
window. Do not convert `WAIT_MARKET` into an actionable opportunity.

## WAIT_OPTIONS_DATA Review

When the radar prints `WAIT_OPTIONS_DATA`, do not promote the ticker manually.
Use the printed diagnostic:

- `Campos faltantes frecuentes` identifies missing executable option fields.
- `Bloqueadores frecuentes` shows dominant blocker labels.
- Per-ticker detail shows selected contract bid/ask, spread, threshold rule, and
  remediation action.
- `contract_alternatives`, when present in JSON, are candidates to inspect only;
  they do not override blocker priority or authorize a trade.
- Required option fields remain `strike`, `expiration`, `dte`, `bid`, `ask`,
  `mid`, `spread`, `spread_pct`, and `delta`.

The corrective action is to refresh or enrich IBKR option-chain data, not to
change the decision state.

## Command Center

The same-source executive view is available after deploy at:

- JSON: `/v31_command_center.json`
- HTML: `/v31_command_center`
- Guided operator: `/v32_operator_dashboard`
- Full GPT daily cycle: `/gpt_v32_operator_daily_cycle`
- GPT operator Action: `/gpt_v32_operator_today`
- Friendly daily summary: `/v32_operator_daily_summary`
- Tracking/backtesting status: `/v32_operator_tracking_status`
- Email summary preview: `/v32_operator_daily_summary_email/preview`

It is derived from the same recommendation payload used by
`/gpt_v31_daily_rankings`, so it should agree with Super Engine Bolsa.

For the friendlier daily workflow, ask the official GPT:

```text
Que hago ahora?
```

The GPT should call `getOperatorDailyCycle` first. That gives the friendly
loop: current state, alert triage, Pushover cloud preview/dedupe, tracking, and
post-close/backtesting follow-up. If you only need current alerts, it can call
`getOperatorToday`. When you tell the GPT "pon QQQ en watchlist", "rechaza TSLA
por spread alto", or "registra esta nota", it should call `recordOperatorEvent`.
Those records are workflow/journal events for tracking and backtesting only;
they do not place orders.

For local notifications, use:

```bash
python3 scripts/v32_operator_notify.py --macos-notify
```

Optional channels:

```bash
python3 scripts/v32_operator_notify.py --webhook-url "$STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL"
python3 scripts/v32_operator_notify.py --pushover
python3 scripts/v32_operator_notify.py --email-summary
```

For mobile push with Pushover, configure these environment variables locally or
in the automation runner:

```bash
PUSHOVER_USER_KEY=...
PUSHOVER_API_TOKEN=...
```

Or store them in macOS Keychain without printing secrets:

```bash
security add-generic-password -U -a "$USER" -s stock-ultimus-pushover-user-key -w "..."
security add-generic-password -U -a "$USER" -s stock-ultimus-pushover-api-token -w "..."
```

Validate the channel before relying on mobile push:

```bash
python3 scripts/setup_pushover_channel.py --configure
python3 scripts/setup_pushover_channel.py
python3 scripts/setup_pushover_channel.py --send-test
```

The normal notifier suppresses `WAIT_MARKET` noise. Use `--force` only for a
manual smoke test or for a deliberate daily "sin accion" digest.

### Local Pushover Automation

Install the local macOS jobs after Pushover preflight passes:

```bash
python3 scripts/setup_pushover_channel.py --send-test
python3 scripts/install_v32_pushover_launchd.py --install
python3 scripts/install_v32_pushover_launchd.py --status
```

Installed jobs:

- `com.stockultimus.v32-pushover-monitor`: runs every 5 minutes; the wrapper
  only calls `v32_operator_notify.py --pushover` inside the US market window and
  the notifier still suppresses `WAIT_MARKET`.
- `com.stockultimus.v32-pushover-postclose`: runs every 15 minutes; the wrapper
  only evaluates outcomes once in the post-close window and sends a Pushover
  summary only if there is something to review.
- `com.stockultimus.v32-pushover-preflight`: daily local channel check.

Manual smoke tests:

```bash
python3 scripts/v32_pushover_automation.py --mode preflight --no-write
python3 scripts/v32_pushover_automation.py --mode monitor --force --no-write
python3 scripts/v32_pushover_automation.py --mode post-close --force --no-write
```

Uninstall:

```bash
python3 scripts/install_v32_pushover_launchd.py --uninstall
```

### Cloud Pushover Option

Local launchd works only while the Mac can run the jobs. To send push from
Render even when the laptop is off, add these Render environment variables:

```text
PUSHOVER_USER_KEY
PUSHOVER_API_TOKEN
```

Keep the existing `READ_ACCESS_TOKEN` in Render. Do not put Pushover credentials
in code, docs, GitHub Actions logs, or GPT instructions.

After deployment, verify the cloud route without sending:

```text
GET /v32_operator_pushover_notify/preview
```

Send only when the user explicitly asks for a push test, or when there are
action/risk alerts:

```text
POST /v32_operator_pushover_notify
POST /v32_operator_pushover_notify {"force": true}
```

`force=true` is for an explicit smoke test. The endpoint is protected by read
auth, keeps `execution_authorized=false`, and never places orders.

GitHub Actions cloud scheduler:

```text
.github/workflows/v32-cloud-pushover.yml
```

It runs every 5 minutes during a broad US market-hours window and calls
`POST /v32_operator_pushover_notify`. The backend sends only when there are
`ACTION`/`RISK` alerts and records a dedupe signature so the same actionable
alert does not repeat on every schedule tick. Manual `workflow_dispatch` with
`force=true` is only for a deliberate smoke test.

## Daily Outcome Evaluation

## Daily Manual Review

Use the fast inbox first:

```text
/v31_manual_review_inbox
```

It shows `ENTRY_READY` setups as cards with large buttons. Use the full console
only when you need blocked/waiting detail:

```text
/v31_manual_review_console
```

Record each setup as `REVIEWING`, `WATCHLIST`, `REJECTED`, `EXPIRED`, or
`APPROVED_FOR_MANUAL_TRADE`. Approval still means you manually validated broker
ticket, sizing, liquidity, event risk, and account risk; it is not an automated
order.

## Daily Outcome Evaluation

After market close, or the next morning after a fresh snapshot exists, run:

```bash
python3 scripts/run_daily_outcome_evaluation.py
```

Use the real write mode only after the review window is complete and a fresh
post-review/post-close snapshot exists. This persists paper outcome evaluations
for learning and performance tracking; it still never places orders.

Preview without writing evaluations:

```bash
python3 scripts/run_daily_outcome_evaluation.py --dry-run --no-write
```

The runner calls:

- `POST /v31_evaluate_pending_outcomes`
- `POST /v31_evaluate_manual_reviews`
- `GET /v32_strategy_performance`
- `GET /v31_manual_review_learning`
- `GET /gpt_v31_daily_answer`

It verifies `not_order_instruction=true` and `execution_authorized=false` for
the evaluation endpoints. It never uses ingest tokens, does not touch IBKR, and
does not place orders.

The executive performance dashboard is:

```text
/v32_strategy_performance_dashboard
```

Manual review history and learning dashboards:

```text
/v31_manual_reviews_dashboard
/v31_manual_review_learning_dashboard
```

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
python3 scripts/stock_ultimus_operational_100_check.py
python3 scripts/check_daily_radar_contract.py
python3 scripts/verify_production_read_auth.py
python3 scripts/monitor_gpt_action_health.py --no-write
python3 scripts/run_daily_outcome_evaluation.py --dry-run --no-write
python3 scripts/run_daily_radar.py --skip-bridge --preview 3
```

To review alert coverage, missed opportunities, source attribution, and whether
there is enough outcome sample before changing thresholds, run:

```bash
python3 scripts/run_alert_opportunity_audit.py --preview 10
```

This writes a JSON and CSV under `runtime/` for manual review. It is evidence
for strategy improvement only; it does not authorize orders.

Then ask Super Engine Bolsa:

```text
que oportunidades tengo hoy?
```

Expected behavior:

- It calls `/gpt_v31_daily_answer` or another Stock Ultimus Action endpoint before answering.
- It does not use Web Search to invent tickers.
- It reports `NO_DATA`, `WAIT_MARKET_WINDOW`, blockers, or manual-review
  candidates exactly as returned by the backend.
- It states that no live order is authorized.
