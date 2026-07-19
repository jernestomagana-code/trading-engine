# Stock Ultimus Environment Automation Runbook

This runbook covers local environment automation only. It does not authorize
orders and does not change strategy parameters.

## 1. Automated Market Checklist

Preview launchd jobs without installing:

```bash
python3 scripts/install_market_environment_launchd.py --install --dry-run
```

Install explicitly:

```bash
python3 scripts/install_market_environment_launchd.py --install
```

Check status:

```bash
python3 scripts/install_market_environment_launchd.py --status
```

Installed jobs:

- `auth-preflight`: checks READ/INGEST/Pushover auth before the workflow.
- `market-open-readiness`: writes market-open go/no-go reports.
- `post-open-monitor`: runs a 90-minute monitor window after open.
- `environment-alerts`: sends environment Pushover alerts when attention is needed.
- `security-audit`: runs local information-security checks and notifies only
  on ACTION findings.
- `dependency-audit`: runs a weekly dependency vulnerability audit and notifies
  only when vulnerable packages are found.
- `local-dashboard`: refreshes a local static dashboard.

## 2. Local Dashboard

Build the local static dashboard:

```bash
python3 scripts/build_local_environment_dashboard.py
```

Output:

```bash
runtime/local_environment_dashboard.html
runtime/local_environment_dashboard_latest.json
```

It reads latest runtime reports for readiness, TradingView, auth, monitor, and
security audit state.

## 2.1 Local Security Audit

Run without notifications:

```bash
python3 scripts/run_security_audit.py --no-send
```

Run with ACTION-only Pushover notifications:

```bash
python3 scripts/run_security_audit.py --pushover
```

The audit is local-first and does not contact external services unless an
ACTION finding triggers an explicit notification channel. It checks for:

- sensitive values written into project/runtime files
- private-key markers in text files
- sensitive paths missing from `.gitignore`
- static read-auth and snapshot-ingest guards
- launchd templates that embed secret names
- core no-order guardrails

The report is written to:

```bash
runtime/security_audit_latest.json
```

## 2.2 Weekly Dependency Audit

Run without notifications:

```bash
python3 scripts/run_dependency_audit.py --no-send
```

Run with ACTION-only Pushover notifications:

```bash
python3 scripts/run_dependency_audit.py --pushover
```

The dependency audit uses `pip-audit` when available. Missing tooling or a
temporary audit-service failure is reported as WATCH in the dashboard; only
confirmed vulnerable packages trigger ACTION notifications.

The report is written to:

```bash
runtime/dependency_audit_latest.json
```

## 3. Token/Auth Validation

Local-only check:

```bash
python3 scripts/run_environment_auth_check.py --local-only
```

Production read-auth check:

```bash
python3 scripts/run_environment_auth_check.py
```

The check verifies presence of:

- READ token
- ingest token
- Pushover user key
- Pushover app token
- production read-auth
- GPT operator endpoint read-auth

Secrets are never printed.

## 4. Environment Alerts

Classify without sending:

```bash
python3 scripts/run_environment_alerts.py --notify-watch --no-send
```

Send Pushover on WATCH/ACTION:

```bash
python3 scripts/run_environment_alerts.py --notify-watch --pushover
```

Send only ACTION:

```bash
python3 scripts/run_environment_alerts.py --pushover
```

The alert script dedupes repeated monitor states through:

```bash
runtime/environment_alerts_state.json
```

## 5. Branch / PR Cleanup

Check branch readiness:

```bash
python3 scripts/run_branch_pr_readiness.py
```

It reports:

- current branch
- upstream
- clean/dirty worktree
- ahead/behind counts
- last commit
- PR title/body suggestion

If the worktree is dirty, resolve or intentionally leave local dashboard changes
out before creating/updating the PR.
