#!/usr/bin/env python3
"""
Run the V31 daily operational audit against production.

This audit is intentionally cloud/read-only:
- it does not connect to IBKR,
- it does not use snapshot ingest credentials,
- it does not send email,
- it does not place or authorize orders.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_READ_TOKEN_SERVICE = "stock-ultimus-read-access-token"


@dataclass
class AuditCheck:
    name: str
    ok: bool
    severity: str
    detail: str = ""
    status_code: int | None = None
    endpoint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity,
            "detail": self.detail,
        }
        if self.status_code is not None:
            item["status_code"] = self.status_code
        if self.endpoint:
            item["endpoint"] = self.endpoint
        return item


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_get(data: Any, *path: str, default: Any = None) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def read_keychain_token(service: str, account: str | None = None) -> str:
    cmd = ["security", "find-generic-password"]
    if account:
        cmd.extend(["-a", account])
    cmd.extend(["-s", service, "-w"])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\n")


def resolve_read_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token
    env_token = os.getenv("READ_ACCESS_TOKEN", "")
    if env_token:
        return env_token
    return read_keychain_token(args.read_token_service, args.keychain_account)


def auth_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"X-Stock-Ultimus-Read-Token": token}


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    timeout: int = 20,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, int | None, Any]:
    headers = auth_headers(token)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, headers=headers, data=data, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, resp.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body[:500]}
        return False, exc.code, parsed
    except Exception as exc:
        return False, None, {"error": str(exc)}


def protected_get(base_url: str, path: str, token: str, timeout: int) -> tuple[bool, int | None, Any]:
    return request_json("GET", base_url + path, token=token, timeout=timeout)


def protected_post(base_url: str, path: str, token: str, timeout: int) -> tuple[bool, int | None, Any]:
    return request_json("POST", base_url + path, token=token, timeout=timeout, payload={})


def dangerous_guardrail_paths(data: Any, prefix: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}"
            if key == "execution_authorized" and value is True:
                failures.append(path)
            if key == "can_operate" and value is True:
                failures.append(path)
            failures.extend(dangerous_guardrail_paths(value, path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            failures.extend(dangerous_guardrail_paths(item, f"{prefix}[{index}]"))
    return failures


def guardrail_check(name: str, payload: Any, endpoint: str, require_top_level_no_order: bool = True) -> AuditCheck:
    if not isinstance(payload, dict):
        return AuditCheck(name, False, "FAIL", "payload is not a JSON object", endpoint=endpoint)
    failures = dangerous_guardrail_paths(payload)
    if require_top_level_no_order and payload.get("not_order_instruction") is not True:
        failures.insert(0, "$.not_order_instruction")
    return AuditCheck(
        name,
        not failures,
        "FAIL",
        "ok" if not failures else "unsafe guardrail fields: " + ", ".join(failures[:10]),
        endpoint=endpoint,
    )


def endpoint_ok_check(
    name: str,
    ok: bool,
    status_code: int | None,
    payload: Any,
    endpoint: str,
    *,
    severity: str = "FAIL",
    expected_engine: str | None = None,
) -> AuditCheck:
    if not ok or status_code != 200:
        return AuditCheck(name, False, severity, f"HTTP {status_code}", status_code=status_code, endpoint=endpoint)
    if expected_engine and safe_get(payload, "engine") != expected_engine:
        return AuditCheck(
            name,
            False,
            severity,
            f"engine={safe_get(payload, 'engine')}",
            status_code=status_code,
            endpoint=endpoint,
        )
    return AuditCheck(name, True, severity, "ok", status_code=status_code, endpoint=endpoint)


def planned_checks(limit: int) -> list[dict[str, Any]]:
    return [
        {"name": "health_public", "method": "GET", "path": "/health", "token": False},
        {"name": "read_auth_enforced", "method": "GET", "path": "/v31_system_status", "token": False},
        {"name": "system_status", "method": "GET", "path": "/v31_system_status", "token": True},
        {"name": "production_readiness", "method": "GET", "path": "/v31_production_readiness", "token": True},
        {"name": "data_pipeline_status", "method": "GET", "path": "/v31_data_pipeline_status", "token": True},
        {"name": "trading_day_readiness", "method": "GET", "path": "/v31_trading_day_readiness", "token": True},
        {"name": "monitor_preview", "method": "GET", "path": "/v31_monitor_notify/preview?force=true", "token": True},
        {"name": "manual_reviews", "method": "GET", "path": f"/v31_manual_reviews?limit={limit}", "token": True},
        {"name": "manual_review_learning", "method": "GET", "path": f"/v31_manual_review_learning?limit={limit}", "token": True},
        {
            "name": "manual_review_evaluation_dry_run",
            "method": "POST",
            "path": f"/v31_evaluate_manual_reviews?limit={min(limit, 25)}&checkpoint=EOD&dry_run=true",
            "token": True,
        },
        {
            "name": "weekly_learning_preview",
            "method": "GET",
            "path": f"/v31_manual_review_learning_notify/preview?force=true&limit={limit}",
            "token": True,
        },
    ]


def summarize(checks: list[AuditCheck]) -> dict[str, int]:
    failed = [item for item in checks if not item.ok and item.severity == "FAIL"]
    warnings = [item for item in checks if not item.ok and item.severity == "WARN"]
    return {
        "total": len(checks),
        "passed": len([item for item in checks if item.ok]),
        "warnings": len(warnings),
        "failed": len(failed),
    }


def status_from_summary(summary: dict[str, int]) -> str:
    if summary["failed"]:
        return "FAIL"
    if summary["warnings"]:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    limit = max(1, min(int(args.limit), 500))
    if args.dry_run:
        return {
            "engine": "V31_DAILY_OPERATIONAL_AUDIT",
            "generated_at": now_iso(),
            "base_url": base_url,
            "dry_run": True,
            "status": "DRY_RUN",
            "planned_checks": planned_checks(limit),
            "checks": [],
            "summary": {"total": 0, "passed": 0, "warnings": 0, "failed": 0},
            "secrets_printed": False,
            "uses_ingest_token": False,
            "sends_email": False,
            "touches_ibkr": False,
            "not_order_instruction": True,
            "execution_authorized": False,
        }

    token = resolve_read_token(args)
    checks: list[AuditCheck] = []
    if not token:
        checks.append(AuditCheck("read_token_available", False, "FAIL", "missing READ_ACCESS_TOKEN or Keychain token"))
        summary = summarize(checks)
        return {
            "engine": "V31_DAILY_OPERATIONAL_AUDIT",
            "generated_at": now_iso(),
            "base_url": base_url,
            "dry_run": False,
            "status": status_from_summary(summary),
            "checks": [item.as_dict() for item in checks],
            "summary": summary,
            "secrets_printed": False,
            "uses_ingest_token": False,
            "sends_email": False,
            "touches_ibkr": False,
            "not_order_instruction": True,
            "execution_authorized": False,
        }
    checks.append(AuditCheck("read_token_available", True, "FAIL", "token resolved without printing it"))

    ok, status_code, health = request_json("GET", base_url + "/health", timeout=args.timeout)
    checks.append(endpoint_ok_check("health_public", ok, status_code, health, "/health"))
    checks.append(AuditCheck(
        "health_analysis_only",
        safe_get(health, "operating_mode") == "ANALYSIS_ONLY",
        "FAIL",
        f"operating_mode={safe_get(health, 'operating_mode')}",
        status_code=status_code,
        endpoint="/health",
    ))

    denied_ok, denied_status, _ = request_json("GET", base_url + "/v31_system_status", timeout=args.timeout)
    checks.append(AuditCheck(
        "read_auth_enforced",
        denied_status in {401, 503} and not denied_ok,
        "FAIL",
        f"unauthorized_status={denied_status}",
        status_code=denied_status,
        endpoint="/v31_system_status",
    ))

    responses: dict[str, tuple[str, bool, int | None, Any]] = {}
    get_endpoints = {
        "system_status": "/v31_system_status",
        "production_readiness": "/v31_production_readiness",
        "data_pipeline_status": "/v31_data_pipeline_status",
        "trading_day_readiness": "/v31_trading_day_readiness",
        "monitor_preview": "/v31_monitor_notify/preview?force=true",
        "manual_reviews": f"/v31_manual_reviews?{parse.urlencode({'limit': limit})}",
        "manual_review_learning": f"/v31_manual_review_learning?{parse.urlencode({'limit': limit})}",
        "weekly_learning_preview": f"/v31_manual_review_learning_notify/preview?{parse.urlencode({'force': 'true', 'limit': limit})}",
    }
    for name, endpoint in get_endpoints.items():
        ok, code, payload = protected_get(base_url, endpoint, token, args.timeout)
        responses[name] = (endpoint, ok, code, payload)

    eval_endpoint = "/v31_evaluate_manual_reviews?" + parse.urlencode(
        {"limit": min(limit, 25), "checkpoint": "EOD", "dry_run": "true"}
    )
    responses["manual_review_evaluation_dry_run"] = (
        eval_endpoint,
        *protected_post(base_url, eval_endpoint, token, args.timeout),
    )

    checks.append(endpoint_ok_check("system_status_ok", *responses["system_status"][1:], responses["system_status"][0]))
    checks.append(guardrail_check("system_status_guardrails", responses["system_status"][3], responses["system_status"][0]))

    readiness_endpoint, readiness_ok, readiness_code, readiness = responses["production_readiness"]
    checks.append(endpoint_ok_check("production_readiness_ok", readiness_ok, readiness_code, readiness, readiness_endpoint))
    checks.append(AuditCheck(
        "production_readiness_ready",
        safe_get(readiness, "status") == "READY",
        "FAIL",
        f"status={safe_get(readiness, 'status')} blockers={len(safe_get(readiness, 'blockers', default=[]))}",
        status_code=readiness_code,
        endpoint=readiness_endpoint,
    ))
    checks.append(guardrail_check("production_readiness_guardrails", readiness, readiness_endpoint, require_top_level_no_order=True))

    pipeline_endpoint, pipeline_ok, pipeline_code, pipeline = responses["data_pipeline_status"]
    checks.append(endpoint_ok_check("pipeline_status_endpoint_ok", pipeline_ok, pipeline_code, pipeline, pipeline_endpoint))
    pipeline_status = safe_get(pipeline, "status")
    checks.append(AuditCheck(
        "pipeline_snapshot_available",
        pipeline_status == "OK",
        "WARN",
        f"status={pipeline_status} rows_found={safe_get(pipeline, 'rows_found')}",
        status_code=pipeline_code,
        endpoint=pipeline_endpoint,
    ))
    checks.append(guardrail_check("pipeline_guardrails", pipeline, pipeline_endpoint))

    trading_day_endpoint, trading_day_ok, trading_day_code, trading_day = responses["trading_day_readiness"]
    checks.append(endpoint_ok_check(
        "trading_day_readiness_ok",
        trading_day_ok,
        trading_day_code,
        trading_day,
        trading_day_endpoint,
        expected_engine="V31_TRADING_DAY_READINESS",
    ))
    checks.append(AuditCheck(
        "trading_day_readiness_not_action_required",
        safe_get(trading_day, "status") != "ACTION_REQUIRED",
        "FAIL",
        f"status={safe_get(trading_day, 'status')} blockers={safe_get(trading_day, 'blockers', default=[])}",
        status_code=trading_day_code,
        endpoint=trading_day_endpoint,
    ))
    checks.append(AuditCheck(
        "trading_day_readiness_pipeline_ready",
        safe_get(trading_day, "status") != "WAIT_PIPELINE",
        "WARN",
        f"status={safe_get(trading_day, 'status')} warnings={safe_get(trading_day, 'warnings', default=[])}",
        status_code=trading_day_code,
        endpoint=trading_day_endpoint,
    ))
    checks.append(guardrail_check("trading_day_readiness_guardrails", trading_day, trading_day_endpoint))

    for name, expected_engine in [
        ("monitor_preview", "V31_PIPELINE_MONITOR_EMAIL"),
        ("manual_reviews", "V31_MANUAL_REVIEW_JOURNAL"),
        ("manual_review_learning", "V31_MANUAL_REVIEW_LEARNING"),
        ("manual_review_evaluation_dry_run", "V31_MANUAL_REVIEW_AUTO_EVALUATION"),
        ("weekly_learning_preview", "V31_WEEKLY_LEARNING_EMAIL"),
    ]:
        endpoint, ok, code, payload = responses[name]
        checks.append(endpoint_ok_check(f"{name}_ok", ok, code, payload, endpoint, expected_engine=expected_engine))
        checks.append(guardrail_check(f"{name}_guardrails", payload, endpoint))

    summary = summarize(checks)
    return {
        "engine": "V31_DAILY_OPERATIONAL_AUDIT",
        "generated_at": now_iso(),
        "base_url": base_url,
        "dry_run": False,
        "status": status_from_summary(summary),
        "pipeline": {
            "status": pipeline_status,
            "rows_found": safe_get(pipeline, "rows_found"),
            "master_snapshot_available": safe_get(pipeline, "master_snapshot_available"),
            "freshness": safe_get(pipeline, "freshness", default={}),
        },
        "trading_day_readiness": {
            "status": safe_get(responses["trading_day_readiness"][3], "status"),
            "blockers": safe_get(responses["trading_day_readiness"][3], "blockers", default=[]),
            "warnings": safe_get(responses["trading_day_readiness"][3], "warnings", default=[]),
            "freshness": safe_get(responses["trading_day_readiness"][3], "freshness", default={}),
        },
        "manual_reviews": {
            "review_count": safe_get(responses["manual_reviews"][3], "review_count"),
            "recent_count": len(safe_get(responses["manual_reviews"][3], "recent_reviews", default=[]) or []),
        },
        "learning": {
            "review_count": safe_get(responses["manual_review_learning"][3], "review_count"),
            "evaluated_count": safe_get(responses["manual_review_learning"][3], "evaluated_count"),
            "needs_more_data": safe_get(responses["manual_review_learning"][3], "needs_more_data"),
        },
        "checks": [item.as_dict() for item in checks],
        "summary": summary,
        "secrets_printed": False,
        "uses_ingest_token": False,
        "sends_email": False,
        "touches_ibkr": False,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default="")
    parser.add_argument("--read-token-service", default=DEFAULT_READ_TOKEN_SERVICE)
    parser.add_argument("--keychain-account", default=os.getenv("USER", ""))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    result = run_audit(build_parser().parse_args())
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.get("status") in {"PASS", "PASS_WITH_WARNINGS", "DRY_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
