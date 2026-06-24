# Stock Ultimus Customer Package

This is the handoff package for installing Stock Ultimus as a customer-specific
decision-support engine connected to a custom GPT.

## Package Contents

- Backend: Render/FastAPI app from `app/main.py`.
- Local bridge: `ibkr_bridge.py` running beside TWS or IBKR Gateway.
- GPT Action schema: `/super_engine_bolsa_gpt_action_openapi.yaml`.
- Daily GPT answer endpoint: `/gpt_v31_daily_answer`.
- Operator console: `/v31_operating_suite`.
- Manual review console: `/v31_manual_review_console`.
- Outcome evaluation: `scripts/run_daily_outcome_evaluation.py`.
- Performance dashboard: `/v32_strategy_performance_dashboard`.

## Customer Setup Checklist

1. Create a dedicated backend deployment for the customer.
2. Generate customer-specific `READ_ACCESS_TOKEN` and `SNAPSHOT_INGEST_TOKEN`.
3. Store local tokens in Keychain or environment variables; never paste them into
   prompts, screenshots, docs, or logs.
4. Set `V31_RISK_PROFILE_PRESET` to `conservative`, `balanced`,
   `aggressive`, or `paper`.
5. Configure TWS/IBKR read access. Do not enable automatic order execution.
6. Import the OpenAPI schema into the customer's custom GPT.
7. Configure GPT Action authentication with `X-Stock-Ultimus-Read-Token`.
8. In GPT instructions, tell the GPT to call `/gpt_v31_daily_answer` first for
   daily opportunity questions.
9. Run `scripts/monitor_gpt_action_health.py --no-write`.
10. Run `scripts/run_daily_outcome_evaluation.py --dry-run`.
11. Open `/v31_operating_suite` and confirm all sections are present.
12. Open `/v32_strategy_performance_dashboard` and confirm it renders.

## GPT Behavior

The customer GPT should answer daily opportunity questions by calling:

```text
GET /gpt_v31_daily_answer
```

For ticker detail, it should call:

```text
GET /gpt_v31_trade_decision/{ticker}
```

The GPT must not invent tickers, prices, strikes, expirations, blockers, or
readiness states. It must say that `ENTRY_READY` means manual review only and
that `execution_authorized=false`.

## Daily Operations

Morning:

```bash
python3 scripts/run_daily_radar.py --preview 5
python3 scripts/monitor_gpt_action_health.py --no-write
```

After market close or the next morning:

```bash
python3 scripts/run_daily_outcome_evaluation.py
```

For a safe preview:

```bash
python3 scripts/run_daily_outcome_evaluation.py --dry-run --no-write
```

## Commercial Gates

Before selling or operating for a third party, require:

- legal/compliance review,
- customer/account isolation,
- separate tokens per customer,
- durable audit logging,
- documented risk profile per customer,
- paper/simulation onboarding,
- written disclosures,
- support and incident process for stale data, broker outages, and token
  rotation.

## Non-Negotiable Boundary

Stock Ultimus is analytics and decision support. It does not place orders and
does not authorize automated execution.
