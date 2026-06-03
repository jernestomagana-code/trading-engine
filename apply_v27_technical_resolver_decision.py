from pathlib import Path

APP = Path("app/main.py")
s = APP.read_text()

backup = Path("app/main_backup_before_v27_technical_resolver_decision.py")
backup.write_text(s)

block = r'''

# ============================================================
# V27 TECHNICAL RESOLVER + UNIFIED DECISION QUALITY
# ============================================================
from pathlib import Path as _V27Path
from datetime import datetime as _V27DateTime, timezone as _V27Timezone
import json as _v27_json
import math as _v27_math
from fastapi.responses import HTMLResponse as _V27HTMLResponse

_V27_RUNTIME_DIR = _V27Path("runtime")
_V27_MASTER_FILE = _V27_RUNTIME_DIR / "v25_master_snapshot.json"
_V27_TECH_SAFE_FILE = _V27_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"
_V27_TECH_ALT_FILE = _V27_RUNTIME_DIR / "technical_snapshot_by_ticker.json"
_V27_DECISION_FILE = _V27_RUNTIME_DIR / "v27_last_decision.json"

_V27_ALLOWED_TICKERS = {
    "QQQ", "SPY", "NVDA", "TSLA", "META", "AAPL", "MSFT", "AMZN", "NFLX", "TLT", "IWM", "DIA", "AMD", "GOOGL", "GOOG"
}

_V27_REJECT_KEYS = {
    "NEXT_BEST_ACTION", "SUMMARY", "DASHBOARD", "SYSTEM_STATUS", "GPT_SUMMARY",
    "DECISION", "EXECUTIVE_CONCLUSION", "MARKET_HOURS", "URLS", "HEALTH"
}

def _v27_now():
    return _V27DateTime.now(_V27Timezone.utc).isoformat()

def _v27_safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, str) and not x.strip():
            return default
        v = float(x)
        if _v27_math.isnan(v) or _v27_math.isinf(v):
            return default
        return v
    except Exception:
        return default

def _v27_load_json_file(path):
    try:
        p = _V27Path(path)
        if not p.exists():
            return None
        return _v27_json.loads(p.read_text())
    except Exception:
        return None

def _v27_save_json_file(path, payload):
    try:
        p = _V27Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_v27_json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return True
    except Exception:
        return False

def _v27_normalize_ticker(t):
    if t is None:
        return None
    t = str(t).upper().strip()
    t = t.replace("/", "").replace("\\", "")
    t = t.replace(":", "").replace(" ", "")
    if not t:
        return None
    if t in _V27_REJECT_KEYS:
        return None
    if len(t) > 8:
        return None
    if not all(ch.isalnum() or ch in {".", "-"} for ch in t):
        return None
    return t

def _v27_is_valid_ticker(t):
    t = _v27_normalize_ticker(t)
    if not t:
        return False
    if t in _V27_REJECT_KEYS:
        return False
    if t in _V27_ALLOWED_TICKERS:
        return True
    # Allow normal equity/ETF tickers but reject obvious metadata words.
    if 1 <= len(t) <= 6 and t.isalpha():
        return True
    return False

def _v27_extract_technical_candidate(obj):
    if not isinstance(obj, dict):
        return None

    raw_ticker = obj.get("ticker") or obj.get("symbol") or obj.get("underlying") or obj.get("asset")
    ticker = _v27_normalize_ticker(raw_ticker)
    if not _v27_is_valid_ticker(ticker):
        return None

    trend = str(obj.get("trend") or obj.get("bias") or obj.get("technical_bias") or "UNKNOWN").upper().strip()
    if trend in {"UP", "BULL", "BULLISH_TREND"}:
        trend = "BULLISH"
    elif trend in {"DOWN", "BEAR", "BEARISH_TREND"}:
        trend = "BEARISH"
    elif trend in {"SIDEWAYS", "FLAT", "RANGE"}:
        trend = "NEUTRAL"

    score = _v27_safe_float(obj.get("score") or obj.get("technical_score"), None)
    rsi = _v27_safe_float(obj.get("rsi"), None)
    adx = _v27_safe_float(obj.get("adx"), None)
    volume_relative = _v27_safe_float(obj.get("volume_relative") or obj.get("relative_volume"), None)

    vwap_position = str(obj.get("vwap_position") or obj.get("vwap") or "UNKNOWN").lower().strip()
    support_near = bool(obj.get("support_near", False))
    resistance_near = bool(obj.get("resistance_near", False))
    range_breakout = bool(obj.get("range_breakout", False))
    event_risk = bool(obj.get("event_risk", False))

    # Minimum shape: must have ticker and at least one real technical field.
    technical_fields_present = any([
        trend != "UNKNOWN",
        score is not None,
        rsi is not None,
        adx is not None,
        vwap_position not in {"", "unknown", "none"},
        volume_relative is not None,
        support_near,
        resistance_near,
        range_breakout,
    ])

    if not technical_fields_present:
        return None

    return {
        "ticker": ticker,
        "trend": trend,
        "bias": trend,
        "score": score,
        "rsi": rsi,
        "adx": adx,
        "vwap_position": vwap_position,
        "volume_relative": volume_relative,
        "support_near": support_near,
        "resistance_near": resistance_near,
        "range_breakout": range_breakout,
        "event_risk": event_risk,
        "source": obj.get("source") or "V27_TECHNICAL_RESOLVER",
        "received_at": obj.get("received_at") or obj.get("generated_at") or _v27_now(),
        "raw": obj,
    }

def _v27_flatten_possible_technical_objects(data):
    out = []

    def walk(x):
        if isinstance(x, dict):
            cand = _v27_extract_technical_candidate(x)
            if cand:
                out.append(cand)

            # Common structures: by ticker, snapshot, technical_snapshot, technical.
            for k, v in x.items():
                nk = _v27_normalize_ticker(k)
                if isinstance(v, dict) and _v27_is_valid_ticker(nk):
                    merged = dict(v)
                    merged.setdefault("ticker", nk)
                    cand2 = _v27_extract_technical_candidate(merged)
                    if cand2:
                        out.append(cand2)
                if isinstance(v, (dict, list)):
                    walk(v)

        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(data)
    return out

def _v27_load_technical_map():
    sources = []
    for path in [_V27_TECH_SAFE_FILE, _V27_TECH_ALT_FILE, _V27_MASTER_FILE]:
        data = _v27_load_json_file(path)
        if data is not None:
            sources.append((str(path), data))

    tech_map = {}
    diagnostics = []

    for path, data in sources:
        candidates = _v27_flatten_possible_technical_objects(data)
        diagnostics.append({
            "path": path,
            "candidates_found": len(candidates),
            "tickers": sorted(list({c["ticker"] for c in candidates if c.get("ticker")})),
        })
        for cand in candidates:
            t = cand.get("ticker")
            if _v27_is_valid_ticker(t):
                existing = tech_map.get(t)
                # Prefer candidate with score and more fields.
                current_quality = sum(1 for k in ["score", "rsi", "adx", "vwap_position", "volume_relative"] if cand.get(k) not in [None, "", "UNKNOWN"])
                previous_quality = 0
                if existing:
                    previous_quality = sum(1 for k in ["score", "rsi", "adx", "vwap_position", "volume_relative"] if existing.get(k) not in [None, "", "UNKNOWN"])
                if not existing or current_quality >= previous_quality:
                    tech_map[t] = cand

    return tech_map, diagnostics

def _v27_get_master_snapshot():
    master = _v27_load_json_file(_V27_MASTER_FILE)
    if isinstance(master, dict):
        return master
    return {}

def _v27_extract_option_rows(master):
    rows = []
    if not isinstance(master, dict):
        return rows

    possible_keys = ["options_rows", "rows", "top", "sample_rows", "best_rows"]
    for key in possible_keys:
        val = master.get(key)
        if isinstance(val, list):
            rows.extend([x for x in val if isinstance(x, dict)])

    # Some previous versions store rows nested under options.
    options = master.get("options")
    if isinstance(options, dict):
        for key in possible_keys:
            val = options.get(key)
            if isinstance(val, list):
                rows.extend([x for x in val if isinstance(x, dict)])

    # Deduplicate lightly.
    cleaned = []
    seen = set()
    for r in rows:
        t = _v27_normalize_ticker(r.get("ticker"))
        strategy = str(r.get("strategy") or r.get("strategy_hint") or "").upper()
        price = str(r.get("price") or r.get("premium") or r.get("option_price") or "")
        decision = str(r.get("decision") or r.get("final_decision") or "").upper()
        key = (t, strategy, price, decision)
        if t and key not in seen:
            seen.add(key)
            rr = dict(r)
            rr["ticker"] = t
            cleaned.append(rr)
    return cleaned

def _v27_market_hours(master):
    mh = {}
    if isinstance(master, dict):
        mh = master.get("market_hours") or {}
        if isinstance(mh, dict) and "market_hours" in mh and isinstance(mh.get("market_hours"), dict):
            mh = mh.get("market_hours")
    if not isinstance(mh, dict):
        mh = {}
    label = mh.get("label") or mh.get("market_hours_label") or "UNKNOWN"
    is_open = bool(mh.get("is_regular_market_open", False) or mh.get("is_open", False))
    options_bidask_expected = bool(mh.get("options_bidask_expected", False))
    return {
        "label": label,
        "is_regular_market_open": is_open,
        "options_bidask_expected": options_bidask_expected,
        "raw": mh,
    }

def _v27_strategy_matches_technical(strategy, technical):
    strategy = str(strategy or "").upper()
    trend = str((technical or {}).get("trend") or (technical or {}).get("bias") or "UNKNOWN").upper()

    if strategy in {"NAKED_PUT", "SHORT_PUT", "BULL_PUT_SPREAD"}:
        return trend in {"BULLISH", "NEUTRAL"}
    if strategy in {"COVERED_CALL", "SHORT_CALL", "BEAR_CALL_SPREAD"}:
        return trend in {"BEARISH", "NEUTRAL", "BULLISH"}  # covered call can be management/neutral-income
    if strategy in {"IRON_CONDOR"}:
        return trend in {"NEUTRAL", "RANGE", "SIDEWAYS"}
    return False

def _v27_technical_confirmed_for_strategy(strategy, technical):
    if not technical:
        return False, "NO_TECHNICAL_SNAPSHOT"

    trend = str(technical.get("trend") or "UNKNOWN").upper()
    score = _v27_safe_float(technical.get("score"), None)
    rsi = _v27_safe_float(technical.get("rsi"), None)
    adx = _v27_safe_float(technical.get("adx"), None)
    event_risk = bool(technical.get("event_risk", False))

    if event_risk:
        return False, "TECHNICAL_EVENT_RISK"

    if trend == "UNKNOWN":
        return False, "TECHNICAL_TREND_UNKNOWN"

    if score is not None and score < 60:
        return False, "TECHNICAL_SCORE_LOW"

    if rsi is not None and (rsi < 35 or rsi > 75):
        return False, "TECHNICAL_RSI_EXTREME"

    if adx is not None and adx < 10:
        return False, "TECHNICAL_ADX_WEAK"

    if not _v27_strategy_matches_technical(strategy, technical):
        return False, "TECHNICAL_STRATEGY_MISMATCH"

    return True, "TECHNICAL_CONFIRMED"

def _v27_row_operable(row):
    decision = str(row.get("decision") or row.get("final_decision") or "").upper()
    can_operate = bool(row.get("can_operate", False))
    quality = str(row.get("data_quality") or row.get("quality") or "").upper()
    missing = row.get("missing_confirmations") or row.get("missing_data") or []
    if missing is None:
        missing = []
    if isinstance(missing, str):
        missing = [missing]

    has_full_greeks = "FULL_WITH_GREEKS" in quality or "WITH_GREEKS" in quality
    entry_like = decision in {"ENTRY", "OPERAR", "ENTRY_READY", "BUY", "SELL", "RADAR"} or can_operate

    if can_operate and has_full_greeks and not missing:
        return True, "OPTIONS_CONFIRMED"
    if entry_like and has_full_greeks and not missing:
        return True, "OPTIONS_CONFIRMED"
    if not has_full_greeks:
        return False, "WAIT_OPTIONS_GREEKS"
    if missing:
        return False, "WAIT_OPTIONS_CONFIRMATIONS"
    return False, "WAIT_OPTIONS_DATA"

def _v27_score_row(row):
    score = _v27_safe_float(row.get("score") or row.get("combined_score") or row.get("master_score"), 0) or 0
    price = _v27_safe_float(row.get("price") or row.get("premium") or row.get("option_price"), 0) or 0
    can_operate = 1 if row.get("can_operate") else 0
    quality_bonus = 10 if "FULL_WITH_GREEKS" in str(row.get("data_quality") or "").upper() else 0
    return score + quality_bonus + can_operate * 25 + min(price, 20) * 0.1

def _v27_choose_best_option_row(ticker, rows):
    ticker = _v27_normalize_ticker(ticker)
    filtered = [r for r in rows if _v27_normalize_ticker(r.get("ticker")) == ticker]
    if not filtered:
        return None
    return sorted(filtered, key=_v27_score_row, reverse=True)[0]

def _v27_decide_for_ticker(ticker):
    ticker = _v27_normalize_ticker(ticker)
    master = _v27_get_master_snapshot()
    rows = _v27_extract_option_rows(master)
    tech_map, tech_diag = _v27_load_technical_map()
    market = _v27_market_hours(master)

    best_row = _v27_choose_best_option_row(ticker, rows)
    technical = tech_map.get(ticker)

    if not best_row and not technical:
        result = {
            "engine": "V27_TECHNICAL_RESOLVER_DECISION",
            "generated_at": _v27_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles.",
            "executive_summary": f"{ticker}: no hay datos suficientes para evaluar operación.",
            "strategy": "UNKNOWN",
            "technical_fit": "NO_TECHNICAL",
            "technical": technical or {},
            "best_row": best_row or {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "market": market,
            "diagnostics": {
                "technical_sources": tech_diag,
                "technical_tickers": sorted(list(tech_map.keys())),
                "master_snapshot_available": bool(master),
            },
        }
        _v27_save_json_file(_V27_DECISION_FILE, result)
        return result

    if not best_row:
        result = {
            "engine": "V27_TECHNICAL_RESOLVER_DECISION",
            "generated_at": _v27_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "action": f"{ticker}: técnico disponible, pero falta oportunidad de opciones.",
            "executive_summary": f"{ticker}: técnico disponible, pero no hay fila de opciones operable.",
            "strategy": "UNKNOWN",
            "technical_fit": "TECHNICAL_AVAILABLE",
            "technical": technical or {},
            "best_row": {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "market": market,
            "diagnostics": {
                "technical_sources": tech_diag,
                "technical_tickers": sorted(list(tech_map.keys())),
                "master_snapshot_available": bool(master),
            },
        }
        _v27_save_json_file(_V27_DECISION_FILE, result)
        return result

    strategy = str(best_row.get("strategy") or best_row.get("strategy_hint") or "UNKNOWN").upper()
    option_ok, option_reason = _v27_row_operable(best_row)
    technical_ok, technical_reason = _v27_technical_confirmed_for_strategy(strategy, technical)

    market_open = bool(market.get("is_regular_market_open"))
    bidask_expected = bool(market.get("options_bidask_expected"))
    market_ok = market_open and bidask_expected

    if option_ok and technical_ok and market_ok:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        severity = "green"
        blocker = None
        action = f"{ticker}: posible entrada. Validar tamaño, spread, liquidez y riesgo final antes de ejecutar."
    elif option_ok and technical_ok and not market_ok:
        final_state = "WAIT_MARKET_OPEN"
        decision = "WAIT_MARKET_OPEN"
        severity = "gray"
        blocker = "MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE"
        action = f"{ticker}: oportunidad válida, pero esperar ventana confiable de mercado/opciones."
    elif option_ok and not technical_ok:
        final_state = "WAIT_TECHNICAL_CONFIRMATION"
        decision = "WAIT_TECHNICAL_CONFIRMATION"
        severity = "yellow"
        blocker = technical_reason
        action = f"{ticker}: opciones operables, pero falta confirmación técnica para {strategy}."
    elif not option_ok and technical_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        severity = "yellow"
        blocker = option_reason
        action = f"{ticker}: técnico confirmado, pero faltan datos/confirmaciones de opciones."
    else:
        final_state = "WAIT_DATA_CONFIRMATION"
        decision = "WAIT_DATA_CONFIRMATION"
        severity = "yellow"
        blocker = f"{option_reason}+{technical_reason}"
        action = f"{ticker}: faltan confirmaciones técnicas y/o de opciones."

    tech_score = None if not technical else technical.get("score")
    opt_score = best_row.get("score") or best_row.get("combined_score") or best_row.get("master_score")
    executive_summary = (
        f"{ticker}: estado {final_state}. Estrategia sugerida/observada: {strategy}. "
        f"Opciones: {option_reason}. Técnico: {technical_reason}. "
        f"Sesgo técnico: {(technical or {}).get('trend', 'UNKNOWN')}. "
        f"Score opciones: {opt_score}. Score técnico: {tech_score}. "
        f"Acción: {action}"
    )

    result = {
        "engine": "V27_TECHNICAL_RESOLVER_DECISION",
        "generated_at": _v27_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": final_state == "ENTRY_READY",
        "severity": severity,
        "main_blocker": blocker,
        "action": action,
        "executive_summary": executive_summary,
        "strategy": strategy,
        "technical_fit": technical_reason,
        "options_fit": option_reason,
        "technical": technical or {},
        "technical_score": tech_score,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "options_score": opt_score,
        "best_row": best_row,
        "rows_found_for_ticker": len([r for r in rows if _v27_normalize_ticker(r.get("ticker")) == ticker]),
        "total_rows_found": len(rows),
        "market": market,
        "diagnostics": {
            "technical_sources": tech_diag,
            "technical_tickers": sorted(list(tech_map.keys())),
            "master_snapshot_available": bool(master),
            "technical_available": bool(technical),
            "options_available": bool(best_row),
        },
    }
    _v27_save_json_file(_V27_DECISION_FILE, result)
    return result

def _v27_html_escape(x):
    import html
    return html.escape("" if x is None else str(x))

def _v27_badge_color(state):
    state = str(state or "").upper()
    if state == "ENTRY_READY":
        return "#16a34a"
    if "WAIT_TECHNICAL" in state:
        return "#f59e0b"
    if "WAIT_OPTIONS" in state:
        return "#f97316"
    if "WAIT_MARKET" in state:
        return "#64748b"
    if "BLOCKED" in state or "NO_DATA" in state:
        return "#dc2626"
    return "#64748b"

def _v27_dashboard_html(tickers=None):
    if not tickers:
        tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v27_decide_for_ticker(t) for t in tickers]
    entry_count = sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY")
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL_CONFIRMATION")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    no_data = sum(1 for d in decisions if d.get("final_state") == "NO_DATA")

    rows = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v27_badge_color(state)
        ticker = d.get("ticker")
        rows += f"""
        <tr>
          <td><a href="/v27_trade_decision/{_v27_html_escape(ticker)}">{_v27_html_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v27_html_escape(state)}</span></td>
          <td>{_v27_html_escape(d.get("strategy"))}</td>
          <td>{_v27_html_escape(d.get("technical_bias"))}</td>
          <td>{_v27_html_escape(d.get("technical_score"))}</td>
          <td>{_v27_html_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v27_html_escape(d.get("main_blocker"))}</td>
          <td>{_v27_html_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V27 Trading Decision Dashboard</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:34px; margin:0 0 22px; }}
        .hero {{
          background:#0f172a;
          color:white;
          padding:34px;
          border-radius:24px;
          margin-bottom:28px;
          box-shadow:0 20px 50px rgba(15,23,42,.12);
        }}
        .hero h2 {{ margin:0 0 12px; font-size:28px; }}
        .cards {{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:16px;
          margin-bottom:24px;
        }}
        .card {{
          background:white;
          border-radius:16px;
          padding:20px;
          box-shadow:0 12px 30px rgba(15,23,42,.08);
        }}
        .card .label {{ color:#64748b; font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; }}
        .card .value {{ font-size:32px; font-weight:800; margin-top:8px; }}
        table {{
          width:100%;
          border-collapse:collapse;
          background:white;
          border-radius:18px;
          overflow:hidden;
          box-shadow:0 16px 40px rgba(15,23,42,.08);
        }}
        th,td {{
          text-align:left;
          padding:14px 16px;
          border-bottom:1px solid #e5e7eb;
          font-size:14px;
          vertical-align:top;
        }}
        th {{
          color:#64748b;
          text-transform:uppercase;
          font-size:12px;
          letter-spacing:.08em;
        }}
        .badge {{
          display:inline-block;
          color:white;
          padding:7px 11px;
          border-radius:999px;
          font-size:12px;
          font-weight:800;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V27 — Technical Resolver + Unified Decision Dashboard</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Consolida técnico real + opciones + mercado para evitar entradas sin confirmación crítica.</p>
        <p>Generado: {_v27_html_escape(_v27_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry_count}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">No Data</div><div class="value">{no_data}</div></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Sesgo técnico</th>
            <th>Score técnico</th>
            <th>Score opciones</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v27_system_status · /v27_trade_decision/QQQ · /v27_dashboard · /v27_technical_resolver
      </div>
    </body>
    </html>
    """
    return html

@app.get("/v27_technical_resolver")
async def v27_technical_resolver():
    tech_map, diagnostics = _v27_load_technical_map()
    return {
        "engine": "V27_TECHNICAL_RESOLVER",
        "generated_at": _v27_now(),
        "status": "OK",
        "technical_available": bool(tech_map),
        "technical_tickers": sorted(list(tech_map.keys())),
        "technical_count": len(tech_map),
        "technical": tech_map,
        "diagnostics": diagnostics,
        "rejected_keywords": sorted(list(_V27_REJECT_KEYS)),
    }

@app.get("/v27_system_status")
async def v27_system_status():
    master = _v27_get_master_snapshot()
    rows = _v27_extract_option_rows(master)
    tech_map, tech_diag = _v27_load_technical_map()
    market = _v27_market_hours(master)
    detected = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(tech_map.keys()))))

    return {
        "engine": "V27_TECHNICAL_RESOLVER_DECISION",
        "generated_at": _v27_now(),
        "status": "OK",
        "master_snapshot_available": bool(master),
        "master_file": str(_V27_MASTER_FILE),
        "options_rows_found": len(rows),
        "technical_available": bool(tech_map),
        "technical_tickers": sorted(list(tech_map.keys())),
        "tickers_detected": detected,
        "market": market,
        "endpoints": {
            "technical_resolver": "/v27_technical_resolver",
            "trade_decision_example": "/v27_trade_decision/QQQ",
            "dashboard": "/v27_dashboard",
            "dashboard_ticker_example": "/v27_dashboard/QQQ",
        },
        "diagnostics": {
            "technical_sources": tech_diag,
        },
    }

@app.get("/v27_trade_decision/{ticker}")
async def v27_trade_decision(ticker: str):
    return _v27_decide_for_ticker(ticker)

@app.get("/gpt_v27_trade_decision/{ticker}")
async def gpt_v27_trade_decision(ticker: str):
    d = _v27_decide_for_ticker(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "options_score": d.get("options_score"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital y tolerancia de riesgo.",
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v27_dashboard", response_class=_V27HTMLResponse)
async def v27_dashboard():
    return _v27_dashboard_html()

@app.get("/v27_dashboard/{ticker}", response_class=_V27HTMLResponse)
async def v27_dashboard_ticker(ticker: str):
    return _v27_dashboard_html([ticker])

# ============================================================
# END V27 TECHNICAL RESOLVER + UNIFIED DECISION QUALITY
# ============================================================
'''

marker = "# ============================================================\n# V27 TECHNICAL RESOLVER + UNIFIED DECISION QUALITY\n# ============================================================"

if marker in s:
    print("V27 block already exists. No duplicate inserted.")
else:
    s = s.rstrip() + "\n\n" + block + "\n"
    APP.write_text(s)
    print("V27 technical resolver + unified decision patch applied.")

