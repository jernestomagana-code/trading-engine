from ib_insync import *
import requests
import time
import math
import logging
from datetime import datetime, timezone
import nest_asyncio


# === V26 REMOTE MASTER SNAPSHOT PUBLISHER ===
import json as _v26_json
import urllib.request as _v26_urllib_request
import urllib.error as _v26_urllib_error
from datetime import datetime as _v26_datetime, timezone as _v26_timezone
from pathlib import Path as _v26_Path

# ============================================================
# V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================

from pathlib import Path as _v283_Path
from datetime import datetime as _v283_datetime, timezone as _v283_timezone
import os as _v283_os
import json as _v283_json

try:
    import requests as _v283_requests
except Exception:
    _v283_requests = None

_V283_REMOTE_BASE_URL = _v283_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V283_REMOTE_INGEST_PATH = _v283_os.environ.get(
    "TRADING_ENGINE_INGEST_PATH",
    "/v31_ingest_snapshot"
)
if not _V283_REMOTE_INGEST_PATH.startswith("/"):
    _V283_REMOTE_INGEST_PATH = "/" + _V283_REMOTE_INGEST_PATH

_V283_INGEST_URL = _V283_REMOTE_BASE_URL + _V283_REMOTE_INGEST_PATH

def _v283_now():
    return _v283_datetime.now(_v283_timezone.utc).isoformat()

def _v283_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v283_load_runtime_jsons():
    runtime = _v283_Path("runtime")
    out = {}
    if not runtime.exists():
        return out

    for p in runtime.glob("*.json"):
        try:
            out[p.name] = _v283_json.loads(p.read_text())
        except Exception:
            pass
    return out

