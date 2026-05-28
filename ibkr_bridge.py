from ib_insync import *
import requests
import time
import math
import logging
from datetime import datetime, timezone
import nest_asyncio

nest_asyncio.apply()

# ============================================================
# SUPER ENGINE BOLSA — IBKR BRIDGE V16_INCREMENTAL
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
            "source": "IBKR_REALTIME_V16_INCREMENTAL",
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
            "source": "IBKR_REALTIME_V16_INCREMENTAL",
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
            "source": "IBKR_HISTORICAL_V16_INCREMENTAL",
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
    print("\n=== MARKET DATA V16_INCREMENTAL ===\n")

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
    print("\n=== PORTFOLIO COMMANDER V16_INCREMENTAL ===\n")

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
            genericTickList="106",
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
            "greeks": greeks,
            "data_quality": data_quality
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
            "greeks": {
                "iv": None,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None
            },
            "data_quality": "OPTION_MARKET_DATA_ERROR",
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


def score_option_candidate(strategy, option_type, strike, stock_price, dte, greeks, mid, data_quality, spread_pct):
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
    print("\n=== OPTIONS INTELLIGENCE V16_INCREMENTAL ===\n")

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
                    greeks = option_data.get("greeks")
                    data_quality = option_data.get("data_quality")

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

                    tv_context = tradingview_context_stub(symbol)

                    payload = {
                        "ticker": symbol,
                        "timeframe": "options",
                        "setup": f"IBKR_{strategy}_V15",
                        "trend": "",
                        "score": score,
                        "price": stock_price,
                        "underlying_price_source": snap.get("price_source"),
                        "source": "IBKR_OPTIONS_V16_INCREMENTAL",
                        "asset_class": "OPTION",
                        "engine_layer": "IBKR_OPTIONS_INTELLIGENCE",
                        "integration_ready_for_tradingview": True,
                        "data_quality": data_quality,
                        "decision_cap": decision_cap,
                        "option_symbol": contract.localSymbol,
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
                        "implied_volatility": greeks["iv"],
                        "delta": greeks["delta"],
                        "gamma": greeks["gamma"],
                        "theta": greeks["theta"],
                        "vega": greeks["vega"],
                        "moneyness_pct": safe_round(
                            (contract.strike / stock_price - 1) * 100,
                            2
                        ),
                        "received_at_bridge": now_iso(),
                        **tv_context
                    }

                    status = post(payload)

                    print(
                        f"{symbol} {strategy} "
                        f"{contract.strike} exp:{contract.lastTradeDateOrContractMonth} "
                        f"mid:{mid} bid:{bid} ask:{ask} spread:{spread_pct} "
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
        clientId=CLIENT_ID
    )

    print("IBKR conectado correctamente")

except Exception as e:
    print("ERROR conectando IBKR:")
    print(e)
    raise SystemExit


set_market_data_type()

print("")
print("SUPER ENGINE IBKR BRIDGE V16_INCREMENTAL")
print("Market + Portfolio + Options + Strategy Commander")
print("IBKR ONLY + READY FOR TRADINGVIEW INTEGRATION")
print("Naked Put + Covered Call activos")
print("Decision safety locks enabled")
print("Robust stock price fallback enabled")
print("")

while True:
    print("")
    print("=========================================")
    print("NUEVO CICLO V16_INCREMENTAL")
    print("=========================================")

    if ENABLE_MARKET_DATA:
        send_market_data()

    if ENABLE_PORTFOLIO_COMMANDER:
        send_positions()

    if ENABLE_OPTIONS_INTELLIGENCE:
        send_options_intelligence()

    print("")
    print(f"Esperando {LOOP_SECONDS} segundos...")
    print("")

    time.sleep(LOOP_SECONDS)
