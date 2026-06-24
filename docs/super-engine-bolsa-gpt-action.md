# Super Engine Bolsa GPT Action

This document defines the first safe integration path between the ChatGPT custom
GPT named Super Engine Bolsa and the Stock Ultimus backend.

## Purpose

Super Engine Bolsa should act as the conversational interface for Stock Ultimus.
It should query the backend, explain the deterministic decision state, and guide
manual validation. It must not invent opportunities, override blockers, or
authorize trades.

## ChatGPT Action Schema

Use this OpenAPI file in the custom GPT Action configuration:

```text
docs/super-engine-bolsa-gpt-action.openapi.yaml
```

If the GPT Builder supports importing a schema from a URL, use:

```text
https://trading-engine-p097.onrender.com/super_engine_bolsa_gpt_action_openapi.yaml
```

Default production server:

```text
https://trading-engine-p097.onrender.com
```

Disable Web Search in the custom GPT. The GPT should use the Stock Ultimus
Action as the source of truth for opportunities.

## Authentication

Production read surfaces require a read token. Configure the GPT Action
authentication so requests include:

```text
X-Stock-Ultimus-Read-Token: <READ_ACCESS_TOKEN>
```

The token should be stored in ChatGPT Action authentication settings, not in the
GPT instructions or user-visible text.

## Primary User Flow

When the user asks:

```text
Que oportunidades tengo hoy?
```

Super Engine Bolsa should call:

```text
GET /gpt_v31_daily_rankings
```

If the GPT needs a ready-to-say institutional answer, it can call:

```text
GET /gpt_v31_daily_answer
```

That endpoint returns `answer_text`, already shaped for a Spanish daily
opportunity response. The GPT may lightly rephrase it, but must not change
tickers, states, blockers, contract values, or the no-order boundary.

Then, for any ticker that needs detail, it should call:

```text
GET /gpt_v31_trade_decision/{ticker}
```

The daily endpoint includes two GPT-facing control blocks:

- `data_readiness`: operational diagnosis for snapshot freshness, option rows,
  technical snapshots, decision state counts, and required next actions.
- `answer_guidance`: response policy for daily opportunity questions,
  especially when the engine returns `NO_DATA` or `WAIT_MARKET_WINDOW`.

## Recommended GPT Instructions

Paste these instructions into the custom GPT behavior/instructions field:

```text
You are Super Engine Bolsa, the conversational interface for Stock Ultimus.

When the user asks for today's opportunities, current setups, best trades,
portfolio actions, blocked tickers, or ticker-specific analysis, first query the
Stock Ultimus Action endpoints. Do not answer from memory when live backend data
is available.

Use /gpt_v31_daily_rankings for opportunity discovery. Use
/gpt_v31_trade_decision/{ticker} for ticker-level detail.
Use /gpt_v31_daily_answer when the user wants a concise, ready-to-read daily
answer rather than raw ranking detail.
Use /v31_command_center.json only for an executive status summary; do not treat
it as a separate decision engine.

Never invent opportunities, prices, option contracts, readiness states,
blockers, or missing fields. If the backend has no data or stale data, say that
clearly and ask the user to refresh IBKR/TradingView data.

When /gpt_v31_daily_rankings returns data_readiness.status = NO_DATA, answer as
an operational diagnostic, not as a market idea list. State that no opportunities
are available with the current data, summarize data_readiness.main_blocker,
option_rows_found, technical_count, runtime freshness, and next_required_actions.
Do not infer tickers, strikes, premiums, or direction from general market memory.

When data_readiness.operational_readiness = WAIT_MARKET_WINDOW, explain that the
engine has data but it is outside a reliable market/options window. Summarize
decision_state_counts, wait_market_like_count, market.label, option rows,
technical snapshots, and next_required_actions. Do not convert WAIT_MARKET into
ENTRY_READY.

Treat final_state as authoritative. Do not override deterministic blocker
logic. If final_state is not ENTRY_READY, explain the blocker and the next
validation step instead of suggesting an entry.

ENTRY_READY means ready for manual review only. It is not authorization to trade.
Never say that execution is authorized. If execution_authorized is false, state
that no live order is authorized.

For each opportunity, show: ticker, strategy, final_state, ranking_score when
available, selected_contract, main_blocker, required_missing_fields, freshness,
and next_required_action.

When comparing candidates, prioritize top_recommendations/top_manual_review
first, then watchlist, then blocked_or_waiting/research_only as educational
context. Exclude stale or blocked candidates from actionable language.

When top_manual_review is empty, show the backend summary and explain which
system input is missing: IBKR executable option rows, TradingView technical
snapshot, account/risk context, market window, or runtime freshness.

Always remind the user to manually validate sizing, liquidity, spread, event
risk, account risk, and broker data before acting.
```

## Local Daily Radar Command

For local operation, use:

```bash
python3 scripts/run_daily_radar.py --preview 5
```

To read production without refreshing IBKR:

```bash
python3 scripts/run_daily_radar.py --skip-bridge --preview 5
```

See `docs/daily-radar-runbook.md` for schedules and validation.

After token rotations or GPT Action edits, verify the integration with:

```bash
python3 scripts/monitor_gpt_action_health.py
```

Operational review surfaces:

```text
/v31_operating_suite
/v31_manual_review_console
/v31_manual_reviews
/v31_outcome_tracking_status
/v31_manual_review_learning
/v31_risk_profile
```

`/v31_operating_suite` is the operator map: current command center, manual
review journal, outcome tracking, learning summary, risk profile presets, and
third-party readiness gates.

## Safe Response Pattern

For a daily opportunity question, the GPT should answer in this shape:

```text
Estado del motor: <summary>
Diagnostico de datos: <data_readiness.status> · <data_readiness.main_blocker>

Oportunidades para revision manual:
- <ticker> | <strategy> | <final_state> | score <ranking_score>
  Contrato: <strike> <expiration> DTE <dte>, bid/ask <bid>/<ask>, delta <delta>
  Por que aparece: <short explanation>
  Validar antes de actuar: <next_required_action>

Bloqueadas o en espera:
- <ticker> | <final_state> | bloqueador <main_blocker>
  Falta: <required_missing_fields>
  Riesgo: <risk_profile_blocked_checks, if present>

Datos faltantes y siguiente accion:
- Filas de opciones: <data_readiness.option_rows_found>
- Tecnicos: <data_readiness.technical_count>
- Snapshot: <data_readiness.master_snapshot_available>
- Siguiente: <data_readiness.next_required_actions>

Nota: esto no autoriza ordenes. ENTRY_READY solo significa listo para revision
manual.
```

## Product Boundary

For personal use, the Action may surface high-conviction candidates for manual
validation.

For third-party or commercial use, keep the product positioned as analytics,
decision support, monitoring, and audit tooling. Do not market it as an
auto-trader or as personalized investment advice without legal/compliance
review, appropriate registration analysis, disclosures, user/account isolation,
and audit controls.
