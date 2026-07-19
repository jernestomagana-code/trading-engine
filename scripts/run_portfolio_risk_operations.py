#!/usr/bin/env python3
"""Run the local portfolio-risk operations cycle without placing orders."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import broker_control_tower as control_tower
import portfolio_risk_engine as risk_engine
import portfolio_risk_operations as operations
import portfolio_risk_store as risk_store


def rooted_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


@contextlib.contextmanager
def exclusive_operation_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _minutes(value: str) -> int:
    hour, minute = str(value or "00:00").split(":", 1)
    return int(hour) * 60 + int(minute)


def within_monitor_window(reference: datetime, config: dict[str, Any]) -> tuple[bool, str]:
    try:
        local = reference.astimezone(ZoneInfo(str(config.get("timezone") or "America/New_York")))
    except Exception:
        local = reference.astimezone(timezone.utc)
    if config.get("weekday_monitoring_only", True) and local.weekday() >= 5:
        return False, "WEEKEND"
    window = config.get("monitor_window") if isinstance(config.get("monitor_window"), dict) else {}
    now_minutes = local.hour * 60 + local.minute
    try:
        start = _minutes(window.get("start") or "07:00")
        end = _minutes(window.get("end") or "17:30")
    except (TypeError, ValueError):
        return False, "INVALID_MONITOR_WINDOW"
    return (start <= now_minutes <= end, "ACTIVE_WINDOW" if start <= now_minutes <= end else "OUTSIDE_ACTIVE_WINDOW")


def refresh_broker(runtime_dir: Path, timeout: int = 90) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "refresh_multi_account_control_tower.py"),
        "--runtime-dir",
        str(runtime_dir),
        "--profiles-file",
        str(runtime_dir / "ibkr_account_profiles.local.json"),
        "--active-file",
        str(runtime_dir / "ibkr_account_active_profile.json"),
        "--json-out",
        str(runtime_dir / "broker_control_tower_latest.json"),
        "--risk-json-out",
        str(runtime_dir / "portfolio_risk_latest.json"),
        "--risk-history-out",
        str(runtime_dir / "portfolio_risk_history.json"),
    ]
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=timeout)
        return {
            "attempted": True,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
            "sensitive_identifiers_excluded": True,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "attempted": True,
            "ok": False,
            "returncode": None,
            "error": f"{type(exc).__name__}: {exc}",
            "sensitive_identifiers_excluded": True,
        }


def send_macos_notification(item: dict[str, Any]) -> dict[str, Any]:
    title = f"Stock Ultimus · {item.get('severity') or 'RISK'}"
    body = f"{item.get('account_alias') or 'SISTEMA'}: {item.get('title') or item.get('rule') or 'Alerta de cartera'}"
    script = f"display notification {json.dumps(body[:220])} with title {json.dumps(title[:80])}"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"sent": False, "provider": "macos_notification_center", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "sent": proc.returncode == 0,
        "provider": "macos_notification_center",
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-300:],
    }


def evaluate_current(runtime_dir: Path, policy_path: Path, reference: datetime) -> dict[str, Any]:
    tower = operations.load_json(runtime_dir / "broker_control_tower_latest.json")
    policy = risk_engine.load_policy(policy_path)
    evaluation = risk_engine.evaluate(tower, policy, reference=reference)
    risk_store.persist_evaluation(runtime_dir, evaluation)
    return operations.load_json(runtime_dir / risk_store.LATEST_FILENAME)


def run_cycle(args: argparse.Namespace, *, reference: datetime | None = None) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    runtime_dir = rooted_path(args.runtime_dir)
    config = operations.load_config(rooted_path(args.operations_config))
    in_window, window_reason = within_monitor_window(reference, config)
    status_path = runtime_dir / "portfolio_risk_operations_status.json"
    if args.mode == "monitor" and not args.force_window and not in_window:
        result = {
            "operations_version": operations.OPERATIONS_VERSION,
            "generated_at": reference.isoformat(),
            "mode": args.mode,
            "status": "SKIPPED",
            "reason": window_reason,
            "broker_refresh_attempted": False,
            "notification_sent": False,
            "sensitive_identifiers_excluded": True,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
            "not_order_instruction": True,
        }
        control_tower.write_control_tower(status_path, result)
        return result

    broker_result = {"attempted": False, "ok": None}
    if args.refresh_broker:
        broker_result = refresh_broker(runtime_dir, timeout=args.refresh_timeout)
    evaluation = evaluate_current(runtime_dir, rooted_path(args.policy), reference)
    action_state = operations.load_json(runtime_dir / "portfolio_risk_actions.json")
    decorated = operations.decorate_evaluation(evaluation, action_state, reference=reference)
    outbox_path = runtime_dir / "portfolio_risk_outbox.json"
    previous_outbox = operations.load_json(outbox_path)
    outbox, new_items = operations.build_outbox(decorated, previous_outbox, config, reference=reference)

    local_enabled = bool(args.local_notify or config.get("local_notifications_enabled"))
    delivery_results = []
    delivered_ids: set[str] = set()
    if local_enabled:
        pending_items = [item for item in (outbox.get("items") or []) if isinstance(item, dict) and item.get("status") == "PENDING"]
        for item in pending_items:
            delivery = send_macos_notification(item)
            delivery_results.append({"message_id": item.get("message_id"), **delivery})
            if delivery.get("sent"):
                delivered_ids.add(str(item.get("message_id") or ""))
    if delivered_ids:
        outbox = operations.mark_outbox_delivery(outbox, delivered_ids, reference=reference)
    control_tower.write_control_tower(outbox_path, outbox)

    digest, markdown = operations.build_digest(decorated, outbox, reference=reference)
    operations.write_digest(
        runtime_dir / "portfolio_risk_digest_latest.json",
        runtime_dir / "portfolio_risk_digest_latest.md",
        digest,
        markdown,
    )
    result = {
        "operations_version": operations.OPERATIONS_VERSION,
        "generated_at": reference.isoformat(),
        "mode": args.mode,
        "status": "COMPLETED",
        "window_reason": window_reason,
        "broker_refresh": broker_result,
        "risk_status": decorated.get("status"),
        "decision_support": decorated.get("decision_support"),
        "risk_score": decorated.get("risk_score"),
        "alert_lifecycle_counts": decorated.get("alert_lifecycle_counts") or {},
        "new_outbox_count": len(new_items),
        "pending_outbox_count": outbox.get("pending_count"),
        "local_notifications_enabled": local_enabled,
        "local_notification_results": delivery_results,
        "external_notification_sent": False,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }
    control_tower.write_control_tower(status_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["monitor", "digest", "preflight"], default="monitor")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--policy", default="config/portfolio_risk_policy.json")
    parser.add_argument("--operations-config", default="config/portfolio_risk_operations.json")
    parser.add_argument("--refresh-broker", action="store_true")
    parser.add_argument("--refresh-timeout", type=int, default=90)
    parser.add_argument("--force-window", action="store_true")
    parser.add_argument("--local-notify", action="store_true", help="Explicitly enable local macOS notifications for new outbox items.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir = rooted_path(args.runtime_dir)
    with exclusive_operation_lock(runtime_dir / ".portfolio_risk_operations.lock") as acquired:
        if acquired:
            result = run_cycle(args)
        else:
            result = {
                "operations_version": operations.OPERATIONS_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": args.mode,
                "status": "SKIPPED",
                "reason": "CYCLE_ALREADY_RUNNING",
                "external_notification_sent": False,
                "sensitive_identifiers_excluded": True,
                "execution_authorized": False,
                "automatic_liquidation_authorized": False,
                "not_order_instruction": True,
            }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
