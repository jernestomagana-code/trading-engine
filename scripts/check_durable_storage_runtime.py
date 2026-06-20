#!/usr/bin/env python3
"""Validate Supabase durable runtime adapters without contacting Supabase."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class FakeRequests:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.rows_by_table = {}

    def post(self, url, headers=None, params=None, json=None, timeout=None):
        table = url.rstrip("/").split("/")[-1]
        rows = json or []
        self.posts.append({
            "table": table,
            "headers": headers or {},
            "params": params or {},
            "rows": rows,
            "timeout": timeout,
        })
        self.rows_by_table.setdefault(table, [])
        for row in rows:
            pk = "event_id" if "event_id" in row else "id"
            existing = next((item for item in self.rows_by_table[table] if item.get(pk) == row.get(pk)), None)
            if existing:
                existing.update(row)
            else:
                self.rows_by_table[table].append(dict(row))
        return FakeResponse(204)

    def get(self, url, headers=None, params=None, timeout=None):
        table = url.rstrip("/").split("/")[-1]
        self.gets.append({
            "table": table,
            "headers": headers or {},
            "params": params or {},
            "timeout": timeout,
        })
        return FakeResponse(200, list(self.rows_by_table.get(table, [])))


def load_app_module():
    env = {
        "RUNTIME_STORAGE_MODE": "supabase",
        "DURABLE_STORAGE_PROVIDER": "supabase",
        "DURABLE_STORAGE_CONTRACT_VERSION": "durable_storage_contract_v1",
        "DURABLE_STORAGE_ENABLED": "true",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "test-service-role-key",
        "STOCK_ULTIMUS_TENANT_ID": "tenant-test",
        "STOCK_ULTIMUS_ACCOUNT_SCOPE": "account-test",
    }
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        app_path = ROOT / "app" / "main.py"
        spec = importlib.util.spec_from_file_location("stock_ultimus_app_durable_runtime_check", app_path)
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


def main() -> int:
    sys.dont_write_bytecode = True
    audit_path = ROOT / "runtime" / "stock_ultimus_audit_log.json"
    audit_backup = audit_path.read_text() if audit_path.exists() else None
    app = load_app_module()
    fake = FakeRequests()
    app.requests = fake

    try:
        require(app._durable_runtime_enabled() is True, "durable runtime should be enabled for Supabase test config")

        decision = {
            "decision_id": "DEC-TEST",
            "recorded_at": "2026-06-19T12:00:00+00:00",
            "ticker": "AAPL",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
        }
        app._v32_write_retained_list(app._V32_DECISION_JOURNAL_FILE, [decision])
        loaded_decisions = app._v32_load_decision_journal()
        require(loaded_decisions == [decision], f"decision payload did not round-trip through durable adapter: {loaded_decisions}")

        outcome = {
            "outcome_id": "OUT-TEST",
            "decision_id": "DEC-TEST",
            "recorded_at": "2026-06-19T13:00:00+00:00",
            "ticker": "AAPL",
            "strategy": "NAKED_PUT",
            "outcome": "WIN",
        }
        app._v32_write_retained_list(app._V32_OUTCOMES_JOURNAL_FILE, [outcome])
        loaded_outcomes = app._v32_load_outcomes_journal()
        require(loaded_outcomes == [outcome], f"outcome payload did not round-trip through durable adapter: {loaded_outcomes}")

        audit_event = app._audit_event("DURABLE_RUNTIME_TEST", {"decision_id": "DEC-TEST"}, source="durable_runtime_check")
        require(audit_event and audit_event.get("event_type") == "DURABLE_RUNTIME_TEST", f"audit event not created: {audit_event}")
        audit_events = app._audit_events(limit=10)
        require(any(item.get("event_type") == "DURABLE_RUNTIME_TEST" for item in audit_events), f"audit event not loaded from durable adapter: {audit_events}")

        posted_tables = {item.get("table") for item in fake.posts}
        require("stock_ultimus_decision_journal" in posted_tables, f"decision table not posted: {fake.posts}")
        require("stock_ultimus_outcome_journal" in posted_tables, f"outcome table not posted: {fake.posts}")
        require("stock_ultimus_audit_events" in posted_tables, f"audit table not posted: {fake.posts}")
        for post in fake.posts:
            for row in post.get("rows") or []:
                require(row.get("tenant_id") == "tenant-test", f"tenant_id missing from durable row: {row}")
                require(row.get("account_scope") == "account-test", f"account_scope missing from durable row: {row}")
                require("payload_hash" in row, f"payload_hash missing from durable row: {row}")
    finally:
        if audit_backup is None:
            try:
                audit_path.unlink()
            except FileNotFoundError:
                pass
        else:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(audit_backup)

    print("Validated Supabase durable runtime adapters for V32 journals and audit events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
