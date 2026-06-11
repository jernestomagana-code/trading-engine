# Agent Operating Model

## Persistent Roles

1. Project Goal Guardian
2. Market Strategy Researcher

## On-Demand Implementation Agents

Use implementation agents only when there is code to change:

- Explorer: maps current code flow.
- Bridge Worker: owns `ibkr_bridge.py`.
- Cloud Worker: owns `app/main.py`.
- Risk/Decision Worker: owns blocker and readiness logic.
- QA Worker: owns tests, fixtures, and verification commands.

## Coordination Rules

- Workers must have disjoint write scopes.
- Explorers should not edit files.
- The main Codex thread integrates all changes.
- No agent may introduce live automatic order execution.
- Every strategy recommendation must become either a documented research note or a testable implementation task.

## Verification

Minimum verification for Python changes:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 -m py_compile ibkr_bridge.py app/main.py
```

Additional verification depends on the changed surface:

- endpoint smoke tests for FastAPI,
- fixture-based decision checks,
- runtime snapshot inspection,
- manual IBKR dry-run validation.
