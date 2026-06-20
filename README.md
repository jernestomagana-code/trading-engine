# Stock Ultimus

Hybrid local/cloud trading decision engine for IBKR, Render, TradingView, and GPT-assisted manual validation.

Long-term, Stock Ultimus is intended to mature into an auditable options trading
decision platform: data ingestion, normalization, strategy scoring, risk
gating, explanation, outcome tracking, and governance for possible future
commercial use.

This workspace now contains the active local/cloud implementation for Stock Ultimus.

Expected key files:

- `ibkr_bridge.py`
- `app/main.py`
- runtime snapshot examples under `runtime/`
- dependency/config files such as `requirements.txt`, `pyproject.toml`, `.env.example`, or Render config

This project now also includes a local `resend` usage guard in `app/main.py`. Use the environment variables `RESEND_DAILY_PLAN_LIMIT` and `RESEND_DAILY_LIMIT_PERCENT` to cap how many emails this app can send per day, so it does not consume the entire shared quota.

If you deploy the app somewhere other than Render, set those env vars in your deployment environment. Render is only relevant if this service is deployed there; the quota guard itself lives in the application.

See `AGENTS.md` for the Codex agent workflow and V30 acceptance criteria.

## Workspace Map

- `AGENTS.md`: project context, non-negotiables, and agent workflow.
- `docs/agents/`: ready-to-use briefs for named agents such as Athena, Sentinel, Morgan, Scout, Bridge, Nova, Atlas, Quinn, Vega, and Ledger.
- `docs/product-vision.md`: long-term platform direction and commercial boundary.
- `docs/roadmap.md`: V30 through product-grade readiness roadmap.
- `docs/strategy-playbook.md`: versioned daily strategy playbook for data
  sources, freshness, blockers, ranking, and manual-review recommendations.
- `docs/strategy-intelligence-loop.md`: Morgan's research-to-rule loop for
  current market practice, elite trader/institutional research, intraday vs
  non-intraday strategy review, and versioned rule promotion.
- `strategy_intelligence.py`: shared V31 Strategy Intelligence helpers for
  registry lookup, source timestamps, freshness gates, score components, and
  daily ranking.
- `v31_contracts.py`: versioned V31 decision contract and selected-contract
  schema helpers used by API/GPT/dashboard surfaces.
- `decision_guards.py`: shared executable option contract, manual-risk, and
  blocker-priority helpers.
- `production_readiness.py`: deployment readiness gates for auth, safe mode,
  email limits, redaction, and no-order policy.
- `audit_log.py`: append-only redacted audit events for decisions, follow-ups,
  outcomes, and production diagnostics.
- `runtime_retention.py`: versioned retention policy for decision journals,
  outcome journals, audit logs, and runtime storage mode.
- `storage_isolation.py`: production gate for durable storage plus tenant and
  account isolation before any multi-user/commercial scope.
- `durable_storage.py`: versioned durable storage contract for decision
  journals, outcome journals, audit events, Supabase grants/RLS, and readiness
  gating plus payload-to-row helpers for the runtime adapter.
- `supabase/durable_storage_contract_v1.sql`: SQL contract to run in Supabase
  SQL Editor or another managed Postgres console.
- `config/strategy_registry.json`: strategy states and caps (`ENABLED`,
  `RADAR_ONLY`, `DISABLED`) tied to playbook and intelligence-loop versions.
- `fixtures/strategy_intelligence/freshness_cases.json`: source-specific
  freshness fixtures for IBKR, TradingView, CANSLIM/fundamental, market regime,
  and account context.
- `fixtures/v31/decision_contract_schema_cases.json`: V31 schema fixture for
  decision contracts, selected contracts, registry caps, and no-order flags.
- `fixtures/v31/surface_compatibility_cases.json`: V31 API/GPT/dashboard/ranking
  parity expectations for shared contract consumption.
- `fixtures/v31/decision_guard_cases.json`: executable-contract and
  blocker-priority guard fixtures.
- `fixtures/production_readiness_cases.json`: production readiness cases for
  secure deployment configuration.
- `fixtures/durable_storage_cases.json`: durable storage contract cases for
  local JSON, Supabase readiness, and missing contract/key blockers.
- `docs/strategy_research_notes/`: Morgan research hypotheses and promotion
  requirements.
