# Stock Ultimus Operational Pending Work Register

Last reviewed: 2026-07-11.

This register tracks the open work from the TradingView alert and strategy
review. It is decision-support only and never authorizes order execution.

## Closed In This Review

- TradingView active alert model reduced to 5 consolidated production alerts.
- Old per-condition TradingView alerts are no longer part of the active set.
- Local validators and operator reports now separate active alerts from logical
  event coverage:
  - `total_production_active_alert_count=5`
  - `total_required_logical_event_count=16`
- TradingView alerts panel was visually verified with the 5 consolidated active
  alerts.
- V32 nudge preflight reached production successfully.
- V32 operator notify handles backend timeouts without traceback.
- After the targeted IBKR refresh, production operator notify moved from
  `NO_DATA` to `WAIT_MARKET`, with `WAIT_MARKET_SUPPRESSED` and no push sent.
- Local IBKR account capacity refresh is operational. The console reads
  sanitized `AccountSummary` fields in readonly mode, writes
  `runtime/ibkr_account_capacity_latest.json`, publishes the capacity context
  into the V31 snapshot, and shows per-alert capital/capacity comparisons
  without exposing real account identifiers.
- Intraday futures TradingView payloads now normalize `strategy_context` and
  `strategy` consistently, derive stop/target/RR from Pine `logical_stop` and
  `logical_target`, and attempt immediate Pushover delivery for entry triggers
  and risk invalidations. The 5-minute V32 watcher remains a fallback reminder,
  not the primary futures timing path.

## Waiting For Market Data

These cannot be fully closed on a closed-market day:

1. Confirm real TradingView payloads reach `/technical_snapshot`.
   - Current expected state: `WAITING_TV`.
   - Target: `logical_received=16/16` after real market triggers.

2. Confirm intraday futures alerts fire in real time.
   - Active alerts: `MNQ1!` `5m` and `MES1!` `5m`.
   - Target: accepted futures events in the TradingView ledger, no quarantine,
     and immediate notify status of `sent`, `deduped`, or provider-level
     `not_sent` without ingest failure.

3. Confirm actionable delivery in a real scenario.
   - V32 nudge preflight is ready.
   - JSON-only operator notify is healthy and suppresses closed-market noise.
   - Futures entry/risk events should arrive through the immediate
     `/technical_snapshot` path before the 5-minute watcher would run.
   - Do not send test push noise unless explicitly requested.

4. Observe scoring behavior over live cycles.
   - `setup_validity_pct`, `conviction_score`, and `ranking_score` must reduce
     daily noise and distinguish near-valid from fully valid setups.
   - Review after several live sessions using the opportunity audit.

## Strategy And Universe Expansion

Do not solve universe coverage by adding many TradingView alerts. The current
boundary is:

- TradingView: technical confirmation for `MNQ1!`, `MES1!`, `QQQ`, `SPY`, and
  `VIX`.
- IBKR: option chains, strike, expiration, DTE, bid/ask, spread, delta, IV,
  account context, and capacity.
- Strategy registry/regime policy: score thresholds, CANSLIM minimums, delta
  ranges, DTE ranges, and blocker logic.
- Backend scanner/universe: large-cap and CANSLIM candidates beyond the current
  default list.

Next implementation target:

- Validate the expanded backend large-cap/CANSLIM candidate universe in a live
  IBKR refresh. The default bridge universe now includes the prior core set plus
  `GOOGL`, `AVGO`, `AMD`, `COST`, `CRM`, and `ORCL`.
- Latest local IBKR refresh attempt on 2026-07-11 connected successfully with
  TWS open. A targeted run validated `QQQ`, `GOOGL`, `AVGO`, `AMD`, `COST`,
  `CRM`, and `ORCL`, produced `COVERAGE_REVIEWABLE`, and published the snapshot
  remotely with status `200`.
- Add or validate the ranking fields that promote stronger CANSLIM setups.
- The IBKR bridge now uses a dynamic option-underlying universe before opening
  chains. It ranks candidates by core context, operator priority, existing
  positions, large-cap/liquidity tier, technical confirmation, and CANSLIM
  score/pass. It then enforces `IBKR_MAX_OPTION_SYMBOLS_PER_RUN` and
  `IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN`.
- CANSLIM is now accepted as dynamic runtime input: any runtime JSON rows with
  `ticker`/`symbol` and `canslim` fields or `canslim_score`/`rating_score`
  fields are merged into the option-underlying rank before chains open.
- A free automated CANSLIM builder now writes
  `runtime/canslim_candidates_latest.json` from SEC companyfacts plus local
  runtime/IBKR bars when available. It uses no paid API and no manual CSV
  export.
- Audit `runtime/v32_ibkr_chain_coverage.json` after the next live run. The
  `option_symbol_plan` section should show selected and skipped underlyings with
  their scores, triggers, blockers, and `canslim_candidate_count`.
- Refresh account capacity from the local IBKR console before reviewing
  option-heavy alerts when margin/capital has materially changed. The current
  command path is documented in `docs/daily-radar-runbook.md`.
- Keep single-name TradingView alerts out of scope unless a measured technical
  confirmation gap is documented.

## Optional Cleanup

TradingView chart layout still may contain duplicate script instances or an old
compiled-error study. This is visual clutter only if the 5 active alerts remain
correct. Remove chart studies only after confirming that alert delivery is
stable or during an explicit chart-cleanup session.

## Verification Commands

```bash
python3 scripts/run_market_open_readiness.py --market-closed-ok --no-write
python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation
python3 scripts/v32_nudge_preflight_check.py
python3 scripts/v32_operator_notify.py
python3 scripts/run_alert_opportunity_audit.py --runtime-dir runtime --preview 5
```

Expected closed-market interpretation:

- `active_alerts=5`
- `logical_received=0/16` until real alerts fire
- `WAITING_TV` is acceptable
- `execution_authorized=false`
- `not_order_instruction=true`
