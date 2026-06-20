#!/usr/bin/env python3
"""Manage resend email limits for 2MV APP.

This script updates the runtime config file used by app/main.py to cap resend usage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("runtime/resend_email_config.json")
DEFAULT_USAGE_PATH = Path("runtime/resend_email_usage.json")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(config: dict[str, Any], path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))


def load_usage(path: Path = DEFAULT_USAGE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"date": None, "count": 0}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"date": None, "count": 0}
    except Exception:
        return {"date": None, "count": 0}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View or update resend daily email limit config for 2MV APP."
    )
    parser.add_argument(
        "--plan-limit",
        type=int,
        help="Total daily plan emails available for this service's plan",
    )
    parser.add_argument(
        "--percent",
        type=int,
        help="Share of the plan reserved for this service (0-100)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current resend config and usage",
    )
    args = parser.parse_args()

    config = load_config()
    usage = load_usage()

    if args.plan_limit is None and args.percent is None and not args.show:
        parser.print_help()
        return

    updated = False
    if args.plan_limit is not None:
        if args.plan_limit < 0:
            raise SystemExit("plan_limit must be non-negative")
        config["plan_limit"] = args.plan_limit
        updated = True
    if args.percent is not None:
        if args.percent < 0 or args.percent > 100:
            raise SystemExit("percent must be between 0 and 100")
        config["percent"] = args.percent
        updated = True

    if updated:
        save_config(config)
        print("Updated resend config:")
    else:
        print("Current resend config:")

    print(json.dumps(config, ensure_ascii=False, indent=2))
    print("\nCurrent usage:")
    print(json.dumps(usage, ensure_ascii=False, indent=2))

    if args.plan_limit is not None or args.percent is not None:
        print("\nConfig saved to:", str(DEFAULT_CONFIG_PATH))


if __name__ == "__main__":
    main()
