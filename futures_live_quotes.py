"""Read-only, bounded IBKR quotes for explicitly identified CME contracts.

Continuous symbols are never resolved by guessing a rollover date.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import math
import os
import re
import threading
import time

from alert_lifecycle import alert_lifecycle_state

_lock = threading.Lock()
_cache = {}
_pending = set()


def contract_identity(event):
    raw = event.get("raw_payload") or {}
    ticker = str(event.get("ticker") or event.get("symbol") or "").upper()
    contract = str(event.get("current_contract") or raw.get("current_contract") or ticker).upper()
    if ":" in contract:
        exchange, contract = contract.split(":", 1)
        if exchange not in {"CME", "CME_MINI"}:
            return None
    match = re.fullmatch(r"(MNQ|MES)([HMUZ])(20\d{2})", contract)
    if not match:
        return None
    root, month, year = match.groups()
    if ticker.split(":")[-1] not in {contract, root + "1!"}:
        return None
    return {"symbol": root, "month": year + {"H": "03", "M": "06", "U": "09", "Z": "12"}[month],
            "contract": contract, "ticker": ticker}


def normalized_quote(identity, ticker, bid, ask, observed_at):
    if getattr(ticker, "marketDataType", None) != 1:
        return {"quote_status": "LIVE_DATA_UNAVAILABLE"}
    if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in (bid, ask)) or ask < bid:
        return {"quote_status": "LIVE_DATA_UNAVAILABLE"}
    return {"quote_status": "LIVE", "quote_symbol": identity["ticker"],
            "quote_contract": identity["contract"], "quote_source": "IBKR_REALTIME_BID_ASK",
            "quote_timestamp": observed_at, "bid": bid, "ask": ask}


def read_quote(identity):
    # Called in one background worker; no order API is used.
    from ib_insync import IB, Future
    asyncio.set_event_loop(asyncio.new_event_loop())
    ib = IB()
    contract = None
    try:
        ib.RequestTimeout = 4
        ib.connect("127.0.0.1", int(os.getenv("IBKR_PORT", "7496")),
                   clientId=193, readonly=True, timeout=4)
        details = ib.reqContractDetails(Future(identity["symbol"], identity["month"], "CME", currency="USD"))
        contracts = [detail.contract for detail in details]
        if len(contracts) != 1:
            return {"quote_status": "CONTRACT_UNRESOLVED"}
        contract = contracts[0]
        if contract.symbol != identity["symbol"] or not contract.lastTradeDateOrContractMonth.startswith(identity["month"]):
            return {"quote_status": "CONTRACT_MISMATCH"}
        schedule = {"contract": identity["contract"], "timezone": details[0].timeZoneId,
                    "trading_hours": details[0].tradingHours, "observed_at": datetime.now(timezone.utc).isoformat()}
        ib.reqMarketDataType(1)
        ticker = ib.reqMktData(contract, "", False, False)
        prices = {}
        def updated(tick):
            for update in tick.ticks:
                if update.tickType in (1, 2):
                    prices[update.tickType] = update.price
        ticker.updateEvent += updated
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            ib.sleep(0.1)
            if 1 in prices and 2 in prices:
                return {**normalized_quote(identity, ticker, prices[1], prices[2], datetime.now(timezone.utc).isoformat()), "contract_schedule": schedule}
        return {"quote_status": "LIVE_DATA_UNAVAILABLE", "contract_schedule": schedule}
    except Exception:
        # Never expose connection/account details in a user-facing error.
        return {"quote_status": "TWS_UNAVAILABLE"}
    finally:
        if contract is not None and ib.isConnected():
            ib.cancelMktData(contract)
        ib.disconnect()
        asyncio.get_event_loop().close()


def _refresh(identity):
    key = identity["ticker"] + "|" + identity["contract"]
    try:
        result = read_quote(identity)
    except Exception:
        result = {"quote_status": "TWS_UNAVAILABLE"}
    with _lock:
        _cache[key] = (time.monotonic(), result)
        _pending.discard(key)


def enrich_event(event):
    output = dict(event)
    symbol = str(event.get("ticker") or event.get("symbol") or "").upper().split(":")[-1]
    if not re.fullmatch(r"(?:MNQ|MES)(?:1!|[HMUZ]20\d{2})", symbol):
        return output
    if alert_lifecycle_state(event)["lifecycle_state"] != "LIVE":
        return output
    identity = contract_identity(event)
    if identity is None:
        output["quote_status"] = "EXACT_CONTRACT_REQUIRED"
        return output
    key = identity["ticker"] + "|" + identity["contract"]
    with _lock:
        checked, quote = _cache.get(key, (0, {}))
        if time.monotonic() - checked >= 10 and not _pending:
            _pending.add(key)
            threading.Thread(target=_refresh, args=(identity,), daemon=True).start()
        quote = dict(quote)
    schedule = quote.pop("contract_schedule", None)
    if isinstance(schedule, dict) and schedule.get("contract") == identity["contract"]:
        output["contract_schedule"] = schedule
    else:
        output.pop("contract_schedule", None)
    if quote.get("quote_status") == "LIVE":
        output.update(quote)
        direction = str(event.get("direction") or event.get("breakout_direction") or "").upper()
        output["current_price"] = quote["ask"] if direction == "LONG" else quote["bid"] if direction == "SHORT" else None
    else:
        output["quote_status"] = quote.get("quote_status", "CONNECTING")
    return output


def enrich_operator(payload):
    output = deepcopy(payload)
    data = output.get("data") or {}
    data["active_alerts"] = [enrich_event(item) for item in data.get("active_alerts", [])]
    daily = (data.get("intraday_futures") or {}).get("daily_summary") or {}
    if daily.get("latest_signal"):
        daily["latest_signal"] = enrich_event(daily["latest_signal"])
    daily["recent_events"] = [enrich_event(item) for item in daily.get("recent_events", [])]
    return output
