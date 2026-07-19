#!/usr/bin/env python3
"""Request official IBKR what-if margin previews without transmitting orders."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portfolio_whatif_engine as whatif_engine
from scripts import ibkr_account_profile as profiles


def rooted(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def contract_key(contract: Any) -> tuple[str, str, str, str, str]:
    strike = getattr(contract, "strike", None)
    try:
        strike_text = str(round(float(strike or 0), 4))
    except (TypeError, ValueError):
        strike_text = "0.0"
    return (
        str(getattr(contract, "symbol", None) or getattr(contract, "localSymbol", None) or "UNKNOWN").upper(),
        str(getattr(contract, "secType", None) or "UNKNOWN").upper(),
        str(getattr(contract, "lastTradeDateOrContractMonth", None) or ""),
        strike_text,
        str(getattr(contract, "right", None) or "").upper(),
    )


def request_key(request: dict[str, Any]) -> tuple[str, str, str, str, str]:
    try:
        strike = str(round(float(request.get("strike") or 0), 4))
    except (TypeError, ValueError):
        strike = "0.0"
    return (
        str(request.get("ticker") or "UNKNOWN").upper(),
        str(request.get("security_type") or "UNKNOWN").upper(),
        str(request.get("expiration") or ""),
        strike,
        str(request.get("right") or "").upper(),
    )


def open_order_fingerprint(trades: list[Any]) -> tuple[tuple[Any, ...], ...]:
    rows = []
    for trade in trades or []:
        order = getattr(trade, "order", None)
        contract = getattr(trade, "contract", None)
        status = getattr(getattr(trade, "orderStatus", None), "status", None)
        rows.append((
            getattr(order, "permId", None), getattr(order, "orderId", None),
            getattr(order, "action", None), getattr(order, "totalQuantity", None),
            contract_key(contract), status,
        ))
    return tuple(sorted(rows, key=str))


def safe_error(error: Exception, account_ids: list[str]) -> str:
    message = f"{type(error).__name__}: {error}"
    for account_id in account_ids:
        if account_id:
            message = message.replace(account_id, "[ACCOUNT_ID_REDACTED]")
    return message[:500]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebalance", default="runtime/portfolio_rebalance_latest.json")
    parser.add_argument("--policy", default="config/portfolio_whatif_policy.json")
    parser.add_argument("--profiles-file", default="runtime/ibkr_account_profiles.local.json")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    parser.add_argument("--client-id", type=int, default=87)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--json-out", default="runtime/portfolio_rebalance_whatif_latest.json")
    args = parser.parse_args()

    rebalance_payload = load_json(rooted(args.rebalance))
    policy = whatif_engine.load_policy(rooted(args.policy))
    request_build = whatif_engine.build_preview_requests(rebalance_payload, policy, candidate_id=args.candidate_id)
    if request_build.get("status") != "READY":
        result = whatif_engine.summarize(
            request_build, [], open_orders_before=0, open_orders_after=0,
            open_order_fingerprint_unchanged=True,
        )
        whatif_engine.write_result(rooted(args.json_out), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    profile_payload = load_json(rooted(args.profiles_file))
    profile_map = profile_payload.get("profiles") if isinstance(profile_payload.get("profiles"), dict) else {}
    aliases_needed = sorted({str(item.get("account_alias") or "") for item in request_build.get("requests") or []})
    account_ids: dict[str, str] = {}
    for alias in aliases_needed:
        profile = profile_map.get(alias) if isinstance(profile_map.get(alias), dict) else {}
        service = str(profile.get("keychain_service") or profiles.keychain_service(alias))
        account_id = profiles.read_keychain_value(service, timeout=10)
        if account_id:
            account_ids[alias] = account_id

    previews = []
    before_fingerprint: tuple[tuple[Any, ...], ...] = ()
    after_fingerprint: tuple[tuple[Any, ...], ...] = ()
    try:
        from ib_insync import IB, Order
        ib = IB()
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=False, timeout=args.timeout)
        ib.RequestTimeout = max(2.0, min(args.timeout, 20.0))
        managed = {str(value).strip() for value in ib.managedAccounts() or []}
        positions = list(ib.positions() or [])
        before_trades = list(ib.reqAllOpenOrders() or [])
        before_fingerprint = open_order_fingerprint(before_trades)
        for request in request_build.get("requests") or []:
            alias = str(request.get("account_alias") or "")
            account_id = account_ids.get(alias) or ""
            preview = {
                **request,
                "status": "FAILED",
                "account_alias": alias,
                "real_account_id_excluded": True,
                "what_if": True,
                "transmit": False,
                "execution_authorized": False,
                "order_created": False,
                "not_order_instruction": True,
            }
            try:
                if not account_id or account_id not in managed:
                    raise ValueError("ACCOUNT_ALIAS_NOT_AVAILABLE")
                matching = [
                    row for row in positions
                    if str(getattr(row, "account", "") or "").strip() == account_id
                    and contract_key(getattr(row, "contract", None)) == request_key(request)
                ]
                if len(matching) != 1:
                    raise ValueError("LIVE_POSITION_MATCH_NOT_UNIQUE")
                live_position = float(getattr(matching[0], "position", 0) or 0)
                quantity = float(request.get("quantity") or 0)
                expected_action = "SELL" if live_position > 0 else "BUY"
                if quantity <= 0 or quantity > abs(live_position) or request.get("action") != expected_action:
                    raise ValueError("REDUCE_ONLY_LIVE_GUARD_FAILED")
                contract = copy.copy(getattr(matching[0], "contract", None))
                if not str(getattr(contract, "exchange", "") or "").strip():
                    contract.exchange = "SMART"
                order = Order(
                    action=expected_action,
                    totalQuantity=quantity,
                    orderType="MKT",
                    tif="DAY",
                    account=account_id,
                    whatIf=True,
                    transmit=False,
                )
                if order.whatIf is not True or order.transmit is not False:
                    raise RuntimeError("WHATIF_ORDER_GUARD_FAILED")
                state = ib.whatIfOrder(contract, order)
                preview.update(whatif_engine.order_state_payload(state))
                preview["status"] = "READY" if any(
                    preview.get(key) is not None
                    for key in ("init_margin_change", "maintenance_margin_change", "commission", "maximum_commission")
                ) else "PARTIAL"
            except Exception as exc:
                preview["error"] = safe_error(exc, list(account_ids.values()))
            previews.append(preview)
        after_trades = list(ib.reqAllOpenOrders() or [])
        after_fingerprint = open_order_fingerprint(after_trades)
    except Exception as exc:
        previews.append({
            "status": "FAILED", "error": safe_error(exc, list(account_ids.values())),
            "what_if": True, "transmit": False, "execution_authorized": False,
            "order_created": False, "not_order_instruction": True,
        })
    finally:
        try:
            if "ib" in locals() and ib.isConnected():
                ib.disconnect()
        except Exception:
            pass

    unchanged = before_fingerprint == after_fingerprint
    result = whatif_engine.summarize(
        request_build,
        previews,
        open_orders_before=len(before_fingerprint),
        open_orders_after=len(after_fingerprint),
        open_order_fingerprint_unchanged=unchanged,
    )
    whatif_engine.write_result(rooted(args.json_out), result)
    print(json.dumps({
        "status": result["status"],
        "candidate_id": result["candidate_id"],
        "requested_preview_count": result["requested_preview_count"],
        "ready_preview_count": result["ready_preview_count"],
        "open_order_fingerprint_unchanged": result["open_order_fingerprint_unchanged"],
        "orders_created": result["orders_created"],
        "what_if_only": True,
        "transmit": False,
        "execution_authorized": False,
        "real_account_ids_excluded": True,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0 if result["status"] in {"READY", "PARTIAL"} and unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
