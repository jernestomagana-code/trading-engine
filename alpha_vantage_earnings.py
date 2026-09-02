"""Free Alpha Vantage earnings-calendar adapter for research data."""

from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable


PROVIDER = "ALPHA_VANTAGE"
ENDPOINT = "https://www.alphavantage.co/query"


def normalize_timing(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"before market open", "bmo", "pre-market", "premarket"}:
        return "BMO"
    if text in {"after market close", "amc", "post-market", "postmarket"}:
        return "AMC"
    if text in {"during market", "during-market"}:
        return "DURING_MARKET"
    return "UNKNOWN"


def parse_calendar_csv(raw: str, tickers: Iterable[str], observed_at: str) -> list[dict[str, Any]]:
    wanted = {str(ticker).upper() for ticker in tickers if ticker}
    rows: list[dict[str, Any]] = []
    for item in csv.DictReader(io.StringIO(raw)):
        ticker = str(item.get("symbol") or "").upper()
        report_date = str(item.get("reportDate") or "").strip()
        if ticker not in wanted or len(report_date) != 10:
            continue
        rows.append({
            "ticker": ticker,
            "earnings_date": report_date,
            "event_timing": normalize_timing(item.get("reportTime")),
            # Upcoming provider dates are scheduled/estimated until corroborated.
            "confirmed": False,
            "confidence": "ESTIMATED",
            "source": PROVIDER,
            "observed_at": observed_at,
            "fiscal_date_ending": item.get("fiscalDateEnding") or None,
            "estimate": item.get("estimate") or None,
        })
    return rows


def fetch_calendar(
    api_key: str,
    tickers: Iterable[str],
    horizon: str = "3month",
    timeout: float = 20,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc).isoformat()
    params = urllib.parse.urlencode({"function": "EARNINGS_CALENDAR", "horizon": horizon, "apikey": api_key})
    request = urllib.request.Request(f"{ENDPOINT}?{params}", headers={"User-Agent": "Stock-Ultimus/1.0"})
    with opener(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    if raw.lstrip().startswith("{"):
        raise RuntimeError("ALPHA_VANTAGE_LIMIT_OR_PROVIDER_ERROR")
    events = parse_calendar_csv(raw, tickers, observed_at)
    return {"provider": PROVIDER, "events": events, "observed_at": observed_at, "horizon": horizon}
