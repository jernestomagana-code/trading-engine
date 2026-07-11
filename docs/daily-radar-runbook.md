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

Market-open go/no-go:

```bash
python3 scripts/run_market_open_readiness.py --market-closed-ok
```

This produces the single local readiness answer for the open:

```bash
runtime/market_open_readiness_latest.json
runtime/market_open_checklist_latest.json
```

It combines TradingView bundle health, IBKR chain coverage, source attribution,
operational gate state, and paper-outcome readiness. Detailed operating steps
live in:

```bash
docs/market-open-operator-runbook.md
docs/next-market-day-checklist.md
docs/operational-pending-work-register.md
```

Post-open monitor:

```bash
python3 scripts/run_post_open_monitor.py
```

For a short six-cycle watch after open:

```bash
python3 scripts/run_post_open_monitor.py --watch --cycles 6 --interval-seconds 300
```

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

Intraday futures immediate path:

```text
TradingView Pine alert() -> /technical_snapshot -> immediate Pushover attempt
```

For `MNQ1!` and `MES1!`, entry triggers and risk invalidations are evaluated as
soon as the TradingView webhook arrives. This path dedupes repeated events and
never authorizes execution. It is the preferred timing path for intraday futures.

Cloud immediate actionable-signal watch:

```text
.github/workflows/v32-actionable-signal-watch.yml -> POST /v32_actionable_signal_watch
```

This runs every 5 minutes during broad US market hours. It is the fallback
operator reminder loop, not the primary futures timing path. It sends Pushover
only when a new `ACTION`, `ENTRY_READY`, or `manual_review_ready=true` alert
appears, deduped by alert id and signal signature. It prompts manual IBKR review
through the GPT and never authorizes execution.

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

Operational edge report:

```bash
python3 scripts/run_operational_edge_report.py --top 5 --preview 5
```

This is the integrated next-level report for the seven improvement fronts:
real-market confirmation, outcome-based score calibration, institutional
opportunity ranking, option-contract optimization, dynamic CANSLIM confidence,
control-panel health, and automatic post-mortem readiness. It writes:

```bash
runtime/v32_operational_edge_latest.json
```

Production routes:

- `/v32_operational_edge`
- `/v32_operational_edge_dashboard`

Interpretation: `overall_edge_score` is a maturity/readiness score, not a trade
score. Low calibration means the system needs more complete outcomes before
changing parameters. High contract ranking means IBKR has enough option-chain
evidence to shortlist contracts for manual review.

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

### IBKR Account Selection

Friendly path: save each IBKR account once with a logical alias, then run the
bridge/checklist by alias. Real IBKR account identifiers stay in macOS Keychain
and are never printed by the helper.

One-time setup:

```bash
python3 scripts/ibkr_account_profile.py setup primary --account YOUR_LOCAL_IBKR_ACCOUNT
python3 scripts/ibkr_account_profile.py setup income --account YOUR_OTHER_LOCAL_IBKR_ACCOUNT
python3 scripts/ibkr_account_profile.py setup speculative --account YOUR_THIRD_LOCAL_IBKR_ACCOUNT
```

Normal use:

```bash
python3 scripts/ibkr_account_profile.py bridge primary
python3 scripts/ibkr_account_profile.py bridge income
python3 scripts/ibkr_account_profile.py bridge speculative
```

For the daily open checklist:

```bash
python3 scripts/ibkr_account_profile.py daily-open primary
```

For any custom command that refreshes through the bridge:

```bash
python3 scripts/ibkr_account_profile.py run primary -- python3 scripts/run_daily_radar.py --preview 5
```

To check saved aliases without exposing account ids:

```bash
python3 scripts/ibkr_account_profile.py list
```

Advanced/env path: select the IBKR account before any command that refreshes
through `ibkr_bridge.py` (`run_operating_day.py`, `run_daily_radar.py --refresh`,
`daily_open_checklist.py --refresh`, or `run_market_bridge_session.py`).
Use logical aliases in prompts, docs, and runtime payloads. Keep the real IBKR
account numbers local in environment variables or Keychain-managed wrappers.

Example for one account:

```bash
export STOCK_ULTIMUS_ACCOUNT_SCOPE=primary
export IBKR_ACCOUNT_ALIAS=primary
export IBKR_ACCOUNT_MAP='{"primary":"YOUR_LOCAL_IBKR_ACCOUNT"}'
python3 ibkr_bridge.py --once
```

To refresh another account, change only the alias/scope before the run:

```bash
export STOCK_ULTIMUS_ACCOUNT_SCOPE=income
export IBKR_ACCOUNT_ALIAS=income
python3 ibkr_bridge.py --once
```

If TWS exposes multiple managed accounts and no account is selected, the bridge
blocks broker account/position context instead of mixing accounts. The bridge
publishes `account_scope` and `account_alias`, but never persists the real IBKR
account identifier.

Friendly local console:

```bash
python3 scripts/ibkr_account_profile.py serve
```

