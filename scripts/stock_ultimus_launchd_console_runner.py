#!/usr/bin/env python3
"""Standalone launchd runner that triggers the local Stock Ultimus console.

This file is copied by the launchd installers into ~/Library/Application Support
so macOS background jobs do not need to open project scripts from Documents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


DEFAULT_CONSOLE_URL = "http://127.0.0.1:8765"

ENDPOINTS = {
    "auth-preflight": ("/diagnostic", "Diagnostico completo"),
    "environment-auth-preflight": ("/diagnostic", "Diagnostico completo"),
    "daily-snapshot-refresh": ("/daily-open", "Apertura diaria"),
    "market-open-readiness": ("/market-open-readiness", "Market open readiness"),
    "post-open-monitor": ("/post-open-monitor", "Post-open monitor"),
    "environment-alerts": ("/environment-alerts", "Environment alerts"),
    "security-audit": ("/security-audit", "Security audit"),
    "dependency-audit": ("/dependency-audit", "Dependency audit"),
    "local-dashboard": ("/local-dashboard-refresh", "Dashboard local"),
    "local-environment-dashboard": ("/local-dashboard-refresh", "Dashboard local"),
    "v32-pushover-monitor": ("/v32-pushover-monitor", "Pushover monitor"),
    "v32-pushover-postclose": ("/v32-pushover-postclose", "Pushover post-close"),
    "v32-pushover-preflight": ("/v32-pushover-preflight", "Pushover preflight"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def post_console(path: str, timeout: float) -> dict:
    base = os.getenv("STOCK_ULTIMUS_CONSOLE_URL", DEFAULT_CONSOLE_URL).rstrip("/")
    data = urllib.parse.urlencode({"source": "launchd_console_runner"}).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json,text/html",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "url": base + path,
                "body_tail": body[-1200:],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "url": base + path,
            "error": body[-1200:],
        }
    except Exception as exc:
        return {
            "ok": False,
            "url": base + path,
            "error": str(exc),
            "hint": "Abre primero la consola local en http://127.0.0.1:8765/console.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Stock Ultimus local console jobs from launchd.")
    parser.add_argument("job", choices=sorted(ENDPOINTS))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    path, label = ENDPOINTS[args.job]
    result = {
        "runner": "stock_ultimus_launchd_console_runner",
        "generated_at": now_iso(),
        "job": args.job,
        "label": label,
        "endpoint": path,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    result["trigger"] = post_console(path, args.timeout)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["trigger"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
