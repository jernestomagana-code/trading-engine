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

See `AGENTS.md` for the Codex agent workflow and V30 acceptance criteria.

## Workspace Map

- `AGENTS.md`: project context, non-negotiables, and agent workflow.
- `docs/agents/`: ready-to-use briefs for named agents such as Athena, Sentinel, Morgan, Scout, Bridge, Nova, Atlas, Quinn, Vega, and Ledger.
- `docs/product-vision.md`: long-term platform direction and commercial boundary.
- `docs/roadmap.md`: V30 through product-grade readiness roadmap.
- `docs/project-dashboard.md`: live project dashboard with current status, risks, and next actions.
- `docs/project-dashboard.html`: visual dashboard that can be opened directly in a browser.
- `docs/v30/decision-contract.md`: executable option field contract and blocker priority.
- `docs/v30/acceptance-checklist.md`: release checklist for V30.
- `fixtures/v30/`: example decision fixtures for incomplete and complete option-data states.
- `fixtures/runtime/v28_master_snapshot_sanitized.json`: sanitized production-style runtime snapshot for multi-ticker V29/V30 decision validation.
- `scripts/check_v30_integrity.py`: local integrity gate for V30 fixtures, no-auto-order guardrails, Python compile checks, V29/V31 engine checks, and endpoint smoke checks.
- `scripts/smoke_v29_endpoints.py`: direct FastAPI handler smoke test for V29/V31 trade and GPT endpoints plus dashboard/monitor handlers with controlled snapshots.
- `scripts/sanitize_runtime_snapshot.py`: sanitizes real runtime snapshots before they are committed as fixtures.
- `scripts/validate_runtime_privacy.py`: blocks obvious account, token, secret, balance, local-path, and private URL leaks in runtime fixtures.

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

## Current Next Step

V31 is active as a versioned canonical API contract over the validated V29 engine. Next, extract shared decision schemas and blocker helpers out of `app/main.py` so API, GPT, dashboard, and monitor surfaces consume one contract instead of duplicating shape logic.