Then open `http://127.0.0.1:8765`. This is the single local cockpit for account
selection, IBKR refresh, V32 alerts, GPT context, and protected production links.
The page is intentionally localhost-only because it can read the local Keychain
and run local TWS/bridge commands. Do not expose it on a public interface.

Control-console contract:

- The top status strip is the first thing to read. Green means production,
  selected account context, snapshot, and account capacity are aligned for
  manual review. Amber means the console is usable but stale, partial, cached,
  or currently running a local process. Red means do not operate the console
  flow until token/production access is restored.
- When a long process is running, the console shows `La consola esta trabajando`
  plus a RUNNING/DONE detail link. Do not press another refresh button until the
  process finishes.
- Alert buttons are workflow marks only: `Visto`, `Revisando`, `Watch`,
  `Rechazar`, and `Cerrar`. After clicking, the alert receives a visible status
  badge and the event is saved for tracking/backtesting. These marks never
  authorize orders.
- Already handled alerts move out of first review into the reviewed/cerradas
  section, so the operator can see what has truly been touched.

No-terminal launcher:

```text
Stock Ultimus Console.command
```

Double-click that file from Finder to start the local console and open the
browser. It is the safest fallback when macOS privacy/TCC prevents launchd from
binding a localhost port from a background job.

Optional one-time autostart install:

```bash
python3 scripts/install_stock_ultimus_console_launchd.py --install --open
python3 scripts/install_stock_ultimus_console_launchd.py --status
```

After that, the local cockpit starts at login and the day-to-day entry point is
just `http://127.0.0.1:8765`. The LaunchAgent plist contains no IBKR account IDs,
read tokens, ingest tokens, or order execution permissions.

Operational flow:

1. Pick the account alias in the local selector.
2. Click `Refrescar bridge` or run the daily-open action.
3. The refreshed snapshot publishes only `account_scope` and `account_alias`.
4. GPT/action payloads use that sanitized account context for the current answer.
5. Use the console alert panel and protected links to review V32 alerts, email
   preview, tracking, and the exact GPT payload for the selected context.

If you change accounts without refreshing the bridge/snapshot, GPT still sees the
previous published account context. Treat a stale or missing `account_context` as
blocked until a fresh refresh is published.

Run the full refresh and read cycle:

```bash
python3 scripts/run_daily_radar.py --preview 5
```

By default this first builds `runtime/canslim_candidates_latest.json` with the
free SEC/runtime CANSLIM builder, then runs the read-only IBKR bridge. Use
`--skip-canslim` only for diagnostics. Use `--refresh-sec-canslim` when you want
to force-refresh the SEC cache before the bridge.

### Market-session bridge loop

For a live market session, use the bridge loop instead of remembering to run the
bridge by hand:

```bash
python3 scripts/run_market_bridge_session.py --max-runs 8 --interval-minutes 15 --notify
```

This runs `ibkr_bridge.py --once` repeatedly with `IBKR_CLIENT_ID=42`,
`DAILY_RADAR_FAST=1`, and `IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS=4`, publishes
fresh snapshots, and calls `/v31_monitor_notify` after successful refreshes. It
never places orders and never prints tokens.

Use `--force-notify` only for a delivery test; normal mode respects the backend
alert and dedupe rules. Use `--full-scan` only when you intentionally want the
slower full option-depth scan.

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
Keychain. `READ_ACCESS_TOKEN` is the canonical name; the other environment
names below are transitional compatibility aliases:

- Ingest token: `TRADING_ENGINE_INGEST_TOKEN`, `SNAPSHOT_INGEST_TOKEN`, or
  Keychain service `stock-ultimus-snapshot-ingest`
- Read token: `READ_ACCESS_TOKEN`, `STOCK_ULTIMUS_READ_TOKEN`,
  `STOCK_ULTIMUS_READ_ACCESS_TOKEN`, or Keychain service
  `stock-ultimus-read-access-token`

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
key inside the official GPT Action are out of sync. Re-copy the canonical
`READ_ACCESS_TOKEN` value into the GPT Action authentication field without
pasting it into prompts, docs, screenshots, or logs. After saving the Action,
use its built-in `Test` button on `getDailyNow`, then ask the published GPT
`que oportunidades tengo hoy?`.

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

## TradingView Alert Boundary

The production TradingView setup uses five active consolidated alerts documented
in `docs/tradingview-production-active-alerts.md`. Those five alerts are enough
for the current technical confirmation layer because Pine emits the required
logical event codes internally.

Do not recreate old per-condition alerts to solve missing strategy evidence.
Use the right source for the missing field:

- TradingView: technical/event confirmation for `MNQ1!`, `MES1!`, `QQQ`, `SPY`,
  and `VIX`.
- IBKR: option contract, best strike, DTE, bid/ask, spread, delta, and account
  capacity checks.
- Strategy registry/regime policy: score thresholds, CANSLIM minimums, delta
  ranges, DTE ranges, and blocker logic.
