# Stock Ultimus

Hybrid local/cloud trading decision engine for IBKR, Render, TradingView, and GPT-assisted manual validation.

Long-term, Stock Ultimus is intended to mature into an auditable options trading
decision platform: data ingestion, normalization, strategy scoring, risk
gating, explanation, outcome tracking, and governance for possible future
commercial use.

This workspace is currently a documentation and implementation staging area. Bring the project code here before starting V30 implementation.

Expected key files:

- `ibkr_bridge.py`
- `app/main.py`
- runtime snapshot examples under `runtime/`
- dependency/config files such as `requirements.txt`, `pyproject.toml`, `.env.example`, or Render config

See `AGENTS.md` for the Codex agent workflow and V30 acceptance criteria.

## V30 Workspace Map

- `AGENTS.md`: project context, non-negotiables, and agent workflow.
- `docs/agents/`: ready-to-use briefs for Explorer, Bridge, Cloud, Risk/Decision, and QA agents.
- `docs/product-vision.md`: long-term platform direction and commercial boundary.
- `docs/roadmap.md`: V30 through product-grade readiness roadmap.
- `docs/project-dashboard.md`: live project dashboard with current status, risks, and next actions.
- `docs/project-dashboard.html`: visual dashboard that can be opened directly in a browser.
- `docs/v30/decision-contract.md`: executable option field contract and blocker priority.
- `docs/v30/acceptance-checklist.md`: release checklist for V30.
- `fixtures/v30/`: example decision fixtures for incomplete and complete option-data states.
- `scripts/check_v30_integrity.py`: local integrity gate for V30 fixtures, no-auto-order guardrails, Python compile checks, V29 engine checks, and endpoint smoke checks.
- `scripts/smoke_v29_endpoints.py`: direct FastAPI handler smoke test for V29 trade, GPT, and dashboard endpoints with controlled snapshots.

## V30 Integrity Check

Run this before and after V30 code changes:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/check_v30_integrity.py
```

While this workspace is still staging-only, the check compiles the available V30 patch files under `tmp_v30_patch/` and reports missing production files. Once `ibkr_bridge.py` and `app/main.py` are present in the root, the same command will include them automatically.

## Next Step

Copy or clone the current project code into this folder. Once the real files are present, Codex can spawn focused agents and start implementing V30.
