#!/usr/bin/env python3
"""Verify production read-auth against a deployed Stock Ultimus service."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def request_json(url: str, token: str | None = None) -> tuple[int, dict]:
    headers = {}
    if token:
        headers["X-Stock-Ultimus-Read-Token"] = token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:500]}
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"))
    parser.add_argument("--token", default=os.getenv("READ_ACCESS_TOKEN", ""))
    args = parser.parse_args()

    if not args.base_url:
        print("Missing --base-url or PUBLIC_BASE_URL", file=sys.stderr)
        return 2
    if not args.token:
        print("Missing --token or READ_ACCESS_TOKEN", file=sys.stderr)
        return 2

    health_status, health = request_json(f"{args.base_url}/health")
    if health_status != 200:
        print(f"/health expected 200, got {health_status}: {health}", file=sys.stderr)
        return 1

    denied_status, _ = request_json(f"{args.base_url}/v31_system_status")
    if denied_status not in {401, 503}:
        print(f"/v31_system_status without token expected 401/503, got {denied_status}", file=sys.stderr)
        return 1

    allowed_status, allowed = request_json(f"{args.base_url}/v31_system_status", args.token)
    if allowed_status != 200:
        print(f"/v31_system_status with token expected 200, got {allowed_status}: {allowed}", file=sys.stderr)
        return 1
    if allowed.get("not_order_instruction") is not True:
        print("Authorized status did not preserve no-order guardrail", file=sys.stderr)
        return 1

    readiness_status, readiness = request_json(f"{args.base_url}/production_readiness", args.token)
    if readiness_status != 200:
        print(f"/production_readiness with token expected 200, got {readiness_status}: {readiness}", file=sys.stderr)
        return 1

    print("Production read-auth verified without exposing token.")
    print(json.dumps({
        "base_url": args.base_url,
        "health_status": health_status,
        "unauthorized_status": denied_status,
        "authorized_status": allowed_status,
        "production_readiness_status": readiness.get("status"),
        "read_auth": readiness.get("read_auth"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