- Backend universe/scanner: additional large-cap or CANSLIM candidates.

The default IBKR bridge universe includes the core indices/large-cap names plus
`GOOGL`, `AVGO`, `AMD`, `COST`, `CRM`, and `ORCL`. Override with
`IBKR_WATCHLIST` and `IBKR_OPTION_SYMBOLS` when testing a narrower or broader
universe.

Option-chain expansion is dynamic. The bridge first ranks the candidate
underlyings, then opens chains only for the selected subset. The rank combines:

- Core market context: `QQQ` and `SPY` by default.
- Context-only market signals such as `TLT`; they inform macro/rates context
  but do not consume option-chain budget unless another detonator is present.
- Operator priority symbols from `IBKR_OPTION_PRIORITY_SYMBOLS`.
- Existing portfolio positions, so covered-call/management candidates are not
  skipped just because they are outside the top growth list.
- Large-cap/liquidity tier score.
- Technical score/confirmation from runtime snapshots.
- CANSLIM pass/score when available.

CANSLIM can enter dynamically through runtime JSON files. Any runtime payload
containing rows with `ticker` or `symbol` plus either a nested `canslim` object
or fields such as `canslim_score`, `canslim_passes`, `canslim_rating`,
`rating_score`, or `composite_rating` is merged into the technical snapshot
before ranking. This lets a future CANSLIM screener feed candidates without
creating extra TradingView alerts or opening option chains for every symbol.

Free automated CANSLIM is available through the local SEC/runtime builder:

```bash
python3 scripts/build_canslim_free_candidates.py
```

The daily radar and daily-open checklist run this automatically before a bridge
refresh. The standalone command is useful for diagnostics. It writes
`runtime/canslim_candidates_latest.json` using free SEC companyfacts data plus
local runtime/IBKR bars when available. It does not require a paid API, does not
require CSV exports, and does not authorize orders. Set
`STOCK_ULTIMUS_SEC_USER_AGENT` to a descriptive SEC user agent before scheduled
runs.

Current guardrails:

- `IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED=true` by default.
- `IBKR_MAX_OPTION_SYMBOLS_PER_RUN` limits how many underlyings get option
  chains in one cycle. Default is 10 in normal mode and 6 in fast mode.
- `IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN` limits total option contracts
  queried in one cycle.
- `IBKR_OPTION_MIN_UNDERLYING_SCORE` defaults to 30 so liquid large-cap names
  can enter discovery while the contract budget still caps IBKR load.
- `IBKR_OPTION_CONTEXT_ONLY_SYMBOLS` defaults to `TLT`; these symbols need
  priority, position, technical, or CANSLIM confirmation before opening chains.
- `IBKR_OPTION_TECHNICAL_TRIGGER_SCORE` and
  `IBKR_OPTION_CANSLIM_TRIGGER_SCORE` define the technical/CANSLIM detonators.
- The IBKR diagnostic file records `option_symbol_plan` with ranked, selected,
  selected, and skipped underlyings, plus `canslim_candidate_count`, so the
  operator can audit why a symbol did or did not consume option-chain budget.

If a new stock or strategy repeatedly needs TradingView-specific confirmation,
document the measured gap first, then add a versioned alert expansion. Until
then, more TradingView alerts are noise, not more intelligence.

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

## Local IBKR Account Capacity

The local IBKR console can now refresh sanitized account capacity before or
after a bridge run. This closes the loop between "best contract" and "can this
account reasonably carry the capital/margin requirement?"

From the local console, use the **Refresh cuenta** button for the selected
alias. From the terminal, use the active profile wrapper so the real IBKR
account id stays in Keychain and is not printed:

```bash
python3 scripts/ibkr_account_profile.py run remanente -- python3 scripts/ibkr_account_profile.py refresh-account-capacity --publish
```

What it does:

- Connects to TWS/IBKR in `readonly=True`.
- Reads only sanitized `AccountSummary` fields such as `AvailableFunds`,
  `ExcessLiquidity`, `BuyingPower`, `NetLiquidation`, and margin requirement.
- Writes `runtime/ibkr_account_capacity_latest.json`.
- Publishes the account context into the V31 snapshot, without real account IDs.
- Keeps `execution_authorized=false` and `not_order_instruction=true`.

The console displays:

- Usable capacity source, preferring `AvailableFunds`, then
  `ExcessLiquidity`, then `BuyingPower`.
- Option economics per alert: estimated capital required, gross credit,
  delta-proxy probability, and annualized return on capital when DTE is present.
- Per-alert capacity comparison, including shortfall or high-capacity warnings.

This is still decision support only. IBKR/TWS remains the final source for
order ticket margin and the human operator must review before any action.

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
python3 scripts/run_alert_opportunity_audit.py --preview 10 --recent-days 14
```

This writes a JSON and CSV under `runtime/` for manual review. It is evidence
for strategy improvement only; it does not authorize orders. The JSON includes
both full-history counts and a `freshness` section so old decisions do not mask
the current live-readiness picture.

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
