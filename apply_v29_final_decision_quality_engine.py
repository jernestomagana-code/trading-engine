from pathlib import Path

APP = Path("app/main.py")
s = APP.read_text()

Path("app/main_backup_before_v29_final_decision_quality_engine.py").write_text(s)

block = r'''
# ============================================================
# V29 FINAL DECISION QUALITY ENGINE
# ============================================================

from fastapi.responses import HTMLResponse as _V29HTMLResponse
from pathlib import Path as _V29Path
from datetime import datetime as _V29Datetime, timezone as _V29Timezone
import json as _v29_json
import math as _v29_math
import html as _v29_html

_V29_RUNTIME_DIR = _V29Path("runtime")
_V29_MASTER_FILES = [
    "v28_master_snapshot.json",
    "v25_master_snapshot.json",
    "v22_2_unified_remote_snapshot.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
]

_V29_DEFAULT_TICKERS = ["QQQ", "SPY", "NVDA", "TSLA", "META", "NFLX", "TLT", "AAPL", "AMZN", "MSFT"]

_V29_MAX_SPREAD_PCT = 18.0
_V29_MAX_ABS_SPREAD = 0.35
_V29_MIN_BID = 0.05
_V29_MIN_ASK = 0.05
_V29_MIN_OPTION_SCORE = 70
_V29_MIN_TECH_SCORE = 65


def _v29_now():
    return _V29Datetime.now(_V29Timezone.utc).isoformat()


def _v29_safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, str) and not x.strip():
            return default
        val = float(x)
        if _v29_math.isnan(val) or _v29_math.isinf(val):
            return default
        return val
    except Exception:
        return default


def _v29_safe_upper(x, default="UNKNOWN"):
    try:
        if x is None:
            return default
        txt = str(x).strip()
        return txt.upper() if txt else default
    except Exception:
        return default


def _v29_load_json_file(path):
    try:
        p = _V29Path(path)
        if not p.exists():
            return None
        return _v29_json.loads(p.read_text())
    except Exception:
        return None


def _v29_discover_master_snapshot():
    candidates = []

    for name in _V29_MASTER_FILES:
        p = _V29_RUNTIME_DIR / name
        if p.exists():
            candidates.append(p)

    if _V29_RUNTIME_DIR.exists():
        for p in _V29_RUNTIME_DIR.glob("*.json"):
            if p not in candidates:
                candidates.append(p)

    best = None
    best_score = -1

    for p in candidates:
        data = _v29_load_json_file(p)
        if not isinstance(data, dict):
            continue

        rows = _v29_extract_options_rows_from_obj(data)
        tech = _v29_extract_technical_from_obj(data)
        score = len(rows) * 5 + len(tech) * 3

        # Preferir explícitamente master snapshots recientes
        if "v28_master_snapshot" in p.name:
            score += 500
        if "v25_master_snapshot" in p.name:
            score += 250

        if score > best_score:
            best_score = score
            best = {
                "path": str(p),
                "data": data,
                "rows": rows,
                "technical": tech,
                "score": score,
            }

    if best is None:
        return {
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }

    return best


def _v29_extract_options_rows_from_obj(obj):
    rows = []

    def scan(x):
        if isinstance(x, dict):
            direct_lists = [
                "options_rows",
                "rows",
                "sample_rows",
                "best_rows",
                "entry_candidates",
                "radar_candidates",
                "top",
                "top_5",
                "candidates",
            ]

            for key in direct_lists:
                v = x.get(key)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            rows.append(dict(item))

            ticker = _v29_safe_upper(x.get("ticker") or x.get("symbol"), "")
            strategy = x.get("strategy") or x.get("strategy_hint") or x.get("best_strategy")
            decision = x.get("decision") or x.get("final_decision") or x.get("state")
            quality = x.get("data_quality") or x.get("quality")

            option_like = False
            if ticker and strategy:
                option_like = True
            if ticker and any(k in x for k in ["bid", "ask", "strike", "delta", "expiration", "dte", "mid", "price"]):
                option_like = True
            if ticker and quality:
                option_like = True
            if ticker and decision and any(word in _v29_safe_upper(strategy, "") for word in ["PUT", "CALL", "CONDOR"]):
                option_like = True

            if option_like:
                rows.append(dict(x))

            for v in x.values():
                if isinstance(v, (dict, list)):
                    scan(v)

        elif isinstance(x, list):
            for item in x:
                scan(item)

    scan(obj)

    cleaned = []
    seen = set()

    for r in rows:
        ticker = _v29_safe_upper(r.get("ticker") or r.get("symbol"), "")
        if not ticker:
            continue

        strategy = _v29_safe_upper(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy"), "UNKNOWN")
        decision = _v29_safe_upper(r.get("decision") or r.get("final_decision") or r.get("state"), "RADAR")

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = _v29_safe_float(
            r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"),
            0
        )

        r["price"] = _v29_safe_float(
            r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"),
            None
        )

        r["bid"] = _v29_safe_float(r.get("bid") or r.get("option_bid"), None)
        r["ask"] = _v29_safe_float(r.get("ask") or r.get("option_ask"), None)
        r["mid"] = _v29_safe_float(r.get("mid") or r.get("mark") or r.get("price"), None)
        r["delta"] = _v29_safe_float(r.get("delta"), None)
        r["strike"] = _v29_safe_float(r.get("strike"), None)
        r["dte"] = _v29_safe_float(r.get("dte"), None)
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"

        key = (
            ticker,
            strategy,
            decision,
            str(r.get("strike")),
            str(r.get("expiration")),
            str(r.get("price")),
            str(r.get("bid")),
            str(r.get("ask")),
        )

        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned


def _v29_extract_technical_from_obj(obj):
    tech = {}

    def scan(x, parent_key=None):
        if isinstance(x, dict):
            ticker = _v29_safe_upper(x.get("ticker") or x.get("symbol") or parent_key, "")

            looks_technical = any(k in x for k in [
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
                "score",
            ])

            if ticker and looks_technical:
                item = dict(x)
                item["ticker"] = ticker
                item["trend"] = _v29_safe_upper(
                    item.get("trend") or item.get("bias") or item.get("technical_bias"),
                    "UNKNOWN"
                )
                item["score"] = _v29_safe_float(item.get("technical_score") or item.get("score"), None)
                tech[ticker] = item

            for k, v in x.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(x, list):
            for item in x:
                scan(item, parent_key)

    scan(obj)
    return tech


def _v29_spread_metrics(row):
    bid = _v29_safe_float(row.get("bid"), None)
    ask = _v29_safe_float(row.get("ask"), None)

    if bid is None or ask is None:
        return None, None, None

    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None, None

    spread = round(ask - bid, 4)
    mid = round((ask + bid) / 2, 4)

    if mid <= 0:
        return spread, mid, None

    spread_pct = round((spread / mid) * 100, 2)
    return spread, mid, spread_pct


def _v29_quality_gate(row):
    missing = []

    bid = _v29_safe_float(row.get("bid"), None)
    ask = _v29_safe_float(row.get("ask"), None)
    price = _v29_safe_float(row.get("price"), None)
    score = _v29_safe_float(row.get("score"), 0)
    delta = _v29_safe_float(row.get("delta"), None)
    strike = _v29_safe_float(row.get("strike"), None)
    dte = _v29_safe_float(row.get("dte"), None)

    spread, mid, spread_pct = _v29_spread_metrics(row)

    if bid is None or bid < _V29_MIN_BID:
        missing.append("bid")
    if ask is None or ask < _V29_MIN_ASK:
        missing.append("ask")
    if spread is None:
        missing.append("spread")
    if spread_pct is None:
        missing.append("spread_pct")
    if strike is None:
        missing.append("strike")
    if dte is None:
        missing.append("dte")
    if delta is None:
        missing.append("delta")
    if price is None and mid is None:
        missing.append("price_or_mid")
    if score < _V29_MIN_OPTION_SCORE:
        missing.append("option_score")

    spread_ok = False
    if spread is not None and spread_pct is not None:
        spread_ok = spread <= _V29_MAX_ABS_SPREAD or spread_pct <= _V29_MAX_SPREAD_PCT
        if not spread_ok:
            missing.append("spread_too_wide")

    executable = len(missing) == 0

    quality = "EXECUTABLE" if executable else "NOT_EXECUTABLE"

    return {
        "executable": executable,
        "quality": quality,
        "missing": missing,
        "spread": spread,
        "mid": mid,
        "spread_pct": spread_pct,
        "bid": bid,
        "ask": ask,
    }


def _v29_score_row(row):
    q = _v29_quality_gate(row)
    base = _v29_safe_float(row.get("score"), 0)

    bonus = 0
    if q["executable"]:
        bonus += 1000
    if q["spread_pct"] is not None:
        bonus += max(0, 100 - q["spread_pct"])
    if row.get("data_quality") == "FULL_WITH_GREEKS":
        bonus += 50
    if _v29_safe_upper(row.get("decision"), "") in ["ENTRY", "ENTRY_READY", "OPERAR"]:
        bonus += 30

    return base + bonus


def _v29_best_row_for_ticker(ticker, rows):
    ticker = _v29_safe_upper(ticker)
    ticker_rows = [r for r in rows if _v29_safe_upper(r.get("ticker")) == ticker]

    if not ticker_rows:
        return None, [], []

    enriched = []
    for r in ticker_rows:
        rr = dict(r)
        q = _v29_quality_gate(rr)
        rr["v29_quality"] = q["quality"]
        rr["v29_missing"] = q["missing"]
        rr["spread"] = q["spread"]
        rr["mid"] = q["mid"]
        rr["spread_pct"] = q["spread_pct"]
        rr["bid"] = q["bid"]
        rr["ask"] = q["ask"]
        rr["v29_executable"] = q["executable"]
        enriched.append(rr)

    executable = [r for r in enriched if r.get("v29_executable")]

    if executable:
        best = sorted(executable, key=_v29_score_row, reverse=True)[0]
    else:
        best = sorted(enriched, key=_v29_score_row, reverse=True)[0]

    return best, enriched, executable


def _v29_technical_state(ticker, technical):
    ticker = _v29_safe_upper(ticker)
    t = technical.get(ticker) or {}
    score = _v29_safe_float(t.get("score") or t.get("technical_score"), None)
    trend = _v29_safe_upper(t.get("trend") or t.get("bias") or t.get("technical_bias"), "UNKNOWN")

    confirmed = score is not None and score >= _V29_MIN_TECH_SCORE and trend not in ["UNKNOWN", "NEUTRAL", ""]

    return {
        "available": bool(t),
        "confirmed": confirmed,
        "score": score,
        "trend": trend,
        "raw": t,
    }


def _v29_market_state(master):
    data = master.get("data") or {}
    market = data.get("market") or data.get("market_hours") or {}

    if not isinstance(market, dict):
        market = {}

    is_open = bool(
        market.get("is_regular_market_open") or
        market.get("regular_market_open") or
        market.get("is_open")
    )

    options_expected = bool(
        market.get("options_bidask_expected") or
        market.get("options_market_open") or
        is_open
    )

    label = market.get("label") or market.get("status") or "UNKNOWN"

    return {
        "is_regular_market_open": is_open,
        "options_bidask_expected": options_expected,
        "label": label,
        "raw": market,
    }


def _v29_decide_ticker(ticker):
    ticker = _v29_safe_upper(ticker)
    master = _v29_discover_master_snapshot()
    rows = master["rows"]
    technical = master["technical"]
    market = _v29_market_state(master)

    best, ticker_rows, executable_rows = _v29_best_row_for_ticker(ticker, rows)
    tech_state = _v29_technical_state(ticker, technical)

    if not best:
        return {
            "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
            "generated_at": _v29_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "strategy": "UNKNOWN",
            "technical_bias": tech_state["trend"],
            "technical_score": tech_state["score"],
            "options_score": None,
            "main_blocker": "NO_OPTIONS_ROWS_FOR_TICKER",
            "action": f"{ticker}: no hay filas de opciones detectadas.",
            "executive_summary": f"{ticker}: NO_DATA. No hay datos de opciones para evaluar operación.",
            "risk_note": "No ejecutar sin validar manualmente datos, liquidez, spread, evento, capital y tolerancia de riesgo.",
            "best_row": None,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "executable_rows_found": 0,
            "technical": tech_state,
            "market": market,
            "master_source": master["path"],
        }

    q = _v29_quality_gate(best)
    strategy = _v29_safe_upper(best.get("strategy"), "UNKNOWN")
    options_score = _v29_safe_float(best.get("score"), 0)

    market_ok = bool(market.get("is_regular_market_open")) and bool(market.get("options_bidask_expected"))
    technical_ok = tech_state["confirmed"]
    options_ok = q["executable"]

    if market_ok and technical_ok and options_ok:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        can_operate = True
        severity = "green"
        blocker = None
        action = f"{ticker}: entrada potencial lista. Validar tamaño, spread, liquidez, evento y riesgo final antes de ejecutar."
    elif not market_ok:
        final_state = "WAIT_MARKET_OPEN"
        decision = "WAIT_MARKET_OPEN"
        can_operate = False
        severity = "gray"
        blocker = "MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE"
        action = f"{ticker}: setup detectado, pero esperar ventana confiable de mercado/opciones."
    elif not technical_ok:
        final_state = "WAIT_TECHNICAL"
        decision = "WAIT_TECHNICAL"
        can_operate = False
        severity = "yellow"
        blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{ticker}: opciones detectadas, pero falta confirmación técnica."
    elif not options_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        can_operate = False
        severity = "yellow"
        blocker = "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"
        action = f"{ticker}: técnico confirmado, pero falta contrato ejecutable con bid/ask/spread/delta/DTE completos."
    else:
        final_state = "RADAR"
        decision = "RADAR"
        can_operate = False
        severity = "yellow"
        blocker = "UNKNOWN_CONFIRMATION_GAP"
        action = f"{ticker}: mantener en radar. Confirmaciones incompletas."

    executive_summary = (
        f"{ticker}: {final_state}. "
        f"Estrategia {strategy}. "
        f"Técnico {tech_state['trend']} score {tech_state['score']}. "
        f"Opciones score {options_score}. "
        f"Spread {q.get('spread')} / {q.get('spread_pct')}%. "
        f"Bloqueador: {blocker or 'None'}."
    )

    return {
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "strategy": strategy,
        "technical_bias": tech_state["trend"],
        "technical_score": tech_state["score"],
        "options_score": options_score,
        "options_fit": "EXECUTABLE_CONTRACT_CONFIRMED" if options_ok else "OPTIONS_DATA_INCOMPLETE",
        "technical_fit": "TECHNICAL_CONFIRMED" if technical_ok else "TECHNICAL_NOT_CONFIRMED",
        "main_blocker": blocker,
        "action": action,
        "executive_summary": executive_summary,
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital disponible y tolerancia de riesgo.",
        "best_row": best,
        "best_row_quality": q,
        "rows_found_for_ticker": len(ticker_rows),
        "total_rows_found": len(rows),
        "executable_rows_found": len(executable_rows),
        "technical": tech_state,
        "market": market,
        "master_source": master["path"],
    }


def _v29_all_decisions(tickers=None):
    if not tickers:
        tickers = _V29_DEFAULT_TICKERS
    return [_v29_decide_ticker(t) for t in tickers]


def _v29_html_escape(x):
    return _v29_html.escape("" if x is None else str(x))


def _v29_badge(state):
    color = "#64748b"
    if state == "ENTRY_READY":
        color = "#16a34a"
    elif state in ["NO_DATA"]:
        color = "#dc2626"
    elif state.startswith("WAIT"):
        color = "#ca8a04"
    elif state == "RADAR":
        color = "#2563eb"

    return f'<span style="background:{color};color:white;padding:7px 12px;border-radius:999px;font-weight:800;font-size:12px;">{_v29_html_escape(state)}</span>'


def _v29_dashboard_html(tickers=None):
    decisions = _v29_all_decisions(tickers)

    counts = {
        "ENTRY_READY": 0,
        "WAIT_TECHNICAL": 0,
        "WAIT_OPTIONS": 0,
        "WAIT_MARKET": 0,
        "NO_DATA": 0,
        "RADAR": 0,
    }

    for d in decisions:
        fs = d.get("final_state")
        if fs == "ENTRY_READY":
            counts["ENTRY_READY"] += 1
        elif fs == "WAIT_TECHNICAL":
            counts["WAIT_TECHNICAL"] += 1
        elif fs == "WAIT_OPTIONS_DATA":
            counts["WAIT_OPTIONS"] += 1
        elif fs == "WAIT_MARKET_OPEN":
            counts["WAIT_MARKET"] += 1
        elif fs == "NO_DATA":
            counts["NO_DATA"] += 1
        else:
            counts["RADAR"] += 1

    rows_html = ""

    for d in decisions:
        br = d.get("best_row") or {}
        q = d.get("best_row_quality") or {}
        rows_html += f"""
        <tr>
            <td><a href="/v29_trade_decision/{_v29_html_escape(d.get('ticker'))}">{_v29_html_escape(d.get('ticker'))}</a></td>
            <td>{_v29_badge(d.get('final_state'))}</td>
            <td>{_v29_html_escape(d.get('strategy'))}</td>
            <td>{_v29_html_escape(d.get('technical_bias'))}</td>
            <td>{_v29_html_escape(d.get('technical_score'))}</td>
            <td>{_v29_html_escape(d.get('options_score'))}</td>
            <td>{_v29_html_escape(br.get('strike'))}</td>
            <td>{_v29_html_escape(br.get('expiration'))}</td>
            <td>{_v29_html_escape(br.get('dte'))}</td>
            <td>{_v29_html_escape(q.get('bid'))}</td>
            <td>{_v29_html_escape(q.get('ask'))}</td>
            <td>{_v29_html_escape(q.get('mid'))}</td>
            <td>{_v29_html_escape(q.get('spread'))}</td>
            <td>{_v29_html_escape(q.get('spread_pct'))}</td>
            <td>{'Sí' if d.get('can_operate') else 'No'}</td>
            <td>{_v29_html_escape(d.get('main_blocker'))}</td>
            <td>{_v29_html_escape(d.get('action'))}</td>
        </tr>
        """

    generated = _v29_now()

    return f"""
    <!doctype html>
    <html>
    <head>
        <title>V29 Final Decision Quality Engine</title>
        <style>
            body {{
                font-family: Inter, Arial, sans-serif;
                background:#f5f7fb;
                color:#0f172a;
                margin:0;
                padding:32px;
            }}
            h1 {{font-size:34px; margin-bottom:22px;}}
            .hero {{
                background:#0f172a;
                color:white;
                border-radius:26px;
                padding:34px;
                margin-bottom:26px;
            }}
            .hero h2 {{margin:0 0 14px 0; font-size:26px;}}
            .cards {{
                display:grid;
                grid-template-columns: repeat(6, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                border-radius:18px;
                padding:20px;
                box-shadow:0 12px 30px rgba(15,23,42,.08);
            }}
            .label {{
                color:#64748b;
                font-size:12px;
                text-transform:uppercase;
                font-weight:800;
                letter-spacing:.08em;
            }}
            .num {{
                font-size:34px;
                font-weight:900;
                margin-top:8px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 12px 30px rgba(15,23,42,.08);
                font-size:13px;
            }}
            th {{
                text-align:left;
                padding:14px;
                color:#64748b;
                font-size:11px;
                text-transform:uppercase;
                letter-spacing:.08em;
                border-bottom:1px solid #e2e8f0;
            }}
            td {{
                padding:14px;
                border-bottom:1px solid #e2e8f0;
                vertical-align:top;
            }}
            .foot {{
                color:#64748b;
                margin-top:18px;
                font-size:14px;
            }}
            a {{color:#2563eb; font-weight:800;}}
        </style>
    </head>
    <body>
        <h1>V29 — Final Decision Quality Engine</h1>

        <div class="hero">
            <h2>Execution Guard activo</h2>
            <p>Selecciona únicamente contratos realmente ejecutables: bid/ask/spread/delta/DTE/strike + técnico + mercado.</p>
            <p>Generado: {generated}</p>
        </div>

        <div class="cards">
            <div class="card"><div class="label">Entry Ready</div><div class="num">{counts["ENTRY_READY"]}</div></div>
            <div class="card"><div class="label">Wait Technical</div><div class="num">{counts["WAIT_TECHNICAL"]}</div></div>
            <div class="card"><div class="label">Wait Options</div><div class="num">{counts["WAIT_OPTIONS"]}</div></div>
            <div class="card"><div class="label">Wait Market</div><div class="num">{counts["WAIT_MARKET"]}</div></div>
            <div class="card"><div class="label">No Data</div><div class="num">{counts["NO_DATA"]}</div></div>
            <div class="card"><div class="label">Radar</div><div class="num">{counts["RADAR"]}</div></div>
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
                    <th>Strike</th>
                    <th>Exp</th>
                    <th>DTE</th>
                    <th>Bid</th>
                    <th>Ask</th>
                    <th>Mid</th>
                    <th>Spread</th>
                    <th>Spread %</th>
                    <th>Operable</th>
                    <th>Bloqueador</th>
                    <th>Acción</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="foot">
            Endpoints: /v29_system_status · /v29_trade_decision/QQQ · /gpt_v29_trade_decision/QQQ · /v29_dashboard
        </div>
    </body>
    </html>
    """


@app.get("/v29_system_status")
async def v29_system_status():
    master = _v29_discover_master_snapshot()
    market = _v29_market_state(master)
    decisions = _v29_all_decisions()

    return {
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
        "status": "OK",
        "master_snapshot_available": bool(master.get("path")),
        "master_source": master.get("path"),
        "rows_found": len(master.get("rows", [])),
        "technical_count": len(master.get("technical", {})),
        "technical_tickers": sorted(list(master.get("technical", {}).keys())),
        "market": market,
        "summary": {
            "entry_ready": sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY"),
            "wait_technical": sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL"),
            "wait_options": sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"),
            "wait_market": sum(1 for d in decisions if d.get("final_state") == "WAIT_MARKET_OPEN"),
            "no_data": sum(1 for d in decisions if d.get("final_state") == "NO_DATA"),
        },
        "endpoints": {
            "trade_decision_example": "/v29_trade_decision/QQQ",
            "gpt_trade_decision_example": "/gpt_v29_trade_decision/QQQ",
            "dashboard": "/v29_dashboard",
            "dashboard_ticker_example": "/v29_dashboard/QQQ",
        },
    }


@app.get("/v29_trade_decision/{ticker}")
async def v29_trade_decision(ticker: str):
    return _v29_decide_ticker(ticker)


@app.get("/gpt_v29_trade_decision/{ticker}")
async def gpt_v29_trade_decision(ticker: str):
    d = _v29_decide_ticker(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "technical_fit": d.get("technical_fit"),
        "options_score": d.get("options_score"),
        "options_fit": d.get("options_fit"),
        "best_contract": {
            "strike": (d.get("best_row") or {}).get("strike"),
            "expiration": (d.get("best_row") or {}).get("expiration"),
            "dte": (d.get("best_row") or {}).get("dte"),
            "bid": (d.get("best_row_quality") or {}).get("bid"),
            "ask": (d.get("best_row_quality") or {}).get("ask"),
            "mid": (d.get("best_row_quality") or {}).get("mid"),
            "spread": (d.get("best_row_quality") or {}).get("spread"),
            "spread_pct": (d.get("best_row_quality") or {}).get("spread_pct"),
            "missing": (d.get("best_row_quality") or {}).get("missing"),
        },
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": d.get("risk_note"),
        "master_source": d.get("master_source"),
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
    }


@app.get("/v29_dashboard", response_class=_V29HTMLResponse)
async def v29_dashboard():
    return _v29_dashboard_html()


@app.get("/v29_dashboard/{ticker}", response_class=_V29HTMLResponse)
async def v29_dashboard_ticker(ticker: str):
    return _v29_dashboard_html([ticker])


# ============================================================
# END V29 FINAL DECISION QUALITY ENGINE
# ============================================================
'''

if "V29 FINAL DECISION QUALITY ENGINE" not in s:
    s = s.rstrip() + "\n\n" + block + "\n"
else:
    print("V29 block already exists. No duplicate inserted.")

APP.write_text(s)
print("V29 Final Decision Quality Engine patch applied.")