def _v283_extract_options_rows(data):
    rows = []
    execution_fields = [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]

    def completeness_score(row):
        complete = sum(
            1
            for field in execution_fields
            if row.get(field) not in [None, "", "None"]
        )
        try:
            score = float(row.get("score") or 0)
        except Exception:
            score = 0.0
        return complete, score

    def scan(obj):
        if isinstance(obj, dict):
            # Detectar filas de opciones
            ticker = str(obj.get("ticker") or obj.get("symbol") or "").upper().strip()
            strategy = obj.get("strategy") or obj.get("strategy_hint") or obj.get("best_strategy")
            decision = obj.get("decision") or obj.get("final_decision") or obj.get("state")
            quality = obj.get("data_quality") or obj.get("quality")

            if ticker and (strategy or decision or quality or obj.get("can_operate") is not None):
                r = dict(obj)
                r["ticker"] = ticker
                r["strategy"] = str(strategy or "UNKNOWN").upper()
                r["decision"] = str(decision or "RADAR").upper()
                r["score"] = _v283_float(
                    r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"),
                    0
                )
                r["price"] = _v283_float(
                    r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"),
                    None
                )
                r["data_quality"] = quality or "UNKNOWN"
                if "can_operate" not in r:
                    r["can_operate"] = r["decision"] in ["ENTRY", "ENTRY_READY", "OPERAR"]
                rows.append(r)

            for key in [
                "options_rows",
                "rows",
                "top",
                "top_5",
                "sample_rows",
                "best_rows",
                "entry_candidates",
                "radar_candidates"
            ]:
                v = obj.get(key)
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict):
                            rows.append(dict(x))

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    scan(v)

        elif isinstance(obj, list):
            for x in obj:
                scan(x)

    for v in data.values():
        scan(v)

    best_by_key = {}

    for r in rows:
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper().strip()
        if not ticker:
            continue

        strategy = str(r.get("strategy") or r.get("strategy_hint") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or "RADAR").upper()

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = _v283_float(r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"), 0)
        r["price"] = _v283_float(r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"), None)
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")

        if "can_operate" not in r:
            r["can_operate"] = decision in ["ENTRY", "ENTRY_READY", "OPERAR"]

        key = (ticker, strategy, decision)

        current = best_by_key.get(key)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[key] = r

    return sorted(best_by_key.values(), key=completeness_score, reverse=True)

def _v283_extract_technical(data):
    tech = {}

    def scan(obj, parent_key=None):
        if isinstance(obj, dict):
            ticker = str(obj.get("ticker") or obj.get("symbol") or parent_key or "").upper().strip()

            looks_technical = any(k in obj for k in [
                "trend",
                "bias",
                "technical_bias",
                "rsi",
                "adx",
                "vwap_position",
                "volume_relative",
                "support_near",
                "resistance_near",
                "range_breakout",
                "event_risk",
                "technical_score",
                "score"
            ])

            if ticker and looks_technical:
                item = dict(obj)
                item["ticker"] = ticker
                item["trend"] = str(
                    item.get("trend") or item.get("bias") or item.get("technical_bias") or "UNKNOWN"
                ).upper()
                item["score"] = _v283_float(item.get("technical_score") or item.get("score"), None)
                tech[ticker] = item

            for k, v in obj.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(obj, list):
            for x in obj:
                scan(x, parent_key)

    for v in data.values():
        scan(v)

    return tech

def _v283_publish_to_v28():
    if _v283_requests is None:
        print("V28.3 OFFICIAL V28 PUBLISH SKIPPED | requests unavailable")
        return

    runtime_data = _v283_load_runtime_jsons()
    rows = _v283_extract_options_rows(runtime_data)
    tech = _v283_extract_technical(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26_V31_TARGET",
        "generated_at": _v283_now(),
        "options_rows": rows,
        "technical_snapshot": tech,
        "market": {
            "status": "REGULAR_OPTIONS_SESSION",
            "label": "Mercado abierto: opciones en ventana operable",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
            "source": "IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26_V31_TARGET",
            "generated_at": _v283_now()
        },
        "bridge_status": "LIVE_IBKR_AFTER_V26_PUBLISH",
        "runtime_files_seen": sorted(list(runtime_data.keys()))
    }

    try:
        resp = _v283_requests.post(_V283_INGEST_URL, json=payload, timeout=20)
        ok = 200 <= resp.status_code < 300
        print(
            "V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(rows)}"
            f" | technical:{len(tech)}"
            f" | url:{_V283_INGEST_URL}"
        )
    except Exception as e:
        print(f"V28.3 OFFICIAL V28 SNAPSHOT ERROR | {e}")

# ============================================================
# END V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================


_V26_RENDER_INGEST_URL = "https://trading-engine-p097.onrender.com/v25_ingest_snapshot"
_V26_RUNTIME_DIR = _v26_Path("runtime")
_V26_RUNTIME_DIR.mkdir(exist_ok=True)
_V26_LOCAL_MASTER_SNAPSHOT = _V26_RUNTIME_DIR / "v26_local_master_snapshot.json"
_V26_LAST_REMOTE_RESULT = _V26_RUNTIME_DIR / "v26_last_remote_publish_result.json"


def _v26_now_iso():
    return _v26_datetime.now(_v26_timezone.utc).isoformat()


def _v26_safe_jsonable(obj):
    try:
        _v26_json.dumps(obj, default=str)
        return obj
    except Exception:
        return str(obj)


def _v26_load_json_file(path):
    try:
        p = _v26_Path(path)
        if p.exists():
            return _v26_json.loads(p.read_text())
    except Exception as e:
        return {"_load_error": str(e), "_path": str(path)}
    return None


def _v26_discover_runtime_context():
    """
    Discover existing runtime files generated by previous versions without assuming
    exact structure. This keeps V26 compatible with V18/V19/V22/V25 work.
    """
    files = {}
    candidates = [
        "runtime/technical_snapshot_by_ticker_safe.json",
        "runtime/technical_snapshot_by_ticker.json",
        "runtime/decision_desk_snapshot.json",
        "runtime/decision_snapshot.json",
        "runtime/v18_decision_snapshot.json",
        "runtime/v18_decision_desk_snapshot.json",
        "runtime/v22_2_unified_remote_snapshot.json",
        "runtime/v25_master_snapshot.json",
    ]

    for path in candidates:
        data = _v26_load_json_file(path)
        if data is not None:
            files[path] = data

    return files


def _v26_extract_options_rows_from_context(ctx):
    """
    Try to recover options rows from known snapshot formats.
    """
    rows = []
    execution_fields = [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]

    def completeness_score(row):
        complete = sum(
            1
            for field in execution_fields
            if row.get(field) not in [None, "", "None"]
        )
        try:
            score = float(row.get("score") or 0)
        except Exception:
            score = 0.0
        return complete, score

    for _, data in ctx.items():
        if not isinstance(data, dict):
            continue

        for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
            val = data.get(key)
            if isinstance(val, list):
                rows.extend([x for x in val if isinstance(x, dict)])

        summary = data.get("summary")
        if isinstance(summary, dict):
            for key in ["rows", "top", "top_5", "sample_rows"]:
                val = summary.get(key)
                if isinstance(val, list):
                    rows.extend([x for x in val if isinstance(x, dict)])

    best_by_key = {}
    for r in rows:
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        strategy = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()
        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        sig = (ticker, strategy, decision)
        current = best_by_key.get(sig)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[sig] = r

    return sorted(best_by_key.values(), key=completeness_score, reverse=True)


def _v26_extract_technical_snapshot_from_context(ctx):
    for _, data in ctx.items():
        if not isinstance(data, dict):
            continue

        # Direct safe technical file
        if data and all(isinstance(v, dict) for v in data.values()):
            tickers = [k for k in data.keys() if isinstance(k, str) and len(k) <= 8]
            if tickers:
                return data

        technical = data.get("technical")
        if isinstance(technical, dict):
            return technical

        snapshot = data.get("technical_snapshot")
        if isinstance(snapshot, dict):
            return snapshot

    return {}


def _v26_build_master_snapshot(extra_payload=None):
    """
    Build one master payload for Render.
    extra_payload can be passed by ibkr_bridge runtime if available.
    """
    ctx = _v26_discover_runtime_context()
    options_rows = _v26_extract_options_rows_from_context(ctx)
    technical_snapshot = _v26_extract_technical_snapshot_from_context(ctx)

    tickers = set()

    for r in options_rows:
        t = r.get("ticker")
        if t:
            tickers.add(str(t).upper())

    for t in technical_snapshot.keys():
        if isinstance(t, str):
            tickers.add(t.upper())

    if isinstance(extra_payload, dict):
        for key in ["tickers", "symbols", "watchlist"]:
            val = extra_payload.get(key)
            if isinstance(val, list):
                for t in val:
                    tickers.add(str(t).upper())

    master = {
        "source": "IBKR_BRIDGE_V26_REMOTE_MASTER_PUBLISHER",
        "generated_at": _v26_now_iso(),
        "extra_payload": _v26_safe_jsonable(extra_payload or {}),
        "runtime_context_files": list(ctx.keys()),
        "options_rows": options_rows,
        "technical_snapshot": technical_snapshot,
        "tickers_detected": sorted(tickers),
        "diagnostics": {
            "options_rows_found": len(options_rows),
            "technical_available": bool(technical_snapshot),
            "technical_tickers": sorted([str(x).upper() for x in technical_snapshot.keys()]) if isinstance(technical_snapshot, dict) else [],
            "runtime_files_found": len(ctx),
        },
    }

    _V26_LOCAL_MASTER_SNAPSHOT.write_text(_v26_json.dumps(master, indent=2, default=str))
    return master


def _v26_publish_master_snapshot(extra_payload=None, timeout=6):
    """
    Publish master snapshot to Render. Never raises into main bridge loop.
    """
    result = {
        "engine": "V26_REMOTE_MASTER_SNAPSHOT_PUBLISHER",
        "generated_at": _v26_now_iso(),
        "target": _V26_RENDER_INGEST_URL,
        "status": "UNKNOWN",
    }

    try:
        master = _v26_build_master_snapshot(extra_payload=extra_payload)

        if (
            not master.get("options_rows")
            and not master.get("technical_snapshot")
            and not master.get("tickers_detected")
        ):
            result.update({
                "status": "SKIPPED_EMPTY",
                "reason": "No useful options/technical/ticker data found to publish.",
                "diagnostics": master.get("diagnostics", {}),
            })
            _V26_LAST_REMOTE_RESULT.write_text(_v26_json.dumps(result, indent=2, default=str))
            print("V26 publish skipped: empty master snapshot.")
            return result

        payload = _v26_json.dumps(master, default=str).encode("utf-8")
        req = _v26_urllib_request.Request(
            _V26_RENDER_INGEST_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with _v26_urllib_request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result.update({
                "status": "OK",
                "http_status": resp.status,
                "response_preview": body[:800],
                "diagnostics": master.get("diagnostics", {}),
            })

        print(
            "V26 remote publish OK | "
            f"rows={master['diagnostics']['options_rows_found']} | "
            f"technical={master['diagnostics']['technical_available']} | "
            f"tickers={master.get('tickers_detected')}"
        )

    except Exception as e:
        result.update({
            "status": "ERROR",
            "error": str(e),
        })
        print(f"V26 remote publish ERROR: {e}")

    try:
        _V26_LAST_REMOTE_RESULT.write_text(_v26_json.dumps(result, indent=2, default=str))
    except Exception:
        pass

    return result


def _v26_print_remote_publish_status(extra_payload=None):
    return _v26_publish_master_snapshot(extra_payload=extra_payload)
# === END V26 REMOTE MASTER SNAPSHOT PUBLISHER ===


nest_asyncio.apply()

# ============================================================
# SUPER ENGINE BOLSA — IBKR BRIDGE V18_1_REMOTE_SNAPSHOT_INGEST
# IBKR ONLY + READY FOR TRADINGVIEW INTEGRATION
# Market + Portfolio + Options + Strategy Commander
# FULL FILE VERSION
# ============================================================

IB_HOST = "127.0.0.1"
IB_PORT = 7496
CLIENT_ID = 10

ENGINE_URL = "https://trading-engine-p097.onrender.com/webhook/ibkr"

WATCHLIST = [
    "QQQ", "SPY", "AAPL", "NVDA", "TSLA",
    "NFLX", "META", "AMZN", "MSFT", "TLT"
]

OPTION_SYMBOLS = [
    "QQQ", "SPY", "NVDA", "TSLA", "NFLX", "META", "TLT"
]

LOOP_SECONDS = 180

TARGET_DTE_MIN = 25
TARGET_DTE_MAX = 65
TARGET_DTE_IDEAL = 45

MAX_OPTIONS_PER_SYMBOL = 8

# 1 = live, 2 = frozen, 3 = delayed, 4 = delayed frozen
MARKET_DATA_TYPE = 1

# ============================================================
# CONTROL FLAGS
# ============================================================

ENABLE_MARKET_DATA = True
ENABLE_PORTFOLIO_COMMANDER = True
ENABLE_OPTIONS_INTELLIGENCE = True

ENABLE_COVERED_CALLS = True
ENABLE_NAKED_PUTS = True

USE_STANDARD_OPTION_STRIKES = True
STANDARD_STRIKE_MULTIPLE = 5

SHOW_IBKR_CONTRACT_ERRORS = False

# Espera para que IBKR entregue bid/ask/greeks en opciones
OPTION_MARKET_DATA_WAIT_SECONDS = 8.0
OPTION_SECOND_PASS_WAIT_SECONDS = 5.0

# Espera para fallback de market data en acciones
STOCK_MARKET_DATA_WAIT_SECONDS = 2.0

# Mandamos opciones aunque estén incompletas, pero la decisión queda bloqueada.
SEND_OPTIONS_WITHOUT_GREEKS = True

# Control de liquidez / spread
MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR = 0.18
MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR = 0.35

# Prima mínima para considerar una opción razonable
MIN_OPTION_MID_FOR_RADAR = 0.10
MIN_OPTION_MID_FOR_OPERAR = 0.20

if not SHOW_IBKR_CONTRACT_ERRORS:
    logging.getLogger("ib_insync.wrapper").setLevel(logging.CRITICAL)

ib = IB()


# ============================================================
# PRIMARY EXCHANGE MAP
# ============================================================

PRIMARY_EXCHANGE_MAP = {
    "AAPL": "NASDAQ",
    "NVDA": "NASDAQ",
    "TSLA": "NASDAQ",
    "NFLX": "NASDAQ",
    "META": "NASDAQ",
    "AMZN": "NASDAQ",
    "MSFT": "NASDAQ",
    "QQQ": "NASDAQ",
    "SPY": "ARCA",
    "TLT": "NASDAQ"
}


# ============================================================
# UTILITIES
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(x, allow_negative=False):
    try:
        if x is None:
            return None

        x = float(x)

        if math.isnan(x) or math.isinf(x):
            return None

        if not allow_negative and x <= 0:
            return None

        return round(x, 4)

    except Exception:
        return None


def safe_round(x, digits=4):
    try:
        if x is None:
            return None

        x = float(x)

        if math.isnan(x) or math.isinf(x):
            return None

        return round(x, digits)

    except Exception:
        return None


def post(payload):
    try:
        response = requests.post(
            ENGINE_URL,
            json=payload,
            timeout=90
        )

        return response.status_code

    except Exception as e:
        print("POST ERROR:", e)
        return None


def set_market_data_type():
    try:
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print(f"Market data type configurado en: {MARKET_DATA_TYPE}")

    except Exception as e:
        print("No se pudo configurar market data type:", e)


def is_standard_strike(strike):
    try:
        if not USE_STANDARD_OPTION_STRIKES:
            return True

        strike = float(strike)

        if strike >= 100:
            return abs(strike % STANDARD_STRIKE_MULTIPLE) < 0.0001

        return abs(strike % 1) < 0.0001

    except Exception:
        return False


def tradingview_context_stub(symbol):
    """
    V15 mantiene el payload listo para integración TradingView.
    En una fase posterior, este bloque se alimentará desde el engine/dashboard:
    última señal técnica, tendencia, score, setup y timeframe.
    """
    return {
        "tradingview_signal_available": False,
        "tradingview_last_setup": None,
        "tradingview_last_trend": None,
        "tradingview_last_score": None,
        "tradingview_last_timeframe": None,
        "tradingview_last_signal_time": None
    }


# ============================================================
# CONTRACT HELPERS
# ============================================================

def stock_contract(symbol):
    """
    V15:
    1. Intenta contrato SMART + primaryExchange.
    2. Si falla, intenta SMART simple.
    3. Devuelve contrato calificado cuando IBKR lo permite.
    """
    primary_exchange = PRIMARY_EXCHANGE_MAP.get(symbol)

    attempts = []

    if primary_exchange:
        attempts.append(
            Stock(
                symbol=symbol,
                exchange="SMART",
                currency="USD",
                primaryExchange=primary_exchange
            )
        )

    attempts.append(
        Stock(
            symbol=symbol,
            exchange="SMART",
            currency="USD"
        )
    )

    for contract in attempts:
        try:
            qualified = ib.qualifyContracts(contract)

            if qualified:
                return qualified[0]

        except Exception:
            pass

    # Fallback final
    if primary_exchange:
        return Stock(
            symbol=symbol,
            exchange="SMART",
            currency="USD",
            primaryExchange=primary_exchange
        )

    return Stock(symbol, "SMART", "USD")






def ibkr_market_is_open_for_options():
    """
    V16.1 Market-Aware:
    Detecta si estamos en horario regular aproximado de mercado USA.
    Sirve para no castigar bid/ask faltante cuando el mercado está cerrado.
    """
    try:
        now = datetime.now(timezone.utc)
        # NY regular market: 9:30-16:00 ET.
        # Aproximación simple usando UTC:
        # Durante horario estándar: 14:30-21:00 UTC.
        # Durante horario de verano: 13:30-20:00 UTC.
        # Usamos ventana amplia para evitar falsos negativos.
        weekday = now.weekday() < 5
        minutes_utc = now.hour * 60 + now.minute
        open_wide = (13 * 60 + 25) <= minutes_utc <= (21 * 60 + 5)
        return weekday and open_wide
    except Exception:
        return False


def market_closed_bidask_note():
    return "MARKET_CLOSED_NO_BIDASK_EXPECTED"

def option_needs_second_pass(ticker):
    """
    V16 incremental:
    Detecta si una opción necesita más tiempo para que IBKR entregue griegas o bid/ask.
    No bloquea la estrategia; solo mejora la probabilidad de recibir delta/IV/bid/ask.
    """
    try:
        bid = clean_price(getattr(ticker, "bid", None))
        ask = clean_price(getattr(ticker, "ask", None))
        greeks = option_greeks(ticker)
        has_delta = greeks.get("delta") is not None
        has_iv = greeks.get("iv") is not None
        has_bidask = bool(bid and ask)
        return not (has_delta and has_iv and has_bidask)
    except Exception:
        return True

def option_greeks(ticker):
    greeks = (
        ticker.modelGreeks
        or ticker.bidGreeks
        or ticker.askGreeks
        or ticker.lastGreeks
    )

    if not greeks:
        return {
            "iv": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None
        }

    return {
        "iv": safe_round(getattr(greeks, "impliedVol", None), 4),
        "delta": safe_round(getattr(greeks, "delta", None), 4),
        "gamma": safe_round(getattr(greeks, "gamma", None), 6),
        "theta": safe_round(getattr(greeks, "theta", None), 4),
        "vega": safe_round(getattr(greeks, "vega", None), 4)
    }


def calculate_spread_pct(bid, ask, mid):
    try:
        if bid is None or ask is None or mid is None:
            return None

        if bid <= 0 or ask <= 0 or mid <= 0:
            return None

        spread = ask - bid

        if spread < 0:
            return None

        return safe_round(spread / mid, 4)

    except Exception:
        return None


def data_quality_for_option(bid, ask, mid, greeks):
    has_price = mid is not None and mid > 0
    has_bid_ask = bid is not None and ask is not None and bid > 0 and ask > 0
    has_delta = greeks.get("delta") is not None
    has_iv = greeks.get("iv") is not None

    if has_price and has_bid_ask and has_delta and has_iv:
        return "FULL_WITH_GREEKS"

    if has_price and has_delta and has_iv:
        return "PRICE_WITH_GREEKS_NO_BIDASK"

    if has_price and not has_delta and not has_iv:
        return "PRICE_ONLY_NO_GREEKS"

    if has_price:
        return "PARTIAL_OPTION_DATA"

    return "NO_VALID_OPTION_PRICE"


# ============================================================
# STOCK PRICE FALLBACKS
# ============================================================

def extract_price_from_ticker(ticker):
    price = clean(ticker.marketPrice())
    last = clean(ticker.last)
    bid = clean(ticker.bid)
    ask = clean(ticker.ask)
    close = clean(ticker.close)

    final_price = (
        price
        or last
        or ((bid + ask) / 2 if bid and ask else None)
        or close
    )

    final_price = clean(final_price)

    return {
        "price": final_price,
        "bid": bid,
        "ask": ask,
        "last": last,
        "close": close,
        "market_price": price
    }


def get_price_snapshot_req_tickers(symbol, contract):
    try:
        tickers = ib.reqTickers(contract)

        if not tickers:
            return None

        ticker = tickers[0]
        data = extract_price_from_ticker(ticker)

        if data["price"] is None:
            return None

        return {
            "ticker": symbol,
            "price": data["price"],
            "bid": data["bid"],
            "ask": data["ask"],
            "last": data["last"],
            "close": data["close"],
            "market_price": data["market_price"],
            "source": "IBKR_REALTIME_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_REQ_TICKERS"
        }

    except Exception:
        return None


def get_price_snapshot_req_mkt_data(symbol, contract):
    ticker = None

    try:
        ticker = ib.reqMktData(
            contract,
            genericTickList="",
            snapshot=False,
            regulatorySnapshot=False
        )

        ib.sleep(STOCK_MARKET_DATA_WAIT_SECONDS)

        data = extract_price_from_ticker(ticker)

        try:
            ib.cancelMktData(contract)
        except Exception:
            pass

        if data["price"] is None:
            return None

        return {
            "ticker": symbol,
            "price": data["price"],
            "bid": data["bid"],
            "ask": data["ask"],
            "last": data["last"],
            "close": data["close"],
            "market_price": data["market_price"],
            "source": "IBKR_REALTIME_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_MKT_DATA_FALLBACK"
        }

    except Exception:
        try:
            if ticker is not None:
                ib.cancelMktData(contract)
        except Exception:
            pass

        return None


def get_price_snapshot_historical(symbol, contract):
    """
    Fallback final:
    Si no hay precio vivo, intenta obtener último cierre histórico.
    Esto ayuda con casos como NFLX cuando reqTickers no devuelve precio.
    """
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False
        )

        if not bars:
            return None

        last_bar = bars[-1]
        close = clean(last_bar.close)

        if close is None:
            return None

        return {
            "ticker": symbol,
            "price": close,
            "bid": None,
            "ask": None,
            "last": None,
            "close": close,
            "market_price": None,
            "source": "IBKR_HISTORICAL_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_HISTORICAL_CLOSE_FALLBACK"
        }

    except Exception:
        return None


# ============================================================
# MARKET DATA
# ============================================================

def get_price_snapshot(symbol):
    try:
        contract = stock_contract(symbol)

        # 1. Método principal
        snap = get_price_snapshot_req_tickers(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        # 2. Fallback por streaming market data
        snap = get_price_snapshot_req_mkt_data(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        # 3. Fallback histórico
        snap = get_price_snapshot_historical(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        return None

    except Exception as e:
        print(symbol, "PRICE ERROR:", e)
        return None


def send_market_data():
    print("\n=== MARKET DATA V18_1_REMOTE_SNAPSHOT_INGEST ===\n")

    for symbol in WATCHLIST:
        snap = get_price_snapshot(symbol)

        if not snap or snap.get("price") is None:
            print(symbol, "sin precio válido")
            continue

        tv_context = tradingview_context_stub(symbol)

        payload = {
            "ticker": symbol,
            "timeframe": "live",
            "setup": "IBKR_LIVE_MARKET_V15",
            "trend": "",
            "score": 0,
            "price": snap["price"],
            "bid": snap["bid"],
            "ask": snap["ask"],
            "last": snap["last"],
            "close": snap["close"],
            "market_price": snap["market_price"],
            "source": snap["source"],
            "price_source": snap["price_source"],
            "asset_class": "EQUITY",
            "engine_layer": "IBKR_MARKET_DATA",
            "integration_ready_for_tradingview": True,
            "received_at_bridge": now_iso(),
            **tv_context
        }

        status = post(payload)

        print(
            f"{symbol} | price:{snap['price']} "
            f"bid:{snap['bid']} ask:{snap['ask']} "
            f"price_source:{snap['price_source']} status:{status}"
        )


# ============================================================
# PORTFOLIO COMMANDER
# ============================================================

def get_positions_rows():
    rows = []
    total_abs_value = 0

    try:
        positions = ib.positions()

    except Exception as e:
        print("POSITIONS ERROR:", e)
        return rows

    for position in positions:
        try:
            contract = position.contract
            symbol = contract.symbol
            sec_type = contract.secType

            qty = safe_round(position.position, 4)
            avg = safe_round(position.avgCost, 4)

            market_price = None
            market_value = None
            unrealized_pl = None
            price_source = None

            if sec_type == "STK":
                snap = get_price_snapshot(symbol)

                if snap and snap.get("price"):
                    market_price = snap["price"]
                    price_source = snap.get("price_source")
                    market_value = safe_round(market_price * position.position, 2)

                    unrealized_pl = safe_round(
                        (market_price - position.avgCost) * position.position,
                        2
                    )

                    total_abs_value += abs(market_value or 0)

            row = {
                "ticker": symbol,
                "local_symbol": getattr(contract, "localSymbol", None),
                "sec_type": sec_type,
                "right": getattr(contract, "right", None),
                "strike": getattr(contract, "strike", None),
                "expiration": getattr(contract, "lastTradeDateOrContractMonth", None),
                "position_size": qty,
                "avg_cost": avg,
                "market_price": market_price,
                "market_value": market_value,
                "unrealized_pl": unrealized_pl,
                "price_source": price_source
            }

            rows.append(row)

        except Exception as e:
            print("POSITION ROW ERROR:", e)

    for row in rows:
        weight = None

        if total_abs_value > 0 and row.get("market_value") is not None:
            weight = safe_round(
                abs(row["market_value"]) / total_abs_value * 100,
                2
            )

        row["portfolio_weight_pct"] = weight

    return rows


def classify_position(row):
    sec_type = row.get("sec_type")
    qty = row.get("position_size") or 0

    if sec_type == "STK" and qty > 0:
        if qty >= 100:
            return "COVERED_CALL_CANDIDATE"

        return "LONG_STOCK_SMALL"

    if sec_type == "STK" and qty < 0:
        return "SHORT_STOCK"

    if sec_type == "OPT":
        right = row.get("right")

        if right == "C" and qty < 0:
            return "SHORT_CALL"

        if right == "P" and qty < 0:
            return "SHORT_PUT"

        if right == "C" and qty > 0:
            return "LONG_CALL"

        if right == "P" and qty > 0:
            return "LONG_PUT"

    if sec_type in ["FUT", "CONTFUT"]:
        return "FUTURES_POSITION"

    return "POSITION"


def send_positions():
    print("\n=== PORTFOLIO COMMANDER V18_1_REMOTE_SNAPSHOT_INGEST ===\n")

    rows = get_positions_rows()

    if not rows:
        print("Sin posiciones detectadas.")
        return

    for row in rows:
        position_class = classify_position(row)
        tv_context = tradingview_context_stub(row["ticker"])

        payload = {
            "ticker": row["ticker"],
            "timeframe": "position",
            "setup": f"IBKR_{position_class}_V15",
            "trend": "",
            "score": 0,
            "source": "IBKR_PORTFOLIO_V15",
            "asset_class": "POSITION",
            "engine_layer": "IBKR_PORTFOLIO_COMMANDER",
            "integration_ready_for_tradingview": True,
            "position_class": position_class,
            "local_symbol": row["local_symbol"],
            "sec_type": row["sec_type"],
            "right": row["right"],
            "strike": row["strike"],
            "expiration": row["expiration"],
            "position_size": row["position_size"],
            "avg_cost": row["avg_cost"],
            "market_price": row["market_price"],
            "market_value": row["market_value"],
            "unrealized_pl": row["unrealized_pl"],
            "portfolio_weight_pct": row["portfolio_weight_pct"],
            "price_source": row["price_source"],
            "received_at_bridge": now_iso(),
            **tv_context
        }

        status = post(payload)

        print(
            f"POS {row['ticker']} | type:{row['sec_type']} "
            f"class:{position_class} size:{row['position_size']} "
            f"value:{row['market_value']} pnl:{row['unrealized_pl']} "
            f"weight:{row['portfolio_weight_pct']} "
            f"price_source:{row['price_source']} status:{status}"
        )


# ============================================================
# OPTIONS INTELLIGENCE
# ============================================================

def choose_expiration_from_chain(expirations):
    today = datetime.now().date()
    candidates = []

    for exp in sorted(expirations):
        try:
            exp_date = datetime.strptime(exp, "%Y%m%d").date()
            dte = (exp_date - today).days

            if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
                candidates.append((exp, dte))

        except Exception:
            pass

    if candidates:
        return sorted(
            candidates,
            key=lambda x: abs(x[1] - TARGET_DTE_IDEAL)
        )[0]

    return None, None



def score_option_candidate(*args, **kwargs):
    """
    V16.2 Decision Cap:
    Envuelve la evaluación original de opciones.
    - Mercado cerrado: nunca permite OPERAR; máximo RADAR/preparación.
    - Mercado abierto: si faltan bid/ask/spread confiable, bloquea OPERAR.
    """
    result = _score_option_candidate_core(*args, **kwargs)

    if not isinstance(result, dict):
        return result

    market_open = ibkr_market_is_open_for_options()
    result["market_open_for_options"] = market_open

    decision = str(result.get("decision", "")).upper()
    final_decision = str(result.get("final_decision", "")).upper()
    strategy_decision = str(result.get("strategy_decision", "")).upper()
    cap = str(result.get("cap", "")).upper()
    quality = str(result.get("data_quality", result.get("quality", ""))).upper()

    blockers = result.get("blockers", [])
    if blockers is None:
        blockers = []
    if not isinstance(blockers, list):
        blockers = [str(blockers)]

    warnings = result.get("warnings", [])
    if warnings is None:
        warnings = []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    # Mercado cerrado: no hay entrada ejecutable.
    if not market_open:
        result["market_closed_note"] = "MARKET_CLOSED_NO_BIDASK_EXPECTED"
        result["execution_cap"] = "RADAR_ONLY_MARKET_CLOSED"

        if decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["decision"] = "RADAR"

        if final_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["final_decision"] = "RADAR"

        if strategy_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["strategy_decision"] = "RADAR"

        if cap in ["OPERAR", "ENTRY", "TRADE"]:
            result["cap"] = "RADAR"

        if "Mercado cerrado: bid/ask de opciones puede no ser confiable." not in warnings:
            warnings.append("Mercado cerrado: bid/ask de opciones puede no ser confiable.")

        result["warnings"] = warnings
        result["blockers"] = blockers
        result["can_operar"] = False

        if result.get("decision") in [None, "", "OPERAR"]:
            result["decision"] = "RADAR"

        v17_store_row(result)
        return result

    # Mercado abierto: si el motor quería OPERAR pero no hay bid/ask o spread completo, se bloquea.
    wants_operate = (
        decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
        or final_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
        or strategy_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
    )

    incomplete_market_quality = (
        "NO_BIDASK" in quality
        or "NO_GREEKS" in quality
        or "WAIT_FOR_GREEKS" in cap
        or "PRICE_ONLY" in quality
    )

    if market_open and wants_operate and incomplete_market_quality:
        result["execution_cap"] = "BLOCKED_OPEN_MARKET_REQUIRES_BIDASK_SPREAD"
        result["decision"] = "RADAR"
        result["final_decision"] = "RADAR"
        result["strategy_decision"] = "RADAR"
        result["cap"] = "RADAR"
        result["can_operar"] = False

        blocker = "Mercado abierto: para OPERAR se requiere bid/ask/spread y griegas confiables."
        if blocker not in blockers:
            blockers.append(blocker)

    result["warnings"] = warnings
    result["blockers"] = blockers
    v17_store_row(result)
    return result


def get_option_chain(symbol):
    try:
        stock = stock_contract(symbol)

        chains = ib.reqSecDefOptParams(
            stock.symbol,
            "",
            stock.secType,
            stock.conId
        )

        if not chains:
            print(symbol, "sin option chains desde IBKR")
            return None, None, None

        usable = []

        for chain in chains:
            expirations = list(chain.expirations or [])
            strikes = list(chain.strikes or [])

            if not expirations or not strikes:
                continue

            expiry, dte = choose_expiration_from_chain(expirations)

            if expiry:
                usable.append(
                    {
                        "chain": chain,
                        "expiry": expiry,
                        "dte": dte,
                        "is_smart": chain.exchange == "SMART",
                        "strike_count": len(strikes)
                    }
                )

        if usable:
            selected = sorted(
                usable,
                key=lambda x: (
                    0 if x["is_smart"] else 1,
                    abs(x["dte"] - TARGET_DTE_IDEAL),
                    -x["strike_count"]
                )
            )[0]

            return selected["chain"], selected["expiry"], selected["dte"]

        # Fallback: si ninguna cadena tiene 25-65 DTE, usamos la mejor mayor a 10 DTE.
        fallback = []

        today = datetime.now().date()

        for chain in chains:
            expirations = list(chain.expirations or [])
            strikes = list(chain.strikes or [])

            if not expirations or not strikes:
                continue

            for exp in sorted(expirations):
                try:
                    exp_date = datetime.strptime(exp, "%Y%m%d").date()
                    dte = (exp_date - today).days

                    if dte > 10:
                        fallback.append(
                            {
                                "chain": chain,
                                "expiry": exp,
                                "dte": dte,
                                "is_smart": chain.exchange == "SMART",
                                "strike_count": len(strikes)
                            }
                        )

                except Exception:
                    pass

        if fallback:
            selected = sorted(
                fallback,
                key=lambda x: (
                    0 if x["is_smart"] else 1,
                    abs(x["dte"] - TARGET_DTE_IDEAL),
                    -x["strike_count"]
                )
            )[0]

            return selected["chain"], selected["expiry"], selected["dte"]

        print(symbol, "sin expiración válida")
        return None, None, None

    except Exception as e:
        print(symbol, "CHAIN ERROR:", e)
        return None, None, None


def qualify_option(symbol, expiry, strike, right, chain):
    try:
        trading_class = getattr(chain, "tradingClass", None)
        multiplier = getattr(chain, "multiplier", None)

        contract = Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=float(strike),
            right=right,
            exchange="SMART",
            currency="USD",
            multiplier=multiplier,
            tradingClass=trading_class
        )

        qualified = ib.qualifyContracts(contract)

        if qualified:
            return qualified[0]

        return None

    except Exception:
        return None


def pick_put_strikes(strikes, stock_price):
    raw_puts = []

    for strike in strikes:
        distance = (strike - stock_price) / stock_price

        if -0.18 < distance < -0.05:
            if is_standard_strike(strike):
                raw_puts.append(strike)

    selected = sorted(
        raw_puts,
        key=lambda x: abs(abs((x - stock_price) / stock_price) - 0.10)
    )[:4]

    return selected


def pick_call_strikes(strikes, stock_price):
    raw_calls = []

    for strike in strikes:
        distance = (strike - stock_price) / stock_price

        if 0.03 < distance < 0.15:
            if is_standard_strike(strike):
                raw_calls.append(strike)

    selected = sorted(
        raw_calls,
        key=lambda x: abs(abs((x - stock_price) / stock_price) - 0.08)
    )[:4]

    return selected


def build_option_candidates(symbol, stock_price):
    chain, expiry, dte = get_option_chain(symbol)

    if chain is None:
        print(symbol, "sin cadena")
        return []

    strikes = sorted([
        float(strike)
        for strike in chain.strikes
        if strike is not None and float(strike) > 0
    ])

    if len(strikes) == 0:
        print(symbol, "sin strikes")
        return []

    puts = []
    calls = []

    if ENABLE_NAKED_PUTS:
        puts = pick_put_strikes(strikes, stock_price)

    if ENABLE_COVERED_CALLS:
        calls = pick_call_strikes(strikes, stock_price)

    valid = []
    invalid_count = 0

    for strike in puts:
        contract = qualify_option(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            right="P",
            chain=chain
        )

        if contract:
            valid.append(
                (
                    contract,
                    dte,
                    "NAKED_PUT"
                )
            )
        else:
            invalid_count += 1

    for strike in calls:
        contract = qualify_option(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            right="C",
            chain=chain
        )

        if contract:
            valid.append(
                (
                    contract,
                    dte,
                    "COVERED_CALL"
                )
            )
        else:
            invalid_count += 1

    print(
        f"{symbol} contratos válidos:",
        len(valid),
        "| inválidos filtrados:",
        invalid_count,
        "| expiry:",
        expiry,
        "| dte:",
        dte,
        "| chain exchange:",
        getattr(chain, "exchange", None),
        "| tradingClass:",
        getattr(chain, "tradingClass", None),
        "| multiplier:",
        getattr(chain, "multiplier", None)
    )

    return valid[:MAX_OPTIONS_PER_SYMBOL]


def request_option_market_data(contract):
    ticker = None

    try:
        ticker = ib.reqMktData(
            contract,
            genericTickList="100,101,106",
            snapshot=False,
            regulatorySnapshot=False
        )

        ib.sleep(OPTION_MARKET_DATA_WAIT_SECONDS)

        bid = clean(ticker.bid)
        ask = clean(ticker.ask)
        last = clean(ticker.last)
        close = clean(ticker.close)
        market_price = clean(ticker.marketPrice())

        mid = None

        if bid and ask:
            mid = safe_round((bid + ask) / 2, 4)

        elif market_price:
            mid = market_price

        elif last:
            mid = last

        elif close:
            mid = close

        greeks = option_greeks(ticker)

        spread_pct = calculate_spread_pct(
            bid=bid,
            ask=ask,
            mid=mid
        )

        spread = None
        if bid is not None and ask is not None and ask >= bid:
            spread = safe_round(ask - bid, 4)

        volume = clean(getattr(ticker, "volume", None))
        if getattr(contract, "right", "") == "P":
            option_volume = clean(getattr(ticker, "putVolume", None)) or volume
            open_interest = clean(getattr(ticker, "putOpenInterest", None))
        elif getattr(contract, "right", "") == "C":
            option_volume = clean(getattr(ticker, "callVolume", None)) or volume
            open_interest = clean(getattr(ticker, "callOpenInterest", None))
        else:
            option_volume = volume
            open_interest = None

        data_quality = data_quality_for_option(
            bid=bid,
            ask=ask,
            mid=mid,
            greeks=greeks
        )

        try:
            ib.cancelMktData(contract)
        except Exception:
            pass

        return {
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "market_price": market_price,
            "mid": mid,
            "spread_pct": spread_pct,
            "spread": spread,
            "greeks": greeks,
            "data_quality": data_quality,
            "volume": option_volume,
            "open_interest": open_interest
        }

    except Exception as e:
        try:
            if ticker is not None:
                ib.cancelMktData(contract)
        except Exception:
            pass

        return {
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "market_price": None,
            "mid": None,
            "spread_pct": None,
            "spread": None,
            "greeks": {
                "iv": None,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None
            },
            "data_quality": "OPTION_MARKET_DATA_ERROR",
            "volume": None,
            "open_interest": None,
            "error": str(e)
        }


def liquidity_decision_cap(data_quality, spread_pct, mid):
    if mid is None or mid <= 0:
        return "NO_OPERAR_SIN_PRECIO"

    if mid < MIN_OPTION_MID_FOR_RADAR:
        return "ESPERAR"

    if data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR"]:
        return "NO_OPERAR_SIN_PRECIO"

    if data_quality == "PRICE_ONLY_NO_GREEKS":
        return "WAIT_FOR_GREEKS"

    if data_quality == "PARTIAL_OPTION_DATA":
        return "WAIT_FOR_GREEKS"

    if data_quality == "PRICE_WITH_GREEKS_NO_BIDASK":
        return "RADAR"

    if data_quality == "FULL_WITH_GREEKS":
        if spread_pct is None:
            return "RADAR"

        if spread_pct > MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR:
            return "ESPERAR"

        if spread_pct > MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR:
            return "RADAR"

        return "OPERAR_ALLOWED"

    return "ESPERAR"


def apply_decision_cap(raw_decision, decision_cap):
    if decision_cap == "NO_OPERAR_SIN_PRECIO":
        return "NO_OPERAR_SIN_PRECIO"

    if decision_cap == "WAIT_FOR_GREEKS":
        return "WAIT_FOR_GREEKS"

    if decision_cap == "ESPERAR":
        return "ESPERAR"

    if decision_cap == "RADAR":
        if raw_decision == "OPERAR":
            return "RADAR"
        return raw_decision

    if decision_cap == "OPERAR_ALLOWED":
        return raw_decision

    return "ESPERAR"


def _score_option_candidate_core(strategy, option_type, strike, stock_price, dte, greeks, mid, data_quality, spread_pct):
    score = 50
    reason = []

    delta = greeks.get("delta")
    iv = greeks.get("iv")

    if mid is None or mid <= 0:
        score -= 50
        reason.append("sin precio válido de opción")

    elif mid < MIN_OPTION_MID_FOR_RADAR:
        score -= 25
        reason.append("prima demasiado baja")

    elif mid >= MIN_OPTION_MID_FOR_OPERAR:
        score += 5
        reason.append("prima disponible")

    if data_quality == "FULL_WITH_GREEKS":
        score += 10
        reason.append("data completa con griegas")

    elif data_quality == "PRICE_WITH_GREEKS_NO_BIDASK":
        score -= 5
        reason.append("griegas disponibles sin bid/ask completo")

    elif data_quality == "PRICE_ONLY_NO_GREEKS":
        score -= 25
        reason.append("sin delta ni IV")

    elif data_quality == "PARTIAL_OPTION_DATA":
        score -= 20
        reason.append("data parcial")

    elif data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR"]:
        score -= 40
        reason.append("sin precio válido o error de market data")

    if spread_pct is not None:
        if spread_pct <= MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR:
            score += 10
            reason.append("spread razonable")

        elif spread_pct <= MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR:
            score -= 5
            reason.append("spread moderado")

        else:
            score -= 20
            reason.append("spread amplio")
    else:
        reason.append("spread no disponible")

    if strategy == "NAKED_PUT":
        if delta is not None:
            abs_delta = abs(delta)

            if 0.12 <= abs_delta <= 0.25:
                score += 25
                reason.append("delta favorable naked put")

            elif 0.08 <= abs_delta < 0.12:
                score += 10
                reason.append("delta conservador naked put")

            elif abs_delta < 0.08:
                score -= 5
                reason.append("delta muy bajo, prima probablemente baja")

            else:
                score -= 20
                reason.append("delta alto para naked put")
        else:
            score -= 20
            reason.append("delta no disponible")

        if strike < stock_price:
            score += 10
            reason.append("strike OTM")

        else:
            score -= 30
            reason.append("strike no está OTM para naked put")

    if strategy == "COVERED_CALL":
        if delta is not None:
            abs_delta = abs(delta)

            if 0.15 <= abs_delta <= 0.35:
                score += 25
                reason.append("delta favorable covered call")

            elif 0.08 <= abs_delta < 0.15:
                score += 10
                reason.append("delta conservador covered call")

            elif abs_delta < 0.08:
                score -= 5
                reason.append("delta muy bajo, prima probablemente baja")

            else:
                score -= 20
                reason.append("call muy cercana o agresiva")
        else:
            score -= 20
            reason.append("delta no disponible")

        if strike > stock_price:
            score += 10
            reason.append("call OTM")

        else:
            score -= 30
            reason.append("call no está OTM")

    if iv is not None:
        if iv >= 0.35:
            score += 10
            reason.append("IV atractiva")

        elif 0.18 <= iv < 0.35:
            score += 5
            reason.append("IV razonable")

        elif iv < 0.15:
            score -= 10
            reason.append("IV baja")
    else:
        score -= 15
        reason.append("IV no disponible")

    if dte is not None and TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
        score += 10
        reason.append("DTE adecuado")

    elif dte is not None:
        score -= 10
        reason.append("DTE fuera de rango ideal")

    else:
        score -= 10
        reason.append("DTE no disponible")

    score = max(0, min(100, score))

    if score >= 85:
        raw_decision = "OPERAR"

    elif score >= 65:
        raw_decision = "RADAR"

    elif data_quality in ["PRICE_ONLY_NO_GREEKS", "PARTIAL_OPTION_DATA"]:
        raw_decision = "WAIT_FOR_GREEKS"

    else:
        raw_decision = "ESPERAR"

    decision_cap = liquidity_decision_cap(
        data_quality=data_quality,
        spread_pct=spread_pct,
        mid=mid
    )

    final_decision = apply_decision_cap(
        raw_decision=raw_decision,
        decision_cap=decision_cap
    )

    if final_decision != raw_decision:
        reason.append(f"decisión limitada por calidad/liquidez: {decision_cap}")

    return score, final_decision, "; ".join(reason), decision_cap


def send_options_intelligence():
    print("\n=== OPTIONS INTELLIGENCE V18_1_REMOTE_SNAPSHOT_INGEST ===\n")

    for symbol in OPTION_SYMBOLS:
        try:
            snap = get_price_snapshot(symbol)

            if not snap or not snap.get("price"):
                print(symbol, "sin precio para opciones")
                continue

            stock_price = snap["price"]

            candidates = build_option_candidates(symbol, stock_price)

            if not candidates:
                print(symbol, "sin opciones candidatas")
                continue

            for item in candidates:
                try:
                    contract = item[0]
                    dte = item[1]
                    strategy = item[2]

                    option_data = request_option_market_data(contract)

                    bid = option_data.get("bid")
                    ask = option_data.get("ask")
                    last = option_data.get("last")
                    close = option_data.get("close")
                    market_price = option_data.get("market_price")
                    mid = option_data.get("mid")
                    spread_pct = option_data.get("spread_pct")
                    spread = option_data.get("spread")
                    greeks = option_data.get("greeks")
                    data_quality = option_data.get("data_quality")
                    volume = option_data.get("volume")
                    open_interest = option_data.get("open_interest")

                    if not SEND_OPTIONS_WITHOUT_GREEKS:
                        if data_quality != "FULL_WITH_GREEKS":
                            print(
                                f"{symbol} {strategy} {contract.strike} "
                                f"omitida por data_quality:{data_quality}"
                            )
                            continue

                    option_type = "PUT" if contract.right == "P" else "CALL"

                    score, decision, reason, decision_cap = score_option_candidate(
                        strategy=strategy,
                        option_type=option_type,
                        strike=contract.strike,
                        stock_price=stock_price,
                        dte=dte,
                        greeks=greeks,
                        mid=mid,
                        data_quality=data_quality,
                        spread_pct=spread_pct
                    )

                    required_execution_fields = {
                        "bid": bid,
                        "ask": ask,
                        "spread": spread,
                        "spread_pct": spread_pct,
                        "strike": contract.strike,
                        "expiration": contract.lastTradeDateOrContractMonth,
                        "dte": dte,
                        "delta": greeks.get("delta"),
                    }
                    missing_confirmations = [
                        key
                        for key, value in required_execution_fields.items()
                        if value is None
                    ]
                    manual_review_ready = (
                        len(missing_confirmations) == 0
                        and decision in ["OPERAR", "ENTRY", "ENTRY_READY"]
                    )

                    tv_context = tradingview_context_stub(symbol)

                    payload = {
                        "ticker": symbol,
                        "timeframe": "options",
                        "setup": f"IBKR_{strategy}_V15",
                        "trend": "",
                        "score": score,
                        "price": stock_price,
                        "underlying_price_source": snap.get("price_source"),
                        "source": "IBKR_OPTIONS_V18_1_REMOTE_SNAPSHOT_INGEST",
                        "asset_class": "OPTION",
                        "engine_layer": "IBKR_OPTIONS_INTELLIGENCE",
                        "integration_ready_for_tradingview": True,
                        "data_quality": data_quality,
                        "decision_cap": decision_cap,
                        "decision": "ENTRY_READY" if manual_review_ready else decision,
                        "final_decision": "ENTRY_READY" if manual_review_ready else decision,
                        "option_symbol": contract.localSymbol,
                        "local_symbol": contract.localSymbol,
                        "option_type": option_type,
                        "strategy_hint": strategy,
                        "strategy_decision": decision,
                        "strategy_reason": reason,
                        "strike": contract.strike,
                        "expiration": contract.lastTradeDateOrContractMonth,
                        "dte": dte,
                        "bid": bid,
                        "ask": ask,
                        "last": last,
                        "close": close,
                        "market_price": market_price,
                        "mid": mid,
                        "spread_pct": spread_pct,
                        "spread": spread,
                        "implied_volatility": greeks["iv"],
                        "iv": greeks["iv"],
                        "delta": greeks["delta"],
                        "gamma": greeks["gamma"],
                        "theta": greeks["theta"],
                        "vega": greeks["vega"],
                        "volume": volume,
                        "open_interest": open_interest,
                        "can_operate": False,
                        "manual_review_ready": manual_review_ready,
                        "not_order_instruction": True,
                        "missing_confirmations": missing_confirmations,
                        "recommendation": "LISTO_PARA_REVISION_MANUAL" if manual_review_ready else "ESPERAR_DATOS_EJECUTABLES",
                        "reason": reason,
                        "v30_contract_enrichment": True,
                        "v30_required_fields_complete": len(missing_confirmations) == 0,
                        "moneyness_pct": safe_round(
                            (contract.strike / stock_price - 1) * 100,
                            2
                        ),
                        "received_at_bridge": now_iso(),
                        **tv_context
                    }

                    v17_store_row(payload)

                    status = post(payload)

                    print(
                        f"{symbol} {strategy} "
                        f"{contract.strike} exp:{contract.lastTradeDateOrContractMonth} "
                        f"mid:{mid} bid:{bid} ask:{ask} spread:{spread} spread_pct:{spread_pct} "
                        f"delta:{greeks['delta']} iv:{greeks['iv']} "
                        f"quality:{data_quality} cap:{decision_cap} "
                        f"score:{score} decision:{decision} "
                        f"underlying_source:{snap.get('price_source')} "
                        f"status:{status}"
                    )

                except Exception as e:
                    print(symbol, "OPTION ROW ERROR:", e)

        except Exception as e:
            print(symbol, "OPTIONS ERROR:", e)


# ============================================================
# MAIN LOOP
# ============================================================




print("Conectando a IBKR...")

try:
    ib.connect(
        IB_HOST,
        IB_PORT,
        clientId=CLIENT_ID,
        timeout=20,
        readonly=True
    )

    print("IBKR conectado correctamente")

except Exception as e:
    print("ERROR conectando IBKR:")
    print(e)
    raise SystemExit


set_market_data_type()

print("")


# ============================================================
# SUPER ENGINE BOLSA — V17.1 SUMMARY STORE
# ============================================================

V17_SUMMARY_ROWS = []

def v17_store_row(row):
    try:
        if isinstance(row, dict):
            V17_SUMMARY_ROWS.append(row)
    except Exception:
        pass
    return row

def v17_store_rows(rows):
    try:
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    V17_SUMMARY_ROWS.append(r)
        elif isinstance(rows, dict):
            V17_SUMMARY_ROWS.append(rows)
    except Exception:
        pass
    return rows

def v17_reset_summary_rows():
    try:
        V17_SUMMARY_ROWS.clear()
    except Exception:
        pass






# ============================================================
# SUPER ENGINE BOLSA — V18.1 REMOTE SNAPSHOT INGEST CLIENT
# ============================================================

import os as _v18_1_os
import urllib.request as _v18_1_urllib_request
import urllib.error as _v18_1_urllib_error

V18_1_REMOTE_INGEST_URL = _v18_1_os.getenv(
    "DECISION_DESK_INGEST_URL",
    "https://trading-engine-p097.onrender.com/decision_desk/ingest"
)

V18_1_INGEST_TOKEN = _v18_1_os.getenv("DECISION_DESK_INGEST_TOKEN", "")

def v18_1_post_decision_snapshot(payload):
    """
    V18.1:
    Envía el snapshot generado localmente por ibkr_bridge.py hacia Render,
    para que /decision_desk, /decision_desk/{ticker} y /decision_desk/health
    puedan mostrar datos reales.
    """
    try:
        if not payload or not isinstance(payload, dict):
            return {"posted": False, "reason": "empty_payload"}

        body = _v18_json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SuperEngineBolsa-V18.1",
        }

        if V18_1_INGEST_TOKEN:
            headers["X-Decision-Desk-Token"] = V18_1_INGEST_TOKEN

        req = _v18_1_urllib_request.Request(
            V18_1_REMOTE_INGEST_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        with _v18_1_urllib_request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return {
                "posted": True,
                "status": getattr(resp, "status", None),
                "response": raw[:300],
            }

    except Exception as e:
        return {
            "posted": False,
            "error": str(e),
            "url": V18_1_REMOTE_INGEST_URL,
        }

# ============================================================
# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API HELPERS
# ============================================================

import json as _v18_json
from pathlib import Path as _v18_Path
from datetime import datetime as _v18_datetime, timezone as _v18_timezone

V18_SNAPSHOT_PATH = _v18_Path("runtime/decision_desk_snapshot.json")

def v18_safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def v18_normalize_decision(raw):
    try:
        d = str(raw or "").upper().strip()
    except Exception:
        d = ""

    if d in ["ENTRY", "ENTRY_READY", "ENTRY_OPPORTUNITY", "OPERAR", "TRADE"]:
        return "ENTRY"
    if d in ["MANAGE_POSITION", "MANAGE", "GESTION", "REVISAR_GESTION"]:
        return "MANAGE_POSITION"
    if d in ["RADAR", "WATCH", "PREPARATION", "PREPARACION"]:
        return "RADAR"
    if d in ["WAIT_FOR_GREEKS", "WAIT_GREEKS"]:
        return "WAIT_GREEKS"
    if d in ["WAIT_FOR_DATA", "MISSING_DATA", "WAIT_DATA"]:
        return "WAIT_DATA"
    if d in ["BLOCKED", "NO_TRADE", "REJECTED"]:
        return "BLOCKED"
    if d in ["ESPERAR", "WAIT"]:
        return "WAIT_DATA"

    return d or "WAIT_DATA"

def v18_missing_confirmations(row):
    missing = []

    quality = str(row.get("data_quality") or row.get("quality") or "").upper()
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    if "NO_BIDASK" in quality:
        missing.append("bid_ask")
        missing.append("spread")

    if "PRICE_ONLY" in quality:
        missing.append("greeks")
        missing.append("bid_ask")
        missing.append("spread")

    if decision == "WAIT_GREEKS":
        if "greeks" not in missing:
            missing.append("greeks")

    if decision == "WAIT_DATA":
        if "data_confirmation" not in missing:
            missing.append("data_confirmation")

    if row.get("price") in [None, "", "None"]:
        missing.append("price")

    for field in [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]:
        if row.get(field) in [None, "", "None"]:
            missing.append(field)

    try:
        bid = v18_safe_float(row.get("bid"), 0)
        ask = v18_safe_float(row.get("ask"), 0)
        if bid <= 0:
            missing.append("bid")
        if ask <= 0:
            missing.append("ask")
        if bid > 0 and ask > 0 and ask < bid:
            missing.append("bid_ask_order")
    except Exception:
        pass

    # Deduplicar preservando orden
    final = []
    for x in missing:
        if x not in final:
            final.append(x)

    return final

def v18_can_operate(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    score = v18_safe_float(row.get("score"), 0)

    if decision != "ENTRY":
        return False

    if score < 80:
        return False

    if missing:
        return False

    return True

def v18_recommendation(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    can_operate = v18_can_operate(row)

    if can_operate:
        return "Listo para revision manual. Validar tamano, riesgo y confirmacion final antes de cualquier decision."

    if decision == "MANAGE_POSITION":
        return "Prioridad de gestión. Revisar posición abierta antes de abrir nuevas operaciones."

    if decision == "RADAR":
        if missing:
            return "Mantener en radar. No operar directo hasta confirmar: " + ", ".join(missing) + "."
        return "Mantener en radar. Aún no es entrada confirmada."

    if decision == "WAIT_GREEKS":
        return "Esperar. Faltan griegas o datos suficientes para validar la operación."

    if decision == "WAIT_DATA":
        return "Esperar. Faltan datos críticos o confirmación suficiente."

    if decision == "BLOCKED":
        return "Bloqueado. No operar bajo las condiciones actuales."

    return "Esperar. No hay ventaja operativa suficiente."

def v18_reason(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    quality = str(row.get("data_quality") or row.get("quality") or "UNKNOWN")
    score = v18_safe_float(row.get("score"), 0)
    missing = v18_missing_confirmations(row)

    if decision == "RADAR" and score >= 80:
        if missing:
            return f"Score alto y datos parciales útiles, pero faltan confirmaciones: {', '.join(missing)}."
        return "Score alto, pero la señal permanece en radar y no en entrada."

    if decision == "WAIT_GREEKS":
        return "La oportunidad requiere griegas completas antes de tomar decisión."

    if decision == "WAIT_DATA":
        return "La oportunidad requiere más datos antes de tomar decisión."

    if decision == "BLOCKED":
        return "La operación fue bloqueada por calidad, liquidez, spread o reglas de seguridad."

    if decision == "ENTRY":
        return "La oportunidad cumple criterios principales de entrada, sujeto a gestión de riesgo."

    return f"Decisión {decision} con calidad de datos {quality}."

def v18_compact_row(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    compact = {
        "ticker": str(row.get("ticker") or row.get("symbol") or "UNKNOWN"),
        "strategy": str(row.get("strategy") or row.get("strategy_hint") or row.get("setup") or "UNKNOWN"),
        "decision": decision,
        "score": v18_safe_float(row.get("score"), 0),
        "price": row.get("price") or row.get("mid") or row.get("last"),
        "data_quality": row.get("data_quality") or row.get("quality") or "UNKNOWN",
        "can_operate": False,
        "missing_confirmations": [],
        "recommendation": "",
        "reason": "",
    }

    for field in [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
        "gamma",
        "theta",
        "vega",
        "iv",
        "implied_volatility",
        "volume",
        "open_interest",
        "option_symbol",
        "local_symbol",
        "option_type",
        "decision_cap",
        "v30_contract_enrichment",
        "v30_required_fields_complete",
    ]:
        if field in row:
            compact[field] = row.get(field)

    compact["missing_confirmations"] = v18_missing_confirmations(compact | row)
    compact["can_operate"] = v18_can_operate(compact | row)
    compact["recommendation"] = v18_recommendation(compact | row)
    compact["reason"] = v18_reason(compact | row)

    return compact

def v18_priority_rank(row):
    decision = v18_normalize_decision(row.get("decision"))
    score = v18_safe_float(row.get("score"), 0)

    decision_weight = {
        "MANAGE_POSITION": 500,
        "ENTRY": 400,
        "RADAR": 300,
        "WAIT_GREEKS": 150,
        "WAIT_DATA": 100,
        "BLOCKED": 0,
    }.get(decision, 50)

    return decision_weight + score

def v18_build_decision_payload(rows=None):
    try:
        if rows is None:
            rows = []

        clean_rows = []
        seen = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            c = v18_compact_row(row)
            key = (
                c.get("ticker"),
                c.get("strategy"),
                c.get("decision"),
                str(c.get("price")),
                str(c.get("score")),
            )

            if key in seen:
                continue

            seen.add(key)
            clean_rows.append(c)

        clean_rows.sort(key=v18_priority_rank, reverse=True)

        summary = {
            "entry": sum(1 for r in clean_rows if r["decision"] == "ENTRY"),
            "manage_position": sum(1 for r in clean_rows if r["decision"] == "MANAGE_POSITION"),
            "radar": sum(1 for r in clean_rows if r["decision"] == "RADAR"),
            "wait_greeks": sum(1 for r in clean_rows if r["decision"] == "WAIT_GREEKS"),
            "wait_data": sum(1 for r in clean_rows if r["decision"] == "WAIT_DATA"),
            "blocked": sum(1 for r in clean_rows if r["decision"] == "BLOCKED"),
            "total": len(clean_rows),
        }

        by_ticker = {}
        by_strategy = {}

        for r in clean_rows:
            ticker = r["ticker"]
            strategy = r["strategy"]
            decision = r["decision"]

            by_ticker.setdefault(ticker, {
                "ticker": ticker,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            by_strategy.setdefault(strategy, {
                "strategy": strategy,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            for bucket in [by_ticker[ticker], by_strategy[strategy]]:
                bucket["total"] += 1
                if decision == "ENTRY":
                    bucket["entry"] += 1
                elif decision == "RADAR":
                    bucket["radar"] += 1
                elif decision == "WAIT_GREEKS":
                    bucket["wait_greeks"] += 1
                elif decision == "WAIT_DATA":
                    bucket["wait_data"] += 1
                elif decision == "BLOCKED":
                    bucket["blocked"] += 1

                if bucket["best"] is None or v18_priority_rank(r) > v18_priority_rank(bucket["best"]):
                    bucket["best"] = r

        next_best_action = clean_rows[0] if clean_rows else None

        if next_best_action:
            global_recommendation = next_best_action.get("recommendation")
        else:
            global_recommendation = "No hay oportunidades operativas disponibles en el último ciclo."

        payload = {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "summary": summary,
            "next_best_action": next_best_action,
            "recommendation": global_recommendation,
            "by_ticker": list(by_ticker.values()),
            "by_strategy": list(by_strategy.values()),
            "top": clean_rows[:20],
            "health": {
                "snapshot_available": True,
                "rows_captured": len(clean_rows),
                "can_operate_count": sum(1 for r in clean_rows if r.get("can_operate")),
            },
        }

        return payload

    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "error": str(e),
            "summary": {
                "entry": 0,
                "manage_position": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "total": 0,
            },
            "next_best_action": None,
            "recommendation": "No se pudo construir la decisión operativa.",
            "by_ticker": [],
            "by_strategy": [],
            "top": [],
            "health": {
                "snapshot_available": False,
                "rows_captured": 0,
                "can_operate_count": 0,
            },
        }

def v18_write_decision_snapshot(rows=None):
    try:
        payload = v18_build_decision_payload(rows or V17_SUMMARY_ROWS)
        V18_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        V18_SNAPSHOT_PATH.write_text(_v18_json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "error": str(e),
            "recommendation": "No se pudo guardar el snapshot V18.",
        }

# ============================================================
# SUPER ENGINE BOLSA — V17.3C SUPPRESS IBKR NOISE
# ============================================================

import sys as _v17_sys
import logging as _v17_logging

class V17NoiseFilter:
    def __init__(self, stream):
        self.stream = stream

    def write(self, message):
        try:
            msg = str(message)
            if "Unknown contract:" in msg:
                return
            if "Option(symbol=" in msg and "tradingClass=" in msg:
                return
            return self.stream.write(message)
        except Exception:
            return self.stream.write(message)

    def flush(self):
        try:
            return self.stream.flush()
        except Exception:
            pass

try:
    _v17_sys.stderr = V17NoiseFilter(_v17_sys.stderr)
except Exception:
    pass

try:
    class V17LoggingNoiseFilter(_v17_logging.Filter):
        def filter(self, record):
            msg = str(record.getMessage())
            if "Unknown contract:" in msg:
                return False
            if "Option(symbol=" in msg and "tradingClass=" in msg:
                return False
            return True

    _v17_logging.getLogger().addFilter(V17LoggingNoiseFilter())
    _v17_logging.getLogger("ib_insync").addFilter(V17LoggingNoiseFilter())
except Exception:
    pass

# ============================================================
# SUPER ENGINE BOLSA — V17.3 CLEAN CONSOLE
# ============================================================

V17_CLEAN_CONSOLE = True

def v17_should_hide_console_line(text):
    try:
        if not V17_CLEAN_CONSOLE:
            return False

        if not isinstance(text, str):
            text = str(text)

        stripped = text.strip()

        if not stripped:
            return False

        # Ocultar ruido de contratos inválidos / desconocidos
        if "Unknown contract:" in stripped:
            return True

        if "Option(symbol=" in stripped and "tradingClass=" in stripped:
            return True

        # Ocultar líneas masivas de contratos de opciones individuales.
        # El resumen ejecutivo ya captura esta información.
        option_tokens = [
            " NAKED_PUT ",
            " COVERED_CALL ",
            " SHORT_PUT ",
            " SHORT_CALL ",
            " IRON_CONDOR ",
        ]

        if any(tok in stripped for tok in option_tokens):
            if " exp:" in stripped and (" decision:" in stripped or " cap:" in stripped or " quality:" in stripped):
                return True

        # Ocultar dumps largos de status si son demasiado técnicos
        if len(stripped) > 240 and (" underlying_source:" in stripped or " price_source:" in stripped):
            return True

        return False

    except Exception:
        return False

# ============================================================
# SUPER ENGINE BOLSA — V17.2 CONSOLE CAPTURE
# ============================================================

import builtins as _v17_builtins
import re as _v17_re

V17_ORIGINAL_PRINT = _v17_builtins.print

def v17_parse_console_line_for_summary(text):
    try:
        if not isinstance(text, str):
            text = str(text)

        if " decision:" not in text and " cap:" not in text:
            return None

        if " score:" not in text:
            return None

        parts = text.strip().split()
        if len(parts) < 2:
            return None

        ticker = parts[0]
        strategy = parts[1]

        def pick(pattern, default=None):
            m = _v17_re.search(pattern, text)
            return m.group(1) if m else default

        score = pick(r"score:([-+]?\d+\.?\d*)", 0)
        decision = pick(r"decision:([A-Z_]+)", None)
        cap = pick(r"cap:([A-Z_]+)", None)
        quality = pick(r"quality:([A-Z_]+)", "CONSOLE_CAPTURE")
        price = pick(r"price:([-+]?\d+\.?\d*)", None)
        mid = pick(r"mid:([-+]?\d+\.?\d*)", None)

        final_decision = decision or cap or "WAIT"

        row = {
            "ticker": ticker,
            "strategy": strategy,
            "decision": final_decision,
            "score": float(score) if score is not None else 0,
            "data_quality": quality,
            "source": "CONSOLE_CAPTURE",
        }

        if price is not None:
            row["price"] = price
        elif mid is not None:
            row["price"] = mid

        return row

    except Exception:
        return None


def v17_print(*args, **kwargs):
    try:
        text = " ".join(str(a) for a in args)

        # Primero capturamos para summary, aunque luego ocultemos la línea.
        for line in text.splitlines():
            row = v17_parse_console_line_for_summary(line)
            if row:
                try:
                    v17_store_row(row)
                except Exception:
                    pass

        # Después filtramos ruido visual de consola.
        visible_lines = []
        for line in text.splitlines():
            if not v17_should_hide_console_line(line):
                visible_lines.append(line)

        if not visible_lines and text.strip():
            return None

        if visible_lines and len(visible_lines) != len(text.splitlines()):
            return V17_ORIGINAL_PRINT("\n".join(visible_lines), **kwargs)

    except Exception:
        pass

    return V17_ORIGINAL_PRINT(*args, **kwargs)

if getattr(_v17_builtins.print, "__name__", "") != "v17_print":
    _v17_builtins.print = v17_print

# ============================================================
# SUPER ENGINE BOLSA — V17 OPERATIONAL DESK OUTPUT
# ============================================================

def v17_safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def v17_get(row, *keys, default=None):
    try:
        for k in keys:
            if isinstance(row, dict) and row.get(k) is not None:
                return row.get(k)
    except Exception:
        pass
    return default


def v17_collect_rows(obj, out=None, max_items=300):
    if out is None:
        out = []

    if len(out) >= max_items:
        return out

    try:
        if isinstance(obj, dict):
            keys = set(obj.keys())
            if (
                "ticker" in keys
                or "symbol" in keys
                or "decision" in keys
                or "final_decision" in keys
                or "strategy_decision" in keys
                or "score" in keys
                or "master_score" in keys
                or "position_class" in keys
                or "quality" in keys
                or "data_quality" in keys
            ):
                out.append(obj)

            for v in obj.values():
                if isinstance(v, (dict, list, tuple)):
                    v17_collect_rows(v, out, max_items)

        elif isinstance(obj, (list, tuple)):
            for item in obj:
                if isinstance(item, (dict, list, tuple)):
                    v17_collect_rows(item, out, max_items)
    except Exception:
        pass

    return out


def v17_score(row):
    return v17_safe_float(
        v17_get(
            row,
            "master_score",
            "priority_score",
            "score",
            "best_entry_score",
            "best_management_score",
            default=0,
        )
    )


def v17_decision(row):
    return str(
        v17_get(
            row,
            "final_action",
            "final_decision",
            "strategy_decision",
            "option_decision",
            "decision",
            "cap",
            default="WAIT",
        )
    )


def v17_ticker(row):
    return str(
        v17_get(
            row,
            "ticker",
            "symbol",
            "local_symbol",
            "option_symbol",
            "underlying",
            default="UNKNOWN",
        )
    )


def v17_strategy(row):
    return str(
        v17_get(
            row,
            "best_strategy",
            "strategy",
            "strategy_hint",
            "option_strategy_hint",
            "setup",
            "position_class",
            "asset_class",
            default="GENERAL",
        )
    )


def v17_quality(row):
    return str(
        v17_get(
            row,
            "data_quality",
            "quality",
            "price_source",
            "source",
            default="NO_QUALITY",
        )
    )


def v17_bucket(row):
    d = v17_decision(row).upper()
    q = v17_quality(row).upper()
    cap = str(v17_get(row, "execution_cap", "cap", default="")).upper()
    blockers = v17_get(row, "blockers", default=[])
    missing = v17_get(row, "missing_data", "entry_missing_data", default=[])

    if blockers and "RADAR_ONLY_MARKET_CLOSED" not in cap:
        return "BLOCKED"

    if "OPERAR" in d or "ENTRY_OPPORTUNITY" in d or d in ["BUY", "SELL", "TRADE"]:
        return "ENTRY"

    if "BLOCKED" in d or "BLOCKED" in cap:
        return "BLOCKED"

    if "RADAR" in d or "RADAR" in cap:
        return "RADAR"

    if "WAIT_FOR_GREEKS" in d or "WAIT_FOR_GREEKS" in cap or "NO_GREEKS" in q:
        return "WAIT_GREEKS"

    if missing:
        return "WAIT_DATA"

    return "WAIT"


def v17_format_row(row):
    price = v17_get(row, "price", "market_price", "latest_price", "last", "close", default=None)
    price_txt = f" | price:{price}" if price is not None else ""
    return (
        f"{v17_ticker(row)} | "
        f"{v17_strategy(row)} | "
        f"{v17_decision(row)} | "
        f"score:{v17_score(row):.1f}"
        f"{price_txt} | "
        f"{v17_quality(row)}"
    )


def v17_build_cycle_summary(local_vars):
    try:
        rows = []
        try:
            rows.extend(V17_SUMMARY_ROWS)
        except Exception:
            pass

        for name, value in local_vars.items():
            if name.startswith("__"):
                continue
            if isinstance(value, (dict, list, tuple)):
                rows.extend(v17_collect_rows(value))

        seen = set()
        unique = []

        for r in rows:
            if not isinstance(r, dict):
                continue

            key = (
                v17_ticker(r),
                v17_strategy(r),
                v17_decision(r),
                round(v17_score(r), 2),
                v17_quality(r),
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(r)

        buckets = {
            "ENTRY": [],
            "RADAR": [],
            "WAIT_GREEKS": [],
            "WAIT_DATA": [],
            "BLOCKED": [],
            "WAIT": [],
        }

        for r in unique:
            buckets.setdefault(v17_bucket(r), []).append(r)

        for k in buckets:
            buckets[k] = sorted(buckets[k], key=v17_score, reverse=True)[:8]

        top = (
            buckets["ENTRY"][:1]
            or buckets["RADAR"][:1]
            or buckets["BLOCKED"][:1]
            or buckets["WAIT_GREEKS"][:1]
            or buckets["WAIT_DATA"][:1]
            or buckets["WAIT"][:1]
        )

        lines = []
        lines.append("")
        lines.append("============================================================")
        lines.append("V17 OPERATIONAL DESK SUMMARY")
        lines.append("============================================================")
        lines.append(
            f"ENTRY:{len(buckets['ENTRY'])} | "
            f"RADAR:{len(buckets['RADAR'])} | "
            f"WAIT_GREEKS:{len(buckets['WAIT_GREEKS'])} | "
            f"WAIT_DATA:{len(buckets['WAIT_DATA'])} | "
            f"BLOCKED:{len(buckets['BLOCKED'])}"
        )
        lines.append("")

        if top:
            lines.append("NEXT BEST ACTION:")
            lines.append("  " + v17_format_row(top[0]))
            lines.append("")

        if buckets["ENTRY"]:
            lines.append("ENTRY CANDIDATES:")
            for r in buckets["ENTRY"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["RADAR"]:
            lines.append("RADAR / PREPARACION:")
            for r in buckets["RADAR"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["BLOCKED"]:
            lines.append("BLOCKED / NO OPERAR:")
            for r in buckets["BLOCKED"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["WAIT_GREEKS"] or buckets["WAIT_DATA"]:
            lines.append("FALTANTES DE DATOS:")
            for r in (buckets["WAIT_GREEKS"] + buckets["WAIT_DATA"])[:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        lines.append("============================================================")
        return "\n".join(lines)

    except Exception as e:
        return f"V17 summary unavailable: {e}"
print("SUPER ENGINE IBKR BRIDGE V18_1_REMOTE_SNAPSHOT_INGEST")
print("Market + Portfolio + Options + Strategy Commander")
print("IBKR ONLY + READY FOR TRADINGVIEW INTEGRATION")
print("Naked Put + Covered Call activos")
print("Decision safety locks enabled")
print("Robust stock price fallback enabled")
print("")


# === V26 AUTO PUBLISH CALL ===
try:
    _v26_print_remote_publish_status(extra_payload={'cycle': 'auto'})
except Exception as _v26_auto_e:
    print(f'V26 auto publish non-fatal error: {_v26_auto_e}')
while True:
    print("")
    print("=========================================")
    # V28.3 HOOK AFTER V26 REMOTE PUBLISH - FALLBACK
    try:
        _v283_publish_to_v28()
    except Exception as _v283_hook_error:
        print(f"V28.3 hook error: {_v283_hook_error}")
    print("NUEVO CICLO V18_1_REMOTE_SNAPSHOT_INGEST")
    print("=========================================")

    if ENABLE_MARKET_DATA:
        send_market_data()

    if ENABLE_PORTFOLIO_COMMANDER:
        send_positions()

    if ENABLE_OPTIONS_INTELLIGENCE:
        send_options_intelligence()

        try:
            print(v17_build_cycle_summary(locals()))
            try:
                v18_payload = v18_write_decision_snapshot(V17_SUMMARY_ROWS)
                v18_remote = v18_1_post_decision_snapshot(v18_payload)
                nba = v18_payload.get("next_best_action")
                if nba:
                    print("")
                    print("V18 DECISION API SNAPSHOT UPDATED")
                    print(f"NEXT: {nba.get('ticker')} | {nba.get('strategy')} | {nba.get('decision')} | can_operate:{nba.get('can_operate')}")
                try:
                    print(f"REMOTE INGEST: {v18_remote.get('posted')} | status:{v18_remote.get('status')} | url:{v18_remote.get('url', '')}")
                except Exception:
                    pass
                else:
                    print("")
                    print("V18 DECISION API SNAPSHOT UPDATED | No next_best_action")
            except Exception as e:
                print(f"V18 snapshot error: {e}")
        except Exception as e:
            print(f"V17 summary error: {e}")

    # Publish again after the cycle so V31 receives the fresh runtime data
    # generated by market, portfolio, and options intelligence.
    try:
        _v283_publish_to_v28()
    except Exception as _v283_post_cycle_error:
        print(f"V28.3 post-cycle hook error: {_v283_post_cycle_error}")

    print(f"Esperando {LOOP_SECONDS} segundos...")
    print("")
    time.sleep(LOOP_SECONDS)


# ============================================================
# V22.2 REMOTE SNAPSHOT SYNC — LOCAL BRIDGE POST TO RENDER
# ============================================================

import json as _v22_2_json
from pathlib import Path as _v22_2_Path
from datetime import datetime as _v22_2_datetime, timezone as _v22_2_timezone

try:
    import requests as _v22_2_requests
except Exception:
    _v22_2_requests = None

V22_2_REMOTE_BASE_URL = "https://trading-engine-p097.onrender.com"

def _v22_2_now_iso():
    return _v22_2_datetime.now(_v22_2_timezone.utc).isoformat()

def _v22_2_read_json_file(path):
    try:
        p = _v22_2_Path(path)
        if p.exists():
            return _v22_2_json.loads(p.read_text())
    except Exception:
        pass
    return None

def _v22_2_post_json(endpoint, payload, timeout=8):
    if _v22_2_requests is None:
        return {"ok": False, "status": "NO_REQUESTS_LIB", "url": endpoint}

    url = V22_2_REMOTE_BASE_URL.rstrip("/") + endpoint
    try:
        r = _v22_2_requests.post(url, json=payload, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:500]}
        return {
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "url": url,
            "body": body,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "POST_ERROR",
            "url": url,
            "error": str(e),
        }

def _v22_2_collect_candidate_files():
    return {
        "technical": [
            "runtime/technical_snapshot_by_ticker_safe.json",
            "runtime/technical_snapshot_by_ticker.json",
            "technical_snapshot_by_ticker_safe.json",
            "technical_snapshot_by_ticker.json",
        ],
        "decision": [
            "runtime/decision_desk_snapshot.json",
            "runtime/v18_decision_snapshot.json",
            "runtime/v18_decision_desk_snapshot.json",
            "decision_desk_snapshot.json",
            "decision_snapshot.json",
        ],
    }

def _v22_2_find_first_json(paths):
    for p in paths:
        data = _v22_2_read_json_file(p)
        if data:
            return p, data
    return None, None

def _v22_2_remote_sync_snapshots(extra_payload=None):
    files = _v22_2_collect_candidate_files()

    tech_path, tech_data = _v22_2_find_first_json(files["technical"])
    decision_path, decision_data = _v22_2_find_first_json(files["decision"])

    results = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "technical_sent": False,
        "decision_sent": False,
        "unified_sent": False,
        "responses": {},
    }

    if isinstance(tech_data, dict):
        # Caso A: store por ticker {"QQQ": {...}, "SPY": {...}}
        if any(isinstance(v, dict) for v in tech_data.values()):
            for ticker, snap in tech_data.items():
                if isinstance(snap, dict):
                    payload = {
                        "ticker": str(ticker).upper(),
                        "snapshot": snap,
                        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                        "local_path": tech_path,
                    }
                    resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
                    results["responses"][f"technical_{ticker}"] = resp
                    if resp.get("ok"):
                        results["technical_sent"] = True
        # Caso B: snapshot directo {"ticker":"QQQ", ...}
        elif tech_data.get("ticker"):
            payload = {
                "ticker": str(tech_data.get("ticker")).upper(),
                "snapshot": tech_data,
                "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                "local_path": tech_path,
            }
            resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
            results["responses"]["technical_single"] = resp
            if resp.get("ok"):
                results["technical_sent"] = True

    if isinstance(decision_data, dict):
        payload = dict(decision_data)
        payload["source"] = payload.get("source") or "IBKR_BRIDGE_V22_2_REMOTE_SYNC"
        payload["local_path"] = decision_path
        resp = _v22_2_post_json("/v22_2_ingest_decision_snapshot", payload)
        results["responses"]["decision"] = resp
        if resp.get("ok"):
            results["decision_sent"] = True

    unified_payload = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_available": bool(tech_data),
        "decision_available": bool(decision_data),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "extra_payload": extra_payload or {},
        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
    }
    resp = _v22_2_post_json("/v22_2_ingest_unified_snapshot", unified_payload)
    results["responses"]["unified"] = resp
    if resp.get("ok"):
        results["unified_sent"] = True

    return results

def v22_2_print_remote_sync_status(extra_payload=None):
    try:
        res = _v22_2_remote_sync_snapshots(extra_payload=extra_payload)
        print("")
        print("=== V22.2 REMOTE SNAPSHOT SYNC ===")
        print(f"technical_sent: {res.get('technical_sent')} | path: {res.get('technical_path')}")
        print(f"decision_sent: {res.get('decision_sent')} | path: {res.get('decision_path')}")
        print(f"unified_sent: {res.get('unified_sent')}")
        for k, v in (res.get("responses") or {}).items():
            print(f"{k}: ok={v.get('ok')} status={v.get('status')}")
        print("==================================")
        print("")
        return res
    except Exception as e:
        print(f"V22.2 remote sync error: {e}")
        return {"ok": False, "error": str(e)}



# ============================================================
# V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================
import os as _v28_os
import json as _v28_json_bridge
from datetime import datetime as _v28_bridge_datetime, timezone as _v28_bridge_timezone

try:
    import requests as _v28_requests
except Exception:
    _v28_requests = None

_V28_REMOTE_BASE_URL = _v28_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V28_REMOTE_INGEST_PATH = _v28_os.environ.get(
    "TRADING_ENGINE_INGEST_PATH",
    "/v31_ingest_snapshot"
)
if not _V28_REMOTE_INGEST_PATH.startswith("/"):
    _V28_REMOTE_INGEST_PATH = "/" + _V28_REMOTE_INGEST_PATH

_V28_REMOTE_INGEST_URL = _V28_REMOTE_BASE_URL + _V28_REMOTE_INGEST_PATH

def _v28_bridge_now():
    return _v28_bridge_datetime.now(_v28_bridge_timezone.utc).isoformat()

def _v28_bridge_json_safe(obj):
    try:
        _v28_json_bridge.dumps(obj)
        return obj
    except Exception:
        if isinstance(obj, dict):
            return {str(k): _v28_bridge_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_v28_bridge_json_safe(x) for x in obj]
        try:
            return float(obj)
        except Exception:
            return str(obj)

def _v28_bridge_collect_runtime_json():
    out = {}
    runtime = Path("runtime")
    try:
        for p in runtime.glob("*.json"):
            try:
                out[p.name] = _v28_json_bridge.loads(p.read_text())
            except Exception:
                pass
    except Exception:
        pass
    return out

def _v28_bridge_extract_options_rows(runtime_data):
    rows = []
    execution_fields = [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]

    def completeness_score(row):
        complete = sum(
            1
            for field in execution_fields
            if row.get(field) not in [None, "", "None"]
        )
        try:
            score = float(row.get("score") or 0)
        except Exception:
            score = 0.0
        return complete, score

    def add_from(x):
        if isinstance(x, list):
            for r in x:
                if isinstance(r, dict):
                    rows.append(dict(r))
        elif isinstance(x, dict):
            for k in ["options_rows", "rows", "top", "top_5", "sample_rows", "best_rows"]:
                v = x.get(k)
                if isinstance(v, list):
                    add_from(v)
            opt = x.get("options")
            if isinstance(opt, dict):
                add_from(opt)
            for k in ["best_row", "best", "next_best_action"]:
                v = x.get(k)
                if isinstance(v, dict):
                    rows.append(dict(v))

    for _name, data in runtime_data.items():
        add_from(data)

    best_by_key = {}
    for r in rows:
        ticker = str(r.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        r["ticker"] = ticker
        r["strategy"] = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        r["decision"] = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()
        r["score"] = r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score")
        r["price"] = r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        key = (r.get("ticker"), r.get("strategy"), r.get("decision"))
        current = best_by_key.get(key)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[key] = r
    return sorted(best_by_key.values(), key=completeness_score, reverse=True)

def _v28_bridge_extract_technical_snapshot(runtime_data):
    tech = {}

    def add_candidate(k, v):
        if not isinstance(v, dict):
            return
        ticker = str(v.get("ticker") or k or "").upper().strip()
        if not ticker:
            return
        # only accept objects that look technical
        looks = any(x in v for x in ["trend", "rsi", "adx", "vwap_position", "volume_relative", "support_near", "resistance_near", "score"])
        if looks:
            vv = dict(v)
            vv["ticker"] = ticker
            tech[ticker] = vv

    def walk(obj, forced_key=None):
        if isinstance(obj, dict):
            if forced_key:
                add_candidate(forced_key, obj)
            for k, v in obj.items():
                if isinstance(v, dict):
                    add_candidate(k, v)
                    walk(v, k)
                elif isinstance(v, list):
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for _name, data in runtime_data.items():
        walk(data)

    return tech

def _v28_bridge_market_snapshot():
    # Local IBKR bridge is source of truth for live cycle.
    return {
        "status": "REGULAR_OPTIONS_SESSION",
        "label": "Mercado abierto: opciones en ventana operable",
        "is_regular_market_open": True,
        "options_bidask_expected": True,
        "source": "IBKR_BRIDGE_V28_AUTO_PUBLISHER",
        "generated_at": _v28_bridge_now(),
    }

def _v28_publish_master_snapshot(extra_payload=None):
    if _v28_requests is None:
        print("V28 REMOTE MASTER SNAPSHOT NOT PUBLISHED | requests not available")
        return {"ok": False, "error": "requests_not_available"}

    runtime_data = _v28_bridge_collect_runtime_json()
    options_rows = _v28_bridge_extract_options_rows(runtime_data)
    technical_snapshot = _v28_bridge_extract_technical_snapshot(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_AUTO_PUBLISHER",
        "generated_at": _v28_bridge_now(),
        "options_rows": _v28_bridge_json_safe(options_rows),
        "technical_snapshot": _v28_bridge_json_safe(technical_snapshot),
        "market": _v28_bridge_market_snapshot(),
        "runtime_files_seen": sorted(list(runtime_data.keys())),
        "bridge_status": "PUBLISHED_FROM_LOCAL_IBKR",
    }

    if isinstance(extra_payload, dict):
        payload.update(extra_payload)

    try:
        resp = _v28_requests.post(_V28_REMOTE_INGEST_URL, json=payload, timeout=15)
        ok = 200 <= resp.status_code < 300
        print(
            "V31 REMOTE MASTER SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(options_rows)}"
            f" | technical:{len(technical_snapshot)}"
            f" | url:{_V28_REMOTE_INGEST_URL}"
        )
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "rows": len(options_rows),
            "technical": len(technical_snapshot),
            "url": _V28_REMOTE_INGEST_URL,
            "text": resp.text[:500],
        }
    except Exception as e:
        print(f"V28 REMOTE MASTER SNAPSHOT PUBLISH ERROR | {e}")
        return {"ok": False, "error": str(e), "url": _V28_REMOTE_INGEST_URL}

# ============================================================
# END V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================
