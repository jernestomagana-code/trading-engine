# Agent Operating Model

## Persistent Roles

These roles protect continuity across project versions and market changes:

1. Project Goal Guardian
2. Market Strategy Researcher
3. Information Security Guardian

## On-Demand Implementation Agents

Use implementation agents only when there is code to inspect or change:

- Explorer: maps current code flow and should not edit files.
- Bridge Worker: owns `ibkr_bridge.py` and bridge-side helpers.
- Cloud Worker: owns `app/main.py` and cloud/API/dashboard handling.
- Risk/Decision Worker: owns blocker priority and readiness logic.
- QA Worker: owns tests, fixtures, and verification commands.

## Recommended Workflow

1. Project Goal Guardian confirms the objective, non-negotiables, and acceptance criteria.
2. Information Security Guardian flags secrets, authentication, endpoint,
   logging, runtime-data, dependency, and multi-user risks for security-sensitive
   work.
3. Explorer maps the real project files and identifies write scopes.
4. Worker agents make scoped changes only in their owned areas.
5. QA Worker verifies fixtures, tests, and compile checks.
6. Project Goal Guardian performs a final consistency pass.
7. Market Strategy Researcher stays research-only unless a proposed rule becomes a documented implementation task.

## Coordination Rules

- Workers must have disjoint write scopes.
- Explorers should not edit files.
- The main Codex thread integrates all changes.
- No agent may introduce live automatic order execution.
- Every strategy recommendation must become either a documented research note or a testable implementation task.
- Market-driven changes must preserve conservative blocker priority.
- No agent may expose broker credentials, webhook secrets, API keys, account
  balances, account identifiers, positions, or sensitive runtime snapshots
  beyond the minimum required for the feature.
- Any new external endpoint must define authentication expectations, accepted
  payload shape, logging behavior, and failure behavior.

## Minimum Verification

For V30 changes, run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/check_v30_integrity.py
```

This validates V30 fixtures, scans available Python files for automatic order-execution patterns, compiles the production files or staged patch files that are present in the workspace, checks V29 decision scenarios, and smoke-tests the V29 trade/GPT/dashboard endpoint handlers.

Additional verification depends on the changed surface:

- endpoint smoke tests for FastAPI,
- fixture-based decision checks,
- runtime snapshot inspection,
- manual IBKR dry-run validation.
