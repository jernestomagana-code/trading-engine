#!/usr/bin/env python3
"""
Probe one IBKR option quote in read-only mode.

This diagnostic tool is intentionally isolated from ibkr_bridge.py:
- it never places orders,
- it does not publish to Render,
- it only connects to TWS/Gateway read-only and reports quote availability.

Use it on a market-open day to identify which IBKR market data path provides
bid/ask/greeks for a specific option contract.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ib_insync import IB, Stock, Option


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7496
DEFAULT_CLIENT_ID = 91
DEFAULT_MARKET_DATA_TYPES = [1, 2, 3, 4]  # live, frozen, delayed, delayed frozen


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any, allow_negative: bool = False) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        if not allow_negative and number <= 0:
            return None
        return round(number, 4)
    except Exception:
        return None


def safe_round(value: Any, digits: int = 4) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, digits)
    except Exception:
        return None


def calculate_spread_pct(bid: float | None, ask: float | None, mid: float | None) -> float | None:
    if bid is None or ask is None or mid is None:
        return None
    if bid <= 0 or ask <= 0 or mid <= 0:
        return None
    spread = ask - bid
    if spread < 0:
        return None
    return safe_round((spread / mid) * 100, 2)


def greeks_from_ticker(ticker: Any) -> dict[str, float | None]:
    greeks = (
        getattr(ticker, "modelGreeks", None)
        or getattr(ticker, "bidGreeks", None)
        or getattr(ticker, "askGreeks", None)
        or getattr(ticker, "lastGreeks", None)
    )
    if not greeks:
        return {"iv": None, "delta": None, "gamma": None, "theta": None, "vega": None}
    return {
        "iv": safe_round(getattr(greeks, "impliedVol", None), 4),
        "delta": safe_round(getattr(greeks, "delta", None), 4),
        "gamma": safe_round(getattr(greeks, "gamma", None), 6),
        "theta": safe_round(getattr(greeks, "theta", None), 4),
        "vega": safe_round(getattr(greeks, "vega", None), 4),
    }


def normalize_quote(ticker: Any, greeks: dict[str, float | None]) -> dict[str, Any]:
    bid = clean(getattr(ticker, "bid", None))
    ask = clean(getattr(ticker, "ask", None))
    last = clean(getattr(ticker, "last", None))
    close = clean(getattr(ticker, "close", None))
    market_price = clean(ticker.marketPrice())

    ordered_bidask = bid is not None and ask is not None and ask >= bid
    if ordered_bidask:
        mid = safe_round((bid + ask) / 2, 4)
        spread = safe_round(ask - bid, 4)
    else:
        mid = market_price or last or close
        spread = None

    spread_pct = calculate_spread_pct(bid, ask, mid)
    has_delta = greeks.get("delta") is not None
    has_iv = greeks.get("iv") is not None
    has_bidask = ordered_bidask and bid > 0 and ask > 0
    has_price = mid is not None and mid > 0

    if has_price and has_bidask and has_delta and has_iv:
        quality = "FULL_WITH_GREEKS"
    elif has_price and has_delta and has_iv:
        quality = "PRICE_WITH_GREEKS_NO_BIDASK"
    elif has_price:
        quality = "PRICE_ONLY_OR_PARTIAL"
    else:
        quality = "NO_VALID_OPTION_PRICE"

    return {
        "bid": bid,
        "ask": ask,
        "last": last,
        "close": close,
        "market_price": market_price,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
        "greeks": greeks,
        "data_quality": quality,
    }


def quote_score(quote: dict[str, Any]) -> tuple[int, int, int]:
    greeks = quote.get("greeks") or {}
    fields = [
        quote.get("bid"),
        quote.get("ask"),
        quote.get("mid"),
        quote.get("spread"),
        quote.get("spread_pct"),
        greeks.get("delta"),
    ]
    complete = sum(1 for value in fields if value not in [None, "", "None"])
    quality_rank = {
        "FULL_WITH_GREEKS": 4,
        "PRICE_WITH_GREEKS_NO_BIDASK": 3,
        "PRICE_ONLY_OR_PARTIAL": 1,
        "NO_VALID_OPTION_PRICE": 0,
        "ERROR": -1,
    }.get(str(quote.get("data_quality") or ""), 0)
    has_bidask = 1 if quote.get("bid") is not None and quote.get("ask") is not None else 0
    return complete, quality_rank, has_bidask


def parse_market_data_types(raw: str) -> list[int]:
    if not raw:
        return list(DEFAULT_MARKET_DATA_TYPES)
    out: list[int] = []
    for item in raw.split(","):
        try:
            value = int(item.strip())
        except Exception:
            continue
        if value not in out:
            out.append(value)
    return out or list(DEFAULT_MARKET_DATA_TYPES)


def parse_ibkr_expiration(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def days_to_expiration(value: str) -> int | None:
    expiration = parse_ibkr_expiration(value)
    if expiration is None:
        return None
    return max(0, int(round((expiration - datetime.now(timezone.utc)).total_seconds() / 86400)))


def choose_expiration(expirations: list[str], target_dte: int) -> str | None:
    dated = [
        (expiration, days_to_expiration(expiration))
        for expiration in expirations
    ]
    dated = [(expiration, dte) for expiration, dte in dated if dte is not None and dte > 0]
    if not dated:
        return None
    return min(dated, key=lambda item: abs(item[1] - target_dte))[0]


def choose_strike(strikes: list[float], underlying_price: float, right: str, otm_pct: float) -> float | None:
    if not strikes or underlying_price <= 0:
        return None
    target = (
        underlying_price * (1 - otm_pct)
        if right.upper() == "P"
        else underlying_price * (1 + otm_pct)
    )
    if right.upper() == "P":
        candidates = [strike for strike in strikes if 0 < strike < underlying_price]
    else:
        candidates = [strike for strike in strikes if strike > underlying_price]
    candidates = candidates or [strike for strike in strikes if strike > 0]
    return min(candidates, key=lambda strike: abs(strike - target)) if candidates else None


def get_underlying_price(ib: IB, ticker: str, exchange: str, currency: str, wait_seconds: float) -> tuple[Stock, float | None]:
    contract = Stock(ticker.upper(), exchange, currency)
    qualified = ib.qualifyContracts(contract)
    if qualified:
        contract = qualified[0]
    quote = ib.reqMktData(contract, "", False, False)
    ib.sleep(wait_seconds)
    price = (
        clean(quote.marketPrice())
        or clean(getattr(quote, "last", None))
        or clean(getattr(quote, "close", None))
    )
    try:
        ib.cancelMktData(contract)
    except Exception:
        pass
    return contract, price


def resolve_option_contract(ib: IB, args: argparse.Namespace) -> tuple[Option, dict[str, Any]]:
    if args.expiration and args.strike:
        contract = option_contract(args)
        return contract, {"mode": "manual"}

    underlying, underlying_price = get_underlying_price(
        ib,
        args.ticker,
        args.underlying_exchange,
        args.currency,
        args.underlying_wait,
    )
    if underlying_price is None:
        raise RuntimeError("Unable to resolve underlying price for automatic option selection.")

    chains = ib.reqSecDefOptParams(
        underlying.symbol,
        "",
        underlying.secType,
        underlying.conId,
    )
    if not chains:
        raise RuntimeError("IBKR returned no option chains for automatic option selection.")

    chain = next(
        (
            item
            for item in chains
            if str(getattr(item, "tradingClass", "")).upper() == args.ticker.upper()
            and str(getattr(item, "exchange", "")).upper() in [args.exchange.upper(), "SMART"]
        ),
        chains[0],
    )
    expiration = args.expiration or choose_expiration(list(chain.expirations), args.target_dte)
    if not expiration:
        raise RuntimeError("Unable to choose option expiration.")

    strike = float(args.strike) if args.strike else choose_strike(
        [float(strike) for strike in chain.strikes],
        underlying_price,
        args.right,
        args.otm_pct,
    )
    if strike is None:
        raise RuntimeError("Unable to choose option strike.")

    contract = Option(
        args.ticker.upper(),
        expiration,
        float(strike),
        args.right.upper(),
        getattr(chain, "exchange", None) or args.exchange,
        currency=args.currency,
        multiplier=str(getattr(chain, "multiplier", None) or args.multiplier),
        tradingClass=getattr(chain, "tradingClass", None) or args.ticker.upper(),
    )
    return contract, {
        "mode": "auto",
        "underlying_price": underlying_price,
        "target_dte": args.target_dte,
        "otm_pct": args.otm_pct,
        "chain_exchange": getattr(chain, "exchange", None),
        "trading_class": getattr(chain, "tradingClass", None),
    }


def option_contract(args: argparse.Namespace) -> Option:
    return Option(
        args.ticker.upper(),
        args.expiration,
        float(args.strike),
        args.right.upper(),
        args.exchange,
        currency=args.currency,
        multiplier=args.multiplier,
    )


def probe_once(
    ib: IB,
    contract: Option,
    market_data_type: int,
    snapshot: bool,
    wait_seconds: float,
) -> dict[str, Any]:
    source = f"{'SNAPSHOT' if snapshot else 'STREAM'}_TYPE_{market_data_type}"
    ticker = None
    try:
        ib.reqMarketDataType(market_data_type)
        ticker = ib.reqMktData(
            contract,
            genericTickList="" if snapshot else "100,101,106",
            snapshot=bool(snapshot),
            regulatorySnapshot=False,
        )
        ib.sleep(wait_seconds)
        greeks = greeks_from_ticker(ticker)
        quote = normalize_quote(ticker, greeks)
        quote["source"] = source
        quote["score"] = quote_score(quote)
        return quote
    except Exception as exc:
        return {"source": source, "data_quality": "ERROR", "error": str(exc), "score": (-1, -1, 0)}
    finally:
        if ticker is not None:
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only IBKR option quote probe.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--expiration", help="YYYYMMDD, e.g. 20260731. Optional in auto-select mode.")
    parser.add_argument("--strike", help="Optional in auto-select mode.")
    parser.add_argument("--right", choices=["P", "C", "p", "c"], default="P")
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--underlying-exchange", default="SMART")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--multiplier", default="100")
    parser.add_argument("--target-dte", type=int, default=45)
    parser.add_argument("--otm-pct", type=float, default=0.10)
    parser.add_argument("--underlying-wait", type=float, default=6)
    parser.add_argument("--market-data-types", default="1,2,3,4")
    parser.add_argument("--stream-wait", type=float, default=12)
    parser.add_argument("--snapshot-wait", type=float, default=4)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--json-out", default="", help="Optional local JSON path for sanitized probe evidence.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ib = IB()
    errors: list[dict[str, Any]] = []

    def on_error(req_id, code, message, contract):
        errors.append({"req_id": req_id, "code": code, "message": message})

    ib.errorEvent += on_error
    attempts: list[dict[str, Any]] = []
    selection: dict[str, Any] = {}

    try:
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=args.timeout)
        contract, selection = resolve_option_contract(ib, args)
        qualified = ib.qualifyContracts(contract)
        if qualified:
            contract = qualified[0]

        for market_data_type in parse_market_data_types(args.market_data_types):
            attempts.append(probe_once(ib, contract, market_data_type, False, args.stream_wait))
            attempts.append(probe_once(ib, contract, market_data_type, True, args.snapshot_wait))

        best = max(attempts, key=quote_score) if attempts else None
        result = {
            "engine": "IBKR_OPTION_QUOTE_PROBE",
            "generated_at": now_iso(),
            "readonly": True,
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
            "secrets_printed": False,
            "selection": selection,
            "contract": {
                "localSymbol": getattr(contract, "localSymbol", None),
                "conId": getattr(contract, "conId", None),
                "symbol": getattr(contract, "symbol", None),
                "expiration": getattr(contract, "lastTradeDateOrContractMonth", None),
                "strike": getattr(contract, "strike", None),
                "right": getattr(contract, "right", None),
                "exchange": getattr(contract, "exchange", None),
            },
            "best": best,
            "attempts": attempts,
            "errors": errors[-20:],
        }
        if args.json_out:
            output = Path(args.json_out).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if best and best.get("data_quality") != "ERROR" else 1
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
