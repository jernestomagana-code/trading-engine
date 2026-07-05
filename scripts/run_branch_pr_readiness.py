#!/usr/bin/env python3
"""Check whether the current branch is ready for PR/merge cleanup."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "runtime" / "branch_pr_readiness_latest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_git(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False, timeout=20)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_value(args: list[str], default: str = "") -> str:
    code, out, _ = run_git(args)
    return out if code == 0 else default


def ahead_behind() -> tuple[int | None, int | None]:
    upstream = git_value(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if not upstream:
        return None, None
    counts = git_value(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"])
    parts = counts.split()
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def build_report() -> dict[str, Any]:
    branch = git_value(["branch", "--show-current"], "UNKNOWN")
    status_short = git_value(["status", "--short"])
    upstream = git_value(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    ahead, behind = ahead_behind()
    last_commit = git_value(["log", "-1", "--oneline"])
    remote_url = git_value(["config", "--get", "remote.origin.url"])
    clean = not bool(status_short.strip())
    ready = clean and upstream and (behind in {0, None})
    blockers = []
    if not clean:
        blockers.append("DIRTY_WORKTREE")
    if not upstream:
        blockers.append("NO_UPSTREAM")
    if behind not in {0, None}:
        blockers.append("BRANCH_BEHIND_UPSTREAM")
    if ahead not in {0, None}:
        blockers.append("UNPUSHED_COMMITS")
    status = "READY_FOR_PR" if ready and not blockers else "ACTION_REQUIRED"
    if status == "READY_FOR_PR" and ahead == 0:
        next_action = "Open or update a PR from this branch; local and upstream are aligned."
    elif "UNPUSHED_COMMITS" in blockers:
        next_action = "Run git push before opening or updating PR."
    elif "DIRTY_WORKTREE" in blockers:
        next_action = "Commit, stash, or intentionally leave local dashboard changes out of PR."
    else:
        next_action = "Resolve branch blockers before PR cleanup."
    return {
        "engine": "STOCK_ULTIMUS_BRANCH_PR_READINESS",
        "check_version": "branch_pr_readiness_v1",
        "generated_at": now_iso(),
        "branch": branch,
        "upstream": upstream,
        "remote_origin": remote_url,
        "last_commit": last_commit,
        "clean_worktree": clean,
        "ahead": ahead,
        "behind": behind,
        "status": status,
        "ok": status == "READY_FOR_PR",
        "blockers": blockers,
        "next_required_action": next_action,
        "pr_title_suggestion": "Add TradingView readiness and market-open environment gates",
        "pr_body_bullets": [
            "Adds combined TradingView alert coverage/readiness checks.",
            "Adds market-open go/no-go, post-open monitor, environment auth, and local dashboard tooling.",
            "Keeps execution_authorized=false and manual-review-only guardrails.",
        ],
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check branch PR readiness.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report()
    if not args.no_write:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
