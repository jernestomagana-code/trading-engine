"""Read-only IBKR collection helpers for premium-strategy research."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from typing import Any, Iterable

from ib_insync import IB, Option, Stock, WshEventData

import premium_strategy_data


COLLECTOR_VERSION = "ibkr_premium_research_collector_v1"
TARGET_DTES = (120, 150, 180)
TARGET_DELTAS = (0.10, 0.12, 0.14, 0.15, 0.20)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def days_to_expiration(expiration: str, today: date | None = None) -> int | None:
    try:
        value = datetime.strptime(str(expiration), "%Y%m%d").date()
        return (value - (today or datetime.now(timezone.utc).date())).days
    except ValueError:
        return None


def select_target_expirations(expirations: Iterable[str], today: date | None = None) -> dict[int, str]:
    dated = [(str(exp), days_to_expiration(str(exp), today)) for exp in expirations]
    dated = [(exp, dte) for exp, dte in dated if dte is not None and dte > 0]
    selected: dict[int, str] = {}
    used: set[str] = set()
    for target in TARGET_DTES:
        choices = [(exp, dte) for exp, dte in dated if exp not in used]
        if not choices:
            break
        expiration, _ = min(choices, key=lambda item: abs(item[1] - target))
        selected[target] = expiration
        used.add(expiration)
    return selected


def strike_probe_grid(strikes: Iterable[Any], underlying_price: float, limit: int = 16) -> list[float]:
    valid = sorted({_number(value) for value in strikes if _number(value) is not None and 0 < float(value) < underlying_price})
    targets = [0.62, 0.68, 0.73, 0.78, 0.82, 0.85, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98]
    selected: list[float] = []
    for ratio in targets:
        remaining = [value for value in valid if value not in selected]
        if not remaining:
            break
        selected.append(min(remaining, key=lambda strike: abs(strike - underlying_price * ratio)))
    return sorted(selected[-max(1, limit):])


def _greeks(ticker: Any) -> Any:
    return (
        getattr(ticker, "modelGreeks", None)
        or getattr(ticker, "bidGreeks", None)
        or getattr(ticker, "askGreeks", None)
        or getattr(ticker, "lastGreeks", None)
    )


def normalize_option_ticker(ticker: Any, target_dte: int, observed_at: str) -> dict[str, Any] | None:
    contract = getattr(ticker, "contract", None)
    greeks = _greeks(ticker)
    bid, ask = _number(getattr(ticker, "bid", None)), _number(getattr(ticker, "ask", None))
    iv, delta = _number(getattr(greeks, "impliedVol", None)), _number(getattr(greeks, "delta", None))
    underlying = _number(getattr(greeks, "undPrice", None))
    if not contract or None in (bid, ask, iv, delta, underlying) or bid <= 0 or ask < bid or underlying <= 0:
        return None
    expiration = str(getattr(contract, "lastTradeDateOrContractMonth", ""))[:8]
    mid = (bid + ask) / 2
    return {
        "ticker": str(getattr(contract, "symbol", "")).upper(),
        "observed_at": observed_at,
        "expiration": expiration,
        "dte": days_to_expiration(expiration),
        "target_dte": int(target_dte),
        "right": str(getattr(contract, "right", "P")).upper(),
        "strike": _number(getattr(contract, "strike", None)),
        "bid": bid,
        "ask": ask,
        "spread_pct": round((ask - bid) / mid * 100, 2) if mid > 0 else None,
        "delta": delta,
        "iv": iv,
        "underlying_price": underlying,
        "open_interest": _number(getattr(ticker, "putOpenInterest", None)),
        "volume": _number(getattr(ticker, "putVolume", None)),
        "source": "IBKR_TWS_READONLY",
    }


def choose_delta_contracts(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(rows)
    selected: list[dict[str, Any]] = []
    used: set[tuple[Any, Any, Any]] = set()
    for target in TARGET_DELTAS:
        available = [row for row in candidates if (row.get("expiration"), row.get("strike"), row.get("right")) not in used]
        if not available:
            break
        row = min(available, key=lambda item: abs(abs(float(item["delta"])) - target))
        row = {**row, "target_delta": target, "delta_distance": round(abs(abs(float(row["delta"])) - target), 4)}
        used.add((row.get("expiration"), row.get("strike"), row.get("right")))
        selected.append(row)
    return selected


def _best_chain(chains: Iterable[Any], ticker: str) -> Any | None:
    available = [chain for chain in chains if getattr(chain, "expirations", None) and getattr(chain, "strikes", None)]
    if not available:
        return None
    return min(available, key=lambda chain: (
        0 if str(getattr(chain, "tradingClass", "")).upper() == ticker else 1,
        0 if str(getattr(chain, "exchange", "")).upper() == "SMART" else 1,
        -len(getattr(chain, "strikes", []) or []),
    ))


def contracts_for_expiration(ib: IB, symbol: str, expiration: str, chain: Any, underlying: float, prefer_exact: bool = False) -> tuple[list[Any], str]:
    """Resolve the actual contracts listed for one expiry, avoiding theoretical chain strikes."""
    template = Option(
        symbol, expiration, 0, "P", "SMART", currency="USD",
        multiplier=str(getattr(chain, "multiplier", None) or "100"),
        tradingClass=getattr(chain, "tradingClass", None) or symbol,
    )
    if prefer_exact:
        try:
            details = ib.reqContractDetails(template)
            contracts = [detail.contract for detail in details if _number(getattr(detail.contract, "strike", None)) and float(detail.contract.strike) < underlying]
            if contracts:
                probe_strikes = set(strike_probe_grid((contract.strike for contract in contracts), underlying, limit=20))
                return [contract for contract in contracts if float(contract.strike) in probe_strikes], "EXACT_CONTRACT_DETAILS"
        except TimeoutError:
            pass
    fallback = [
        Option(symbol, expiration, strike, "P", "SMART", currency="USD", multiplier=str(getattr(chain, "multiplier", None) or "100"), tradingClass=getattr(chain, "tradingClass", None) or symbol)
        for strike in strike_probe_grid(chain.strikes, underlying, limit=16)
    ]
    return list(ib.qualifyContracts(*fallback)), "QUALIFIED_CHAIN_FALLBACK"


def collect_long_dated_puts(ib: IB, tickers: Iterable[str], wait_seconds: float = 8.0) -> dict[str, Any]:
    observed_at = premium_strategy_data.now_iso()
    records: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    for raw_ticker in tickers:
        symbol = str(raw_ticker).upper()
        try:
            stock = Stock(symbol, "SMART", "USD")
            qualified = ib.qualifyContracts(stock)
            stock = qualified[0] if qualified else stock
            quote = ib.reqMktData(stock, "", False, False)
            ib.sleep(max(1.0, min(wait_seconds, 4.0)))
            underlying = _number(quote.marketPrice()) or _number(getattr(quote, "last", None)) or _number(getattr(quote, "close", None))
            ib.cancelMktData(stock)
            if underlying is None:
                raise RuntimeError("UNDERLYING_PRICE_UNAVAILABLE")
            chain = _best_chain(ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId), symbol)
            if chain is None:
                raise RuntimeError("OPTION_CHAIN_UNAVAILABLE")
            expirations = select_target_expirations(chain.expirations)
            symbol_rows = []
            resolution_modes = {}
            for target_dte, expiration in expirations.items():
                contracts, resolution_mode = contracts_for_expiration(ib, symbol, expiration, chain, underlying, prefer_exact=False)
                resolution_modes[str(target_dte)] = resolution_mode
                streams = [ib.reqMktData(contract, "100,101,106", False, False) for contract in contracts]
                ib.sleep(wait_seconds)
                normalized = [normalize_option_ticker(stream, target_dte, observed_at) for stream in streams]
                for stream in streams:
                    try:
                        ib.cancelMktData(stream.contract)
                    except Exception:
                        pass
                chosen = choose_delta_contracts(row for row in normalized if row)
                records.extend(chosen)
                symbol_rows.extend(chosen)
            diagnostics[symbol] = {
                "status": "COLLECTED" if symbol_rows else "NO_COMPLETE_QUOTES",
                "target_expirations": expirations,
                "contract_resolution_modes": resolution_modes,
                "selected_rows": len(symbol_rows),
            }
        except Exception as exc:
            diagnostics[symbol] = {"status": "ERROR", "error": exc.__class__.__name__, "detail": str(exc)[:300]}
    return {"records": records, "diagnostics": diagnostics, "observed_at": observed_at}


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def normalize_wsh_events(raw: str, ticker: str, observed_at: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    events = []
    for item in _walk_dicts(payload):
        event_type = str(item.get("event_type") or item.get("eventType") or item.get("eventCode") or item.get("type") or "").lower()
        if "earn" not in event_type and "wsh_ed" not in event_type:
            continue
        raw_date = item.get("date") or item.get("eventDate") or item.get("event_date") or item.get("startDate")
        digits = "".join(character for character in str(raw_date or "") if character.isdigit())[:8]
        if len(digits) != 8:
            continue
        event_time = str(item.get("time") or item.get("eventTime") or item.get("event_timing") or "UNKNOWN").upper()
        timing = "BMO" if any(marker in event_time for marker in ("BMO", "BEFORE")) else "AMC" if any(marker in event_time for marker in ("AMC", "AFTER")) else "DURING_MARKET" if "DURING" in event_time else "UNKNOWN"
        events.append({
            "ticker": ticker.upper(),
            "earnings_date": f"{digits[:4]}-{digits[4:6]}-{digits[6:]}",
            "event_timing": timing,
            "confirmed": True,
            "source": "IBKR_WSH",
            "observed_at": observed_at,
        })
    return list({(row["ticker"], row["earnings_date"], row["event_timing"]): row for row in events}.values())


def collect_earnings_calendar(ib: IB, tickers: Iterable[str], start_date: str, end_date: str) -> dict[str, Any]:
    observed_at = premium_strategy_data.now_iso()
    diagnostics: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    try:
        metadata = ib.getWshMetaData()
        metadata_available = bool(metadata)
    except Exception as exc:
        return {"events": [], "diagnostics": {}, "metadata_available": False, "blocker": "WSH_SUBSCRIPTION_OR_METADATA_UNAVAILABLE", "detail": str(exc)[:300]}
    if not metadata_available:
        return {"events": [], "diagnostics": {}, "metadata_available": False, "blocker": "WSH_SUBSCRIPTION_OR_METADATA_UNAVAILABLE", "detail": "IBKR did not return WSH metadata; earnings queries were not attempted."}
    for raw_ticker in tickers:
        symbol = str(raw_ticker).upper()
        try:
            contracts = ib.qualifyContracts(Stock(symbol, "SMART", "USD"))
            if not contracts or not contracts[0].conId:
                raise RuntimeError("CONTRACT_ID_UNAVAILABLE")
            raw = ib.getWshEventData(WshEventData(conId=contracts[0].conId, startDate=start_date, endDate=end_date, totalLimit=10))
            rows = normalize_wsh_events(raw, symbol, observed_at)
            events.extend(rows)
            diagnostics[symbol] = {"status": "EVENTS_FOUND" if rows else "NO_EARNINGS_IN_WINDOW", "event_count": len(rows)}
        except Exception as exc:
            diagnostics[symbol] = {"status": "ERROR", "error": exc.__class__.__name__, "detail": str(exc)[:300]}
    return {"events": events, "diagnostics": diagnostics, "metadata_available": metadata_available, "observed_at": observed_at}
