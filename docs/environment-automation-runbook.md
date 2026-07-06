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
branch/PR state.

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
