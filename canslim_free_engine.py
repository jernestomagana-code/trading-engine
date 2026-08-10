"""Free CANSLIM-style candidate builder for Stock Ultimus.

The engine uses free SEC companyfacts data for reported fundamentals and local
runtime/IBKR bars for relative-strength context when available. It does not use
paid APIs and never authorizes orders.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import runtime_local_technical


ENGINE = "CANSLIM_FREE_ENGINE"
ENGINE_VERSION = "canslim_free_engine_v1"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_OUTPUT = Path("runtime/canslim_candidates_latest.json")
DEFAULT_SEC_CACHE = Path("runtime/sec_companyfacts_cache")
DEFAULT_ERROR_STATE = Path("runtime/canslim_network_error_state.json")
RECURRENT_ERROR_THRESHOLD = 3
DEFAULT_UNIVERSE = [
    "QQQ", "SPY", "AAPL", "NVDA", "TSLA",
    "NFLX", "META", "AMZN", "MSFT", "GOOGL",
    "AVGO", "AMD", "COST", "CRM", "ORCL", "TLT",
    "ADBE", "NOW", "PANW", "CRWD", "SNOW", "DDOG",
    "NET", "MDB", "SHOP", "UBER", "ABNB", "COIN",
    "HOOD", "PLTR", "APP", "TTD", "ROKU", "ZS",
    "TEAM", "WDAY", "INTU", "ISRG", "LRCX", "KLAC",
    "ASML", "ARM", "MU", "SMCI", "DELL", "VRT",
    "ANET", "MRVL", "MELI", "ELF", "CELH", "DECK",
    "LULU", "AXON", "HUBS", "DASH", "RBLX",
]
NON_COMPANY_SYMBOLS = {"QQQ", "SPY", "TLT", "VIX", "DIA", "IWM"}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,4}$")

REVENUE_TAGS = [
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
]
NET_INCOME_TAGS = ["NetIncomeLoss"]
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
SHARES_TAGS = ["EntityCommonStockSharesOutstanding"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def safe_float(value: Any) -> float | None:
    try:
        if value in [None, "", "None"]:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def pct_growth(current: Any, prior: Any) -> float | None:
    current_value = safe_float(current)
    prior_value = safe_float(prior)
    if current_value is None or prior_value in [None, 0]:
        return None
    return round(((current_value - prior_value) / abs(prior_value)) * 100.0, 2)


def growth_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value >= 50:
        return 100.0
    if value >= 25:
        return round(80 + ((value - 25) / 25) * 20, 2)
    if value >= 10:
        return round(50 + ((value - 10) / 15) * 30, 2)
    return round(20 + (value / 10) * 30, 2)


def average(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 2)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def cik10(value: Any) -> str:
    try:
        return str(int(value)).zfill(10)
    except Exception:
        return str(value or "").strip().zfill(10)


def parse_universe(raw: str | None = None) -> list[str]:
    values = list(DEFAULT_UNIVERSE) if not raw else [upper(item) for item in raw.split(",") if upper(item)]
    seen = set()
    out = []
    for value in values:
        if not TICKER_RE.match(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out or list(DEFAULT_UNIVERSE)


def load_runtime_jsons(runtime_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not runtime_dir.exists():
        return out
    for path in sorted(runtime_dir.glob("*.json")):
        try:
            out[path.name] = json.loads(path.read_text())
        except Exception:
            continue
    return out


def load_error_state(path: Path = DEFAULT_ERROR_STATE) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "tickers": {}}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"version": 1, "tickers": {}}
    if not isinstance(data, dict):
        return {"version": 1, "tickers": {}}
    tickers = data.get("tickers")
    if not isinstance(tickers, dict):
        data["tickers"] = {}
    data.setdefault("version", 1)
    return data


def write_error_state(state: dict[str, Any], path: Path = DEFAULT_ERROR_STATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n")
    return path


def _error_kind(error: str | None) -> str:
    text = upper(error)
    if not text:
        return "NONE"
    if text == "NON_COMPANY_SYMBOL_SKIPPED":
        return "SKIPPED"
    if text == "NO_SEC_CIK":
        return "DATA_MAPPING"
    if text.startswith("STALE_CACHE_USED_AFTER_REFRESH_ERROR"):
        return "CACHE_FALLBACK"
    network_markers = [
        "URLOPEN ERROR",
        "TIMEOUT",
        "TIMED OUT",
        "TEMPORARY FAILURE",
        "NODE NAME",
        "NODENAME",
        "NETWORK",
        "NAME OR SERVICE",
        "HTTP ERROR",
        "SSL",
        "CONNECTION",
    ]
    if any(marker in text for marker in network_markers):
        return "NETWORK"
    return "OTHER"


def update_error_state(
    *,
    universe: list[str],
    successful_tickers: set[str],
    errors: dict[str, str],
    path: Path = DEFAULT_ERROR_STATE,
    generated_at: str | None = None,
    recurrent_threshold: int = RECURRENT_ERROR_THRESHOLD,
) -> dict[str, Any]:
    generated_at = generated_at or now_iso()
    state = load_error_state(path)
    tickers = state.setdefault("tickers", {})

    for raw_ticker in universe:
        ticker = upper(raw_ticker)
        if not ticker:
            continue
        entry = tickers.get(ticker) if isinstance(tickers.get(ticker), dict) else {}
        error = errors.get(ticker)
        kind = _error_kind(error)

        if ticker in successful_tickers and kind != "CACHE_FALLBACK":
            entry.update({
                "status": "OK",
                "consecutive_failures": 0,
                "last_success_at": generated_at,
                "last_error": None,
                "last_error_kind": None,
            })
        elif kind == "CACHE_FALLBACK":
            entry.update({
                "status": "CACHE_FALLBACK_USED",
                "consecutive_failures": 0,
                "last_success_at": generated_at,
                "last_warning": error,
                "last_warning_at": generated_at,
                "last_error": None,
                "last_error_kind": None,
            })
        elif kind == "SKIPPED":
            entry.update({
                "status": "SKIPPED_NON_COMPANY_SYMBOL",
                "consecutive_failures": 0,
                "last_error": error,
                "last_error_kind": kind,
                "last_failed_at": generated_at,
            })
        elif error:
            consecutive = int(safe_float(entry.get("consecutive_failures")) or 0) + 1
            entry.update({
                "status": "RECURRENT_ERROR" if consecutive >= recurrent_threshold else "TRANSIENT_ERROR",
                "consecutive_failures": consecutive,
                "last_error": error,
                "last_error_kind": kind,
                "last_failed_at": generated_at,
            })
        tickers[ticker] = entry

    state["updated_at"] = generated_at
    state["recurrent_threshold"] = recurrent_threshold
    write_error_state(state, path)
    return state


def summarize_network_health(
    *,
    universe: list[str],
    errors: dict[str, str],
    error_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tickers = (error_state or {}).get("tickers") if isinstance(error_state, dict) else {}
    tickers = tickers if isinstance(tickers, dict) else {}
    recurrent = []
    transient = []
    cache_fallback = []
    skipped = []
    data_mapping = []
    other = []

    for raw_ticker in universe:
        ticker = upper(raw_ticker)
        entry = tickers.get(ticker) if isinstance(tickers.get(ticker), dict) else {}
        status = upper(entry.get("status"))
        kind = _error_kind(errors.get(ticker) or entry.get("last_error"))
        if status == "RECURRENT_ERROR":
            recurrent.append(ticker)
        elif status == "TRANSIENT_ERROR":
            transient.append(ticker)
        elif status == "CACHE_FALLBACK_USED":
            cache_fallback.append(ticker)
        elif kind == "SKIPPED":
            skipped.append(ticker)
        elif kind == "DATA_MAPPING":
            data_mapping.append(ticker)
        elif errors.get(ticker):
            other.append(ticker)

    if recurrent:
        status = "ACTION_REQUIRED"
        action = "Review network/DNS/SEC availability and pre-warm SEC cache for recurrent CANSLIM tickers."
    elif transient or cache_fallback:
        status = "DEGRADED"
        action = "Monitor next run; CANSLIM stayed operational for cached tickers."
    else:
        status = "OK"
        action = "No CANSLIM network action required."

    return {
        "status": status,
        "recurrent_error_count": len(recurrent),
        "transient_error_count": len(transient),
        "cache_fallback_count": len(cache_fallback),
        "skipped_non_company_symbol_count": len(skipped),
        "data_mapping_error_count": len(data_mapping),
        "other_error_count": len(other),
        "recurrent_tickers": recurrent,
        "transient_tickers": transient,
        "cache_fallback_tickers": cache_fallback,
        "skipped_non_company_symbols": skipped,
        "data_mapping_tickers": data_mapping,
        "other_error_tickers": other,
        "next_required_action": action,
        "not_order_instruction": True,
    }


def sec_user_agent(value: str | None = None) -> str:
    if value:
        return value
    env_value = os.getenv("STOCK_ULTIMUS_SEC_USER_AGENT")
    if env_value:
        return env_value
    try:
        email = subprocess.check_output(
            ["git", "config", "--get", "user.email"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        email = ""
    if "@" in email:
        return f"StockUltimus/1.0 {email}"
    return "StockUltimus/1.0 set-STOCK_ULTIMUS_SEC_USER_AGENT"


def fetch_json(url: str, *, user_agent: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_sec_ticker_map(cache_dir: Path, *, user_agent: str, refresh: bool = False) -> dict[str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "company_tickers.json"
    if cache_path.exists() and not refresh:
        data = json.loads(cache_path.read_text())
    else:
        data = fetch_json(SEC_TICKER_MAP_URL, user_agent=user_agent)
        cache_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    mapping: dict[str, str] = {}
    rows = data.values() if isinstance(data, dict) else data
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = upper(row.get("ticker"))
        cik = row.get("cik_str") or row.get("cik")
        if ticker and cik is not None:
            mapping[ticker] = cik10(cik)
    return mapping


def load_companyfacts(
    ticker: str,
    cik: str,
    cache_dir: Path,
    *,
    user_agent: str,
    refresh: bool = False,
    timeout: int = 20,
) -> tuple[dict[str, Any] | None, str | None]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    ticker = upper(ticker)
    cache_path = cache_dir / f"{ticker}_{cik}.json"
    if cache_path.exists() and not refresh:
        try:
            return json.loads(cache_path.read_text()), None
        except Exception as exc:
            return None, str(exc)
    try:
        data = fetch_json(SEC_COMPANYFACTS_URL.format(cik=cik), user_agent=user_agent, timeout=timeout)
        cache_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return data, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if cache_path.exists():
            try:
                return (
                    json.loads(cache_path.read_text()),
                    f"STALE_CACHE_USED_AFTER_REFRESH_ERROR: {exc}",
                )
            except Exception:
                pass
        return None, str(exc)


def fact_rows(companyfacts: dict[str, Any], tags: list[str], units: list[str]) -> list[dict[str, Any]]:
    facts = companyfacts.get("facts") if isinstance(companyfacts, dict) else {}
    us_gaap = facts.get("us-gaap") if isinstance(facts, dict) else {}
    dei = facts.get("dei") if isinstance(facts, dict) else {}
    rows: list[dict[str, Any]] = []
    for tag in tags:
        item = None
        if isinstance(us_gaap, dict):
            item = us_gaap.get(tag)
        if item is None and isinstance(dei, dict):
            item = dei.get(tag)
        if not isinstance(item, dict):
            continue
        unit_map = item.get("units") if isinstance(item.get("units"), dict) else {}
        for unit in units:
            for row in unit_map.get(unit, []) or []:
                if not isinstance(row, dict):
                    continue
                value = safe_float(row.get("val"))
                if value is None:
                    continue
                rows.append({**row, "tag": tag, "unit": unit, "val": value})
    return rows


def row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    fy = int(safe_float(row.get("fy")) or 0)
    filed = str(row.get("filed") or "")
    end = str(row.get("end") or "")
    return fy, filed, end


def latest_annual(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates = [
        row for row in rows
        if upper(row.get("fp")) == "FY" and upper(row.get("form")) in {"10-K", "20-F", "40-F"}
    ]
    candidates = sorted(candidates, key=row_sort_key, reverse=True)
    if not candidates:
        return None, None
    latest = candidates[0]
    latest_fy = int(safe_float(latest.get("fy")) or 0)
    prior = next((row for row in candidates[1:] if int(safe_float(row.get("fy")) or 0) < latest_fy), None)
    return latest, prior


def latest_quarter_pair(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates = [
        row for row in rows
        if upper(row.get("fp")) in {"Q1", "Q2", "Q3", "Q4"} and upper(row.get("form")) in {"10-Q", "10-K"}
    ]
    candidates = sorted(candidates, key=row_sort_key, reverse=True)
    if not candidates:
        return None, None
    latest = candidates[0]
    latest_fp = upper(latest.get("fp"))
    latest_fy = int(safe_float(latest.get("fy")) or 0)
    prior = next(
        (
            row for row in candidates[1:]
            if upper(row.get("fp")) == latest_fp and int(safe_float(row.get("fy")) or 0) == latest_fy - 1
        ),
        None,
    )
    if prior is None and len(candidates) > 4:
        prior = candidates[4]
    return latest, prior


def metric_growths(companyfacts: dict[str, Any]) -> dict[str, Any]:
    revenue_rows = fact_rows(companyfacts, REVENUE_TAGS, ["USD"])
    income_rows = fact_rows(companyfacts, NET_INCOME_TAGS, ["USD"])
    eps_rows = fact_rows(companyfacts, EPS_TAGS, ["USD/shares", "USD/shares"])
    shares_rows = fact_rows(companyfacts, SHARES_TAGS, ["shares"])

    q_rev, q_rev_prior = latest_quarter_pair(revenue_rows)
    q_income, q_income_prior = latest_quarter_pair(income_rows)
    q_eps, q_eps_prior = latest_quarter_pair(eps_rows)
    a_rev, a_rev_prior = latest_annual(revenue_rows)
    a_income, a_income_prior = latest_annual(income_rows)
    a_eps, a_eps_prior = latest_annual(eps_rows)

    latest_shares = sorted(shares_rows, key=row_sort_key, reverse=True)[:1]

    return {
        "quarterly_revenue_growth": pct_growth((q_rev or {}).get("val"), (q_rev_prior or {}).get("val")),
        "quarterly_net_income_growth": pct_growth((q_income or {}).get("val"), (q_income_prior or {}).get("val")),
        "quarterly_eps_growth": pct_growth((q_eps or {}).get("val"), (q_eps_prior or {}).get("val")),
        "annual_revenue_growth": pct_growth((a_rev or {}).get("val"), (a_rev_prior or {}).get("val")),
        "annual_net_income_growth": pct_growth((a_income or {}).get("val"), (a_income_prior or {}).get("val")),
        "annual_eps_growth": pct_growth((a_eps or {}).get("val"), (a_eps_prior or {}).get("val")),
        "shares_outstanding": (latest_shares[0].get("val") if latest_shares else None),
        "latest_quarter": {
            "fy": (q_rev or q_income or q_eps or {}).get("fy"),
            "fp": (q_rev or q_income or q_eps or {}).get("fp"),
            "filed": (q_rev or q_income or q_eps or {}).get("filed"),
        },
        "latest_annual": {
            "fy": (a_rev or a_income or a_eps or {}).get("fy"),
            "filed": (a_rev or a_income or a_eps or {}).get("filed"),
        },
    }


def close_values(bars: list[dict[str, Any]]) -> list[float]:
    values = []
    for row in bars or []:
        value = safe_float(row.get("close") or row.get("c") or row.get("last") or row.get("price"))
        if value is not None and value > 0:
            values.append(value)
    return values


def trailing_return(bars: list[dict[str, Any]], lookback: int = 126) -> float | None:
    closes = close_values(bars)
    if len(closes) < 20:
        return None
    window = closes[-lookback:] if len(closes) >= lookback else closes
    if not window or window[0] == 0:
        return None
    return (window[-1] / window[0]) - 1.0


def relative_strength_score(ticker: str, bars_by_ticker: dict[str, list[dict[str, Any]]]) -> tuple[float | None, dict[str, Any]]:
    ticker_return = trailing_return(bars_by_ticker.get(ticker, []))
    benchmark_returns = [
        value for value in [
            trailing_return(bars_by_ticker.get("SPY", [])),
            trailing_return(bars_by_ticker.get("QQQ", [])),
        ]
        if value is not None
    ]
    if ticker_return is None or not benchmark_returns:
        return None, {"ticker_return": ticker_return, "benchmark_return": None}
    benchmark_return = sum(benchmark_returns) / len(benchmark_returns)
    score = clamp(50 + ((ticker_return - benchmark_return) * 100))
    return round(score, 2), {
        "ticker_return": round(ticker_return * 100, 2),
        "benchmark_return": round(benchmark_return * 100, 2),
        "relative_return": round((ticker_return - benchmark_return) * 100, 2),
    }


def market_score(bars_by_ticker: dict[str, list[dict[str, Any]]]) -> float | None:
    scores = []
    for symbol in ["SPY", "QQQ"]:
        ret = trailing_return(bars_by_ticker.get(symbol, []), lookback=63)
        if ret is not None:
            scores.append(clamp(50 + ret * 200))
    return average(scores)


def rating_for_score(score: float | None, passes: bool) -> str:
    if score is None:
        return "NO_DATA"
    if passes and score >= 85:
        return "LEADER"
    if passes:
        return "PASS"
    if score >= 55:
        return "WATCH"
    return "FAIL"


def score_companyfacts(
    ticker: str,
    companyfacts: dict[str, Any],
    *,
    bars_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
    minimum_score: float = 70.0,
) -> dict[str, Any]:
    ticker = upper(ticker)
    bars_by_ticker = bars_by_ticker or {}
    metrics = metric_growths(companyfacts)
    c_score = average([
        growth_score(metrics.get("quarterly_eps_growth")),
        growth_score(metrics.get("quarterly_revenue_growth")),
        growth_score(metrics.get("quarterly_net_income_growth")),
    ])
    a_score = average([
        growth_score(metrics.get("annual_eps_growth")),
        growth_score(metrics.get("annual_revenue_growth")),
        growth_score(metrics.get("annual_net_income_growth")),
    ])
    l_score, relative_strength = relative_strength_score(ticker, bars_by_ticker)
    m_score = market_score(bars_by_ticker)

    weighted = [
        (c_score, 0.35),
        (a_score, 0.30),
        (l_score, 0.20),
        (m_score, 0.15),
    ]
    available_weight = sum(weight for value, weight in weighted if value is not None)
    available_components = [name for name, value in {
        "C": c_score, "A": a_score, "L": l_score, "M": m_score,
    }.items() if value is not None]
    missing_components = [name for name in ["C", "A", "L", "M"] if name not in available_components]
    total = None
    if available_weight > 0:
        total = round(sum((value or 0) * weight for value, weight in weighted if value is not None) / available_weight, 2)

    has_growth_evidence = c_score is not None or a_score is not None
    passes = bool(total is not None and total >= minimum_score and has_growth_evidence)
    rating = rating_for_score(total, passes)

    return {
        "ticker": ticker,
        "canslim_score": total,
        "canslim_passes": passes,
        "canslim_rating": rating,
        "canslim_component_coverage_pct": round(len(available_components) / 4 * 100.0, 1),
        "canslim_available_components": available_components,
        "canslim_missing_components": missing_components,
        "canslim_scope": "FULL_C_A_L_M" if not missing_components else "PARTIAL_AVAILABLE_COMPONENTS",
        "rating": rating,
        "canslim": {
            "available": True,
            "passes": passes,
            "score": total,
            "rating": rating,
            "source": ENGINE,
            "components": {
                "C_quarterly_growth": c_score,
                "A_annual_growth": a_score,
                "L_relative_strength": l_score,
                "M_market": m_score,
            },
            "minimum_score": minimum_score,
            "component_coverage_pct": round(len(available_components) / 4 * 100.0, 1),
            "available_components": available_components,
            "missing_components": missing_components,
            "scope": "FULL_C_A_L_M" if not missing_components else "PARTIAL_AVAILABLE_COMPONENTS",
        },
        "fundamental": {
            "eps_growth": metrics.get("quarterly_eps_growth"),
            "sales_growth": metrics.get("quarterly_revenue_growth"),
            "annual_eps_growth": metrics.get("annual_eps_growth"),
            "annual_sales_growth": metrics.get("annual_revenue_growth"),
            "shares_outstanding": metrics.get("shares_outstanding"),
        },
        "metrics": {
            **metrics,
            "relative_strength": relative_strength,
        },
        "source": ENGINE,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_payload(
    *,
    universe: list[str],
    companyfacts_by_ticker: dict[str, dict[str, Any]],
    runtime_data: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    error_state: dict[str, Any] | None = None,
    minimum_score: float = 70.0,
) -> dict[str, Any]:
    bars_by_ticker = runtime_local_technical.extract_local_bar_sets(runtime_data or {})
    rows = []
    for ticker in universe:
        facts = companyfacts_by_ticker.get(upper(ticker))
        if not isinstance(facts, dict):
            continue
        rows.append(score_companyfacts(ticker, facts, bars_by_ticker=bars_by_ticker, minimum_score=minimum_score))

    rows = sorted(
        rows,
        key=lambda row: (
            1 if row.get("canslim_passes") else 0,
            row.get("canslim_score") if row.get("canslim_score") is not None else -1,
            row.get("ticker") or "",
        ),
        reverse=True,
    )
    network_health = summarize_network_health(
        universe=universe,
        errors=errors or {},
        error_state=error_state,
    )
    return {
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
        "generated_at": now_iso(),
        "free_data_only": True,
        "sources": ["SEC_COMPANYFACTS", "IBKR_RUNTIME_BARS"],
        "universe": universe,
        "candidate_count": len(rows),
        "pass_count": sum(1 for row in rows if row.get("canslim_passes")),
        "candidates": rows,
        "by_ticker": {row["ticker"]: row for row in rows},
        "errors": errors or {},
        "network_health": network_health,
        "error_state_version": (error_state or {}).get("version"),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def write_payload(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return path
