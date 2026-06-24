#!/usr/bin/env python3
"""Validate read-auth middleware for sensitive Stock Ultimus surfaces."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import asyncio


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_app_module(name: str, env: dict[str, str]):
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        app_path = ROOT / "app" / "main.py"
        spec = importlib.util.spec_from_file_location(name, app_path)
        if spec is None:
            raise RuntimeError("unable to import app/main.py")
        module = importlib.util.module_from_spec(spec)
        module.__dict__["__file__"] = str(app_path)
        source = "from __future__ import annotations\n" + app_path.read_text()
        exec(compile(source, str(app_path), "exec"), module.__dict__)
        return module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeURL:
    def __init__(self, path: str):
        self.path = path


class FakeRequest:
    def __init__(self, path: str, headers: dict[str, str] | None = None):
        self.url = FakeURL(path)
        self.headers = headers or {}


async def ok_next(_request):
    return {"status_code": 200}


async def call_middleware(app_module, path: str, headers: dict[str, str] | None = None):
    return await app_module.sensitive_read_auth_middleware(FakeRequest(path, headers), ok_next)


def main() -> int:
    sys.dont_write_bytecode = True

    configured = load_app_module(
        "stock_ultimus_read_auth_configured",
        {
            "DEPLOYMENT_ENV": "production",
            "READ_ACCESS_TOKEN": "read-token-test",
            "ADMIN_DEBUG_TOKEN": "",
        },
    )

    health = asyncio.run(call_middleware(configured, "/health"))
    require(isinstance(health, dict) and health.get("status_code") == 200, f"/health should stay public: {health}")

    denied = asyncio.run(call_middleware(configured, "/v31_system_status"))
    require(getattr(denied, "status_code", None) == 401, f"sensitive read without token should be 401, got {denied}")

    allowed = asyncio.run(call_middleware(configured, "/v31_system_status", {"x-stock-ultimus-read-token": "read-token-test"}))
    require(isinstance(allowed, dict) and allowed.get("status_code") == 200, f"sensitive read with token should pass: {allowed}")

    api_key_alias = asyncio.run(call_middleware(configured, "/gpt_v31_daily_rankings", {"x-api-key": "read-token-test"}))
    require(isinstance(api_key_alias, dict) and api_key_alias.get("status_code") == 200, f"x-api-key alias should pass: {api_key_alias}")

    bearer = asyncio.run(call_middleware(configured, "/read_auth_status", {"authorization": "Bearer read-token-test"}))
    require(isinstance(bearer, dict) and bearer.get("status_code") == 200, f"bearer token should pass: {bearer}")
    body = configured.read_auth_status()
    require(body.get("read_auth_version") == "read_auth_gate_v1", f"wrong read auth version: {body}")
    require("read-token-test" not in str(body), "read auth status must not expose raw token")

    unconfigured = load_app_module(
        "stock_ultimus_read_auth_unconfigured",
        {
            "DEPLOYMENT_ENV": "production",
            "READ_ACCESS_TOKEN": "",
            "ADMIN_DEBUG_TOKEN": "",
        },
    )
    blocked = asyncio.run(call_middleware(unconfigured, "/v31_system_status"))
    require(getattr(blocked, "status_code", None) == 503, f"production without read token should be 503, got {blocked}")

    local = load_app_module(
        "stock_ultimus_read_auth_local",
        {
            "DEPLOYMENT_ENV": "local",
            "REQUIRE_READ_AUTH": "",
            "READ_ACCESS_TOKEN": "",
            "ADMIN_DEBUG_TOKEN": "",
        },
    )
    local_open = asyncio.run(call_middleware(local, "/v31_system_status"))
    require(isinstance(local_open, dict) and local_open.get("status_code") == 200, f"local dev should stay open unless REQUIRE_READ_AUTH=true: {local_open}")

    print("Validated read-auth middleware for sensitive production surfaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