- `docs/project-dashboard.md`: live project dashboard with current status, risks, and next actions.
- `docs/project-dashboard.html`: visual dashboard that can be opened directly in a browser.
- `docs/project-command-center.html`: executive Kanban view of completed work, active work, and release gates.
- `docs/v30/decision-contract.md`: executable option field contract and blocker priority.
- `docs/v30/acceptance-checklist.md`: release checklist for V30.
- `fixtures/v30/`: example decision fixtures for incomplete and complete option-data states.
- `fixtures/runtime/v28_master_snapshot_sanitized.json`: sanitized production-style runtime snapshot for multi-ticker V29/V30 decision validation.
- `scripts/check_v30_integrity.py`: local integrity gate for V30 fixtures, no-auto-order guardrails, Python compile checks, V29/V31 engine checks, and endpoint smoke checks.
- `scripts/smoke_v29_endpoints.py`: direct FastAPI handler smoke test for V29/V31 trade and GPT endpoints plus dashboard/monitor handlers with controlled snapshots.
- `scripts/sanitize_runtime_snapshot.py`: sanitizes real runtime snapshots before they are committed as fixtures.
- `scripts/validate_runtime_privacy.py`: blocks obvious account, token, secret, balance, local-path, and private URL leaks in runtime fixtures.
- `scripts/validate_strategy_intelligence.py`: validates the strategy registry
  and Morgan research notes.
- `scripts/validate_decision_guards.py`: validates executable-contract and
  blocker-priority helpers.
- `scripts/validate_production_readiness.py`: validates production readiness
  gates and response redaction.
- `scripts/validate_audit_log.py`: validates audit event shape and sensitive
  value redaction.
- `scripts/validate_runtime_retention.py`: validates retention policy bounds
  and trimming behavior.
- `scripts/validate_storage_isolation.py`: validates durable storage and
  tenant/account isolation gates.
- `scripts/validate_durable_storage.py`: validates durable storage contract
  SQL, required tables, RLS, grants, and readiness blockers.
- `scripts/check_durable_storage_runtime.py`: validates the Supabase runtime
  adapter for V32 decision journals, outcome journals, and audit events without
  contacting a real Supabase project.
- `scripts/check_read_auth_gate.py`: validates production read-auth middleware
  for sensitive dashboards, GPT/status, decision, audit, readiness, and V31/V32
  surfaces.
- `scripts/verify_production_read_auth.py`: verifies a deployed service accepts
  the read token and blocks unauthenticated sensitive reads.

## Integrity Check

Run this before and after decision, risk, bridge, dashboard, or GPT-facing changes:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/check_v30_integrity.py
```

Before adding a real runtime snapshot, sanitize it outside the repo:

```bash
python3 scripts/sanitize_runtime_snapshot.py path/to/raw.json fixtures/runtime/real_sanitized/example.json
python3 scripts/validate_runtime_privacy.py
```

## Sensitive Read Access

Production read surfaces require a read token. Configure `READ_ACCESS_TOKEN` in
Render and send it as one of:

- `X-Stock-Ultimus-Read-Token: <token>`
- `Authorization: Bearer <token>`
- `X-Admin-Debug-Token: <ADMIN_DEBUG_TOKEN>`

Public health paths remain open, while ingest/webhook endpoints keep their own
ingest/webhook tokens.

The local `READ_ACCESS_TOKEN` generated during setup is stored in macOS Keychain
under `stock-ultimus-read-access-token`.

## Durable Storage SQL

Run this SQL in Supabase SQL Editor before setting `RUNTIME_STORAGE_MODE=supabase`:

```text
supabase/durable_storage_contract_v1.sql
```

Then configure Render with `SUPABASE_URL`, `SUPABASE_KEY`,
`DURABLE_STORAGE_CONTRACT_VERSION=durable_storage_contract_v1`, and
`RUNTIME_STORAGE_MODE=supabase`.

## Current Next Step

V31 is active as a versioned canonical API contract over the validated V29 engine. Core decision contracts, executable-contract validation, blocker priority, surface parity, production readiness, redacted audit logging, runtime retention, storage isolation, durable-storage contract gates, Supabase runtime adapter, and production read-auth middleware now live in shared modules and guards. Next, configure the real production secrets in Render, apply the SQL contract in Supabase/Postgres, set `RUNTIME_STORAGE_MODE=supabase`, and validate against a sanitized live IBKR snapshot.
