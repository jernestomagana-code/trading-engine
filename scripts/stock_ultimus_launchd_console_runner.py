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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


DEFAULT_CONSOLE_URL = "http://127.0.0.1:8765"
DEFAULT_JOB_TIMEOUT_SECONDS = 600.0

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
    "portfolio-risk-monitor": ("/portfolio-risk-monitor", "Monitoreo de riesgo de cartera"),
    "portfolio-risk-preflight": ("/portfolio-risk-preflight", "Preflight de riesgo de cartera"),
    "portfolio-risk-digest": ("/portfolio-risk-digest", "Digest de riesgo de cartera"),
    "daily-outcome-evaluation": ("/daily-outcome-evaluation", "Seguimiento automático de resultados"),
    "executive-report-daily": ("/executive-report-daily", "Reporte ejecutivo diario"),
    "executive-report-weekly": ("/executive-report-weekly", "Reporte ejecutivo semanal"),
    "preventive-maintenance": ("/preventive-maintenance", "Mantenimiento preventivo"),
}

JOB_TIMEOUTS = {
    # The post-open watcher intentionally spans roughly 90 minutes.
    "post-open-monitor": 6000.0,
    "daily-snapshot-refresh": 900.0,
    "portfolio-risk-monitor": 900.0,
    "portfolio-risk-preflight": 600.0,
    "portfolio-risk-digest": 600.0,
    "daily-outcome-evaluation": 900.0,
    "executive-report-daily": 600.0,
    "executive-report-weekly": 600.0,
    "preventive-maintenance": 600.0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def post_console(path: str, timeout: float, *, local_notify: bool = False) -> dict:
    base = os.getenv("STOCK_ULTIMUS_CONSOLE_URL", DEFAULT_CONSOLE_URL).rstrip("/")
    data = urllib.parse.urlencode({
        "source": "launchd_console_runner",
        "local_notify": "1" if local_notify else "0",
    }).encode("utf-8")
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
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "url": base + path,
                "job_id": payload.get("job_id") if isinstance(payload, dict) else None,
                "accepted_status": payload.get("status") if isinstance(payload, dict) else None,
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


def get_job_status(job_id: str, timeout: float) -> dict:
    base = os.getenv("STOCK_ULTIMUS_CONSOLE_URL", DEFAULT_CONSOLE_URL).rstrip("/")
    url = base + "/job-status?" + urllib.parse.urlencode({"id": job_id})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                payload = {}
            payload["http_status_code"] = response.status
            return payload
    except urllib.error.HTTPError as exc:
        return {"status": "ERROR", "error": f"JOB_STATUS_HTTP_{exc.code}", "http_status_code": exc.code}
    except Exception as exc:
        return {"status": "ERROR", "error": f"JOB_STATUS_UNAVAILABLE: {exc}"}


def summarize_job(job: dict) -> dict:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    return {
        "job_id": job.get("job_id"),
        "label": job.get("label"),
        "status": job.get("status"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error") or "",
        "returncode": result.get("returncode"),
        "operator_status": result.get("operator_status"),
        "remote_verification_ok": result.get("remote_verification_ok"),
        "remote_verification_status": result.get("remote_verification_status"),
        "timed_out": result.get("timed_out"),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def wait_for_job(job_id: str, *, request_timeout: float, job_timeout: float, poll_interval: float = 1.0) -> dict:
    started = time.monotonic()
    last: dict = {"job_id": job_id, "status": "RUNNING"}
    while time.monotonic() - started <= job_timeout:
        last = get_job_status(job_id, request_timeout)
        if str(last.get("status") or "").upper() in {"DONE", "ERROR"}:
            summary = summarize_job(last)
            summary["ok"] = summary.get("status") == "DONE"
            return summary
        time.sleep(max(0.05, poll_interval))
    summary = summarize_job(last)
    summary.update({
        "ok": False,
        "status": "TIMEOUT",
        "error": f"JOB_DID_NOT_FINISH_WITHIN_{int(job_timeout)}_SECONDS",
    })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Stock Ultimus local console jobs from launchd.")
    parser.add_argument("job", choices=sorted(ENDPOINTS))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--job-timeout",
        type=float,
        default=None,
        help="Maximum time to wait for the console job to finish.",
    )
    parser.add_argument(
        "--local-notify",
        action="store_true",
        help="Explicitly request local notifications for supported jobs.",
    )
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
    result["trigger"] = post_console(path, args.timeout, local_notify=args.local_notify)
    job_id = result["trigger"].get("job_id")
    if result["trigger"].get("ok") and job_id:
        job_timeout = (
            args.job_timeout
            if args.job_timeout is not None
            else JOB_TIMEOUTS.get(args.job, DEFAULT_JOB_TIMEOUT_SECONDS)
        )
        result["completion"] = wait_for_job(
            str(job_id),
            request_timeout=max(1.0, args.timeout),
            job_timeout=max(1.0, float(job_timeout)),
        )
    else:
        result["completion"] = {
            "ok": False,
            "status": "NOT_TRACKED",
            "error": "CONSOLE_DID_NOT_RETURN_JOB_ID",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["trigger"].get("ok") and result["completion"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
