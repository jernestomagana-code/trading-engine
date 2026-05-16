#!/usr/bin/env python3
from pathlib import Path
import shutil
from datetime import datetime
import py_compile

MAIN = Path("app/main.py")
if not MAIN.exists():
    raise SystemExit("ERROR: corre esto desde ~/Projects/trading-engine; no encuentro app/main.py")

text = MAIN.read_text()

required = [
    "Super Engine Bolsa v3.0",
    "@app.post(\"/webhook/tradingview\")",
    "@app.post(\"/test_signal\")",
    "@app.get(\"/get_dashboard\")",
    "@app.get(\"/get_report\")",
    "@app.get(\"/stats\")",
    "@app.get(\"/debug/supabase\")",
    "def build_dashboard():",
    "def market_regime():",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("ERROR: tu main.py no parece ser v3 estable. Faltan: " + ", ".join(missing))

backup = Path(f"app/main_backup_v3_before_v4_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
shutil.copy(MAIN, backup)

text = text.replace('version="3.0.0"', 'version="4.0.0"')
text = text.replace("Super Engine Bolsa v3.0", "Super Engine Bolsa v4.0")
text = text.replace("v3.0", "v4.0")
text = text.replace("STABLE INSTITUTIONAL CORE", "DECISION INTELLIGENCE CORE")
text = text.replace("Stable Institutional Core", "Decision Intelligence Core")

if "import math" not in text:
    text = text.replace("import requests\n", "import requests\nimport math\n")

text = text.replace(
    r"\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX)\b",
    r"\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX|IWM|VIX|DXY)\b"
)

if "iv_rank: Optional[float]" not in text:
    text = text.replace(
        "    price: Optional[float] = Field(default=None)\n"
        "    state: Optional[str] = Field(default=None)\n",
        "    price: Optional[float] = Field(default=None)\n"
        "    entry: Optional[float] = Field(default=None)\n"
        "    stop: Optional[float] = Field(default=None)\n"
        "    target: Optional[float] = Field(default=None)\n"
        "    iv_rank: Optional[float] = Field(default=None)\n"
        "    volume_relative: Optional[float] = Field(default=None)\n"
        "    rsi: Optional[float] = Field(default=None)\n"
        "    macd_state: Optional[str] = Field(default=None)\n"
        "    adx: Optional[float] = Field(default=None)\n"
        "    vwap_position: Optional[str] = Field(default=None)\n"
        "    state: Optional[str] = Field(default=None)\n"
    )

if "class PositionSizingRequest" not in text:
    models = '''
class PositionSizingRequest(BaseModel):
    account_size: float = Field(..., description="Account size in USD")
    risk_percent: float = Field(default=1.0, description="Risk percent per trade")
    entry: float
    stop: float


class OptionEvalRequest(BaseModel):
    ticker: str
    strategy: str = Field(default="NAKED_PUT")
    strike: Optional[float] = None
    premium: Optional[float] = None
    dte: Optional[int] = None
    account_size: Optional[float] = None
    margin_required: Optional[float] = None
    iv_rank: Optional[float] = None


'''
    text = text.replace("\n\ndef now_utc():\n", "\n\n" + models + "def now_utc():\n")

append_code = '''

# ==============================
# V4 ADDITIVE DECISION INTELLIGENCE LAYER
# Preserves v3 core: webhook, Supabase, history, dashboard, report, test_signal, stats.
# ==============================

def v4_alignment_score(classification):
    alignment = classification.get("alignment", "mixed")
    missing = classification.get("missing_timeframes", [])
    if alignment in ["bullish", "bearish"] and not missing:
        return 100
    if alignment in ["bullish", "bearish"] and "5m" in missing:
        return 80
    if alignment in ["bullish_context", "bearish_context"]:
        return 60
    if "partial" in alignment:
        return 65
    return 25


def v4_market_regime():
    base = market_regime()
    spy = base.get("spy")
    qqq = base.get("qqq")
    tlt = base.get("tlt")
    iwm = classify_asset(trade_store.get("IWM", {})) if "IWM" in trade_store else None
    vix = classify_asset(trade_store.get("VIX", {})) if "VIX" in trade_store else None
    dxy = classify_asset(trade_store.get("DXY", {})) if "DXY" in trade_store else None
    bullish = 0
    bearish = 0
    for item in [spy, qqq, iwm]:
        if item:
            if item.get("alignment") in ["bullish", "bullish_context", "partial_bullish"]:
                bullish += 1
            if item.get("alignment") in ["bearish", "bearish_context", "partial_bearish"]:
                bearish += 1
    vix_risk = bool(vix and vix.get("alignment") in ["bullish", "bullish_context", "partial_bullish"])
    if bullish >= 2 and bearish == 0 and not vix_risk:
        regime = "STRONG_BULL" if qqq and qqq.get("priority_score", 0) >= 75 else "BULL"
        summary = "Índices principales muestran sesgo alcista."
    elif bearish >= 2 and vix_risk:
        regime = "PANIC"
        summary = "Índices bajistas con VIX presionando."
    elif bearish >= 2:
        regime = "BEAR"
        summary = "Índices principales muestran sesgo bajista."
    elif bullish >= 1 and bearish >= 1:
        regime = "CHOP"
        summary = "Lectura mixta entre índices; riesgo de falsas rupturas."
    else:
        regime = base.get("regime", "MIXED_OR_CHOP")
        summary = base.get("summary", "No hay alineación clara entre índices principales.")
    return {"regime": regime, "summary": summary, "spy": spy, "qqq": qqq, "tlt": tlt, "iwm": iwm, "vix": vix, "dxy": dxy}


def probability_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state", "NO_DATA")
    priority = safe_float(classification.get("priority_score"), 0)
    freshness = safe_float(classification.get("freshness_weighted"), 0)
    alignment_score = v4_alignment_score(classification)
    base = 45 + (priority - 50) * 0.28 + (alignment_score - 50) * 0.18 + (freshness - 50) * 0.10
    if state in ["LONG_READY", "SHORT_READY"]:
        base += 8
    elif state in ["LONG_ACTIVE", "SHORT_ACTIVE"]:
        base += 6
    elif state in ["PRE_LONG", "PRE_SHORT"]:
        base += 2
    elif state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        base -= 10
    elif state in ["WAIT", "NO_DATA", "MIXED"]:
        base -= 12
    if regime in ["STRONG_BULL", "BULL", "BEAR"]:
        base += 3
    elif regime in ["CHOP", "RANGE"]:
        base -= 5
    elif regime == "PANIC":
        base -= 4
    probability = round(max(5, min(base, 92)), 1)
    confidence = "HIGH" if probability >= 80 else "MEDIUM_HIGH" if probability >= 68 else "MEDIUM" if probability >= 56 else "LOW"
    risk = "LOW" if probability >= 78 and state not in ["EXTENDED_LONG", "EXTENDED_SHORT"] else "MEDIUM" if probability >= 60 else "HIGH"
    return {"probability_estimate": probability, "confidence": confidence, "risk": risk, "alignment_score": alignment_score, "note": "Heurístico v4: score, alineación, frescura y régimen. No usa aún IV/flow/gamma reales."}


def risk_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state", "NO_DATA")
    missing = classification.get("missing_timeframes", [])
    priority = safe_float(classification.get("priority_score"), 0)
    warnings = []
    allowed = True
    if state in ["NO_DATA", "WAIT", "MIXED"]:
        warnings.append("No hay edge suficiente.")
        allowed = False
    if state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        warnings.append("Movimiento extendido: no perseguir.")
        allowed = False
    if "5m" in missing and state not in ["PRE_LONG", "PRE_SHORT"]:
        warnings.append("Falta gatillo 5m.")
    if regime in ["CHOP", "RANGE"] and priority < 85:
        warnings.append("Régimen de mercado reduce edge.")
        allowed = False
    if priority < 65:
        warnings.append("Priority score insuficiente.")
        allowed = False
    return {"trade_allowed": allowed, "risk_level": "LOW" if allowed and priority >= 85 else "MEDIUM" if priority >= 70 else "HIGH", "warnings": warnings, "capital_preservation_bias": not allowed}


def expected_pl_engine(classification, account_size=None):
    priority = safe_float(classification.get("priority_score"), 0)
    entry = safe_float(classification.get("entry"), 0)
    stop = safe_float(classification.get("stop"), 0)
    risk_budget = (account_size * 0.01) if account_size else 1000
    if entry and stop and abs(entry - stop) > 0:
        units = math.floor(risk_budget / abs(entry - stop))
    else:
        units = None
    base = round((priority - 50) * 12, 2)
    return {"base_case_pl": base, "favorable_case_pl": round(base * 2.0, 2), "adverse_case_pl": round(-risk_budget, 2), "risk_budget_assumption": risk_budget, "suggested_units_if_entry_stop_available": units, "note": "P/L conceptual v4. Requiere contrato/opción/cartera para cálculo monetario real."}


def theta_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state")
    priority = classification.get("priority_score", 0)
    if state in ["PRE_LONG", "LONG_READY", "LONG_ACTIVE", "PARTIAL_LONG"] and regime in ["STRONG_BULL", "BULL", "MIXED_OR_CHOP", "RISK_ON"]:
        return {"naked_put_bias": "FAVORABLE" if priority >= 70 else "WATCH", "covered_call_bias": "LOW", "preferred_condition": "Vender put solo si soporte es claro, IV es suficiente y no hay evento binario cercano."}
    if state in ["EXTENDED_LONG"]:
        return {"naked_put_bias": "WAIT", "covered_call_bias": "FAVORABLE_IF_HOLDING_SHARES", "preferred_condition": "Covered call solo si hay posición, resistencia clara e IV suficiente."}
    if state in ["PRE_SHORT", "SHORT_READY", "SHORT_ACTIVE", "PARTIAL_SHORT"]:
        return {"naked_put_bias": "AVOID", "covered_call_bias": "FAVORABLE_IF_HOLDING_SHARES", "preferred_condition": "Priorizar defensa; no vender puts en deterioro técnico."}
    return {"naked_put_bias": "NEUTRAL", "covered_call_bias": "NEUTRAL", "preferred_condition": "No theta trade sin edge técnico/volatilidad."}


def strategy_selection_v4(classification, regime="MIXED_OR_CHOP"):
    base = strategy_selection(classification)
    probability = probability_engine(classification, regime)
    theta = theta_engine(classification, regime)
    risk = risk_engine(classification, regime)
    expected_pl = expected_pl_engine(classification)
    return {**base, "strategy_score": probability["probability_estimate"], "probability": probability, "theta": theta, "risk": risk, "expected_pl": expected_pl}


def build_dashboard_v4():
    dashboard = []
    regime_info = v4_market_regime()
    regime = regime_info.get("regime", "MIXED_OR_CHOP")
    for ticker, timeframes in trade_store.items():
        c = classify_asset(timeframes)
        strategy = strategy_selection_v4(c, regime)
        dashboard.append({"ticker": ticker, "state": c["state"], "grade": c["grade"], "conviction": c["conviction"], "action": c["action"], "strategy_type": c["strategy_type"], "primary_strategy": strategy["primary_strategy"], "secondary_strategy": strategy["secondary_strategy"], "avoid": strategy["avoid"], "strategy_score": strategy["strategy_score"], "theta": strategy["theta"], "probability": strategy["probability"], "risk": strategy["risk"], "expected_pl": strategy["expected_pl"], "alignment": c["alignment"], "alignment_score": strategy["probability"]["alignment_score"], "weighted_score": c["weighted_score"], "priority_score": c["priority_score"], "freshness_weighted": c["freshness_weighted"], "recommendation": c["recommendation"], "reason": c["reason"], "missing_timeframes": c["missing_timeframes"]})
    return sorted(dashboard, key=lambda x: (x["priority_score"], x["weighted_score"]), reverse=True)


@app.get("/gpt_report")
def gpt_report():
    dashboard = build_dashboard_v4()
    regime = v4_market_regime()
    best = dashboard[0] if dashboard else None
    if not best:
        return {"engine": "v4.0", "market": regime["regime"], "status": "NO_DATA", "best_setup": None, "plan": "Esperar nuevas señales frescas."}
    return {"engine": "v4.0", "market": regime["regime"], "market_summary": regime["summary"], "best_setup": f"{best['ticker']} {best['state']}", "strategy": best["primary_strategy"], "probability": best["probability"]["probability_estimate"], "confidence": best["probability"]["confidence"], "risk": best["risk"]["risk_level"], "trade_allowed": best["risk"]["trade_allowed"], "plan": best["recommendation"], "avoid": best["avoid"], "top_5": dashboard[:5], "radar": [x for x in dashboard if x["state"] in ["PRE_LONG", "PRE_SHORT", "PARTIAL_LONG", "PARTIAL_SHORT"]][:5], "avoid_list": [x for x in dashboard if not x["risk"]["trade_allowed"]][:5]}


@app.get("/get_dashboard_v4")
def get_dashboard_v4():
    dashboard = build_dashboard_v4()
    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i
    return {"generated_at": now_utc().isoformat(), "engine": "v4.0", "supabase_enabled": supabase_enabled(), "market_regime": v4_market_regime(), "dashboard": dashboard, "best_setups": dashboard[:5]}


@app.get("/get_trade_context_v4")
def get_trade_context_v4(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in trade_store:
        return {"ticker": ticker, "status": "missing_data", "message": "No hay datos todavía para este ticker."}
    regime = v4_market_regime().get("regime", "MIXED_OR_CHOP")
    c = classify_asset(trade_store[ticker])
    return {"ticker": ticker, "engine": "v4.0", "classification": c, "strategy_selection": strategy_selection_v4(c, regime), "theta_engine": theta_engine(c, regime), "probability": probability_engine(c, regime), "risk": risk_engine(c, regime), "expected_pl": expected_pl_engine(c)}


@app.post("/position_sizing")
def position_sizing(req: PositionSizingRequest):
    risk_budget = req.account_size * (req.risk_percent / 100)
    unit_risk = abs(req.entry - req.stop)
    if unit_risk <= 0:
        return {"error": "Entry and stop cannot be equal."}
    return {"engine": "v4.0", "account_size": req.account_size, "risk_percent": req.risk_percent, "risk_budget": round(risk_budget, 2), "entry": req.entry, "stop": req.stop, "unit_risk": round(unit_risk, 4), "suggested_units": math.floor(risk_budget / unit_risk)}


@app.post("/evaluate_option")
def evaluate_option(req: OptionEvalRequest):
    ticker = req.ticker.upper().strip()
    context = classify_asset(trade_store.get(ticker, {})) if ticker in trade_store else None
    regime = v4_market_regime().get("regime", "MIXED_OR_CHOP")
    margin_yield = round((req.premium / req.margin_required) * 100, 2) if req.premium and req.margin_required and req.margin_required > 0 else None
    iv_comment = "IV no proporcionada."
    if req.iv_rank is not None:
        iv_comment = "IV rank favorable para venta de prima." if req.iv_rank >= 50 else "IV rank moderada; venta de prima condicional." if req.iv_rank >= 30 else "IV rank baja; prima puede no compensar riesgo."
    dictamen = "No recomendable: falta contexto técnico reciente."
    if context:
        theta = theta_engine(context, regime)
        if req.strategy.upper() in ["NAKED_PUT", "SELL_PUT"] and theta["naked_put_bias"] in ["FAVORABLE", "WATCH"]:
            dictamen = "Condicional/Favorable: revisar soporte, IV, DTE y assignment risk."
        elif req.strategy.upper() in ["COVERED_CALL", "SELL_CALL"] and theta["covered_call_bias"] in ["FAVORABLE_IF_HOLDING_SHARES"]:
            dictamen = "Condicional/Favorable si ya existe posición y resistencia clara."
        else:
            dictamen = "Condicional: el contexto no favorece claramente la estrategia."
    return {"engine": "v4.0", "ticker": ticker, "strategy": req.strategy, "strike": req.strike, "premium": req.premium, "dte": req.dte, "margin_required": req.margin_required, "premium_on_margin_percent": margin_yield, "iv_rank": req.iv_rank, "iv_comment": iv_comment, "context_available": context is not None, "technical_context": context, "dictamen": dictamen}


@app.get("/debug/regime")
def debug_regime():
    return {"engine": "v4.0", "market_regime": v4_market_regime()}


@app.get("/debug/scoring")
def debug_scoring(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()
    if ticker not in trade_store:
        return {"engine": "v4.0", "ticker": ticker, "error": "Ticker not in memory"}
    regime = v4_market_regime().get("regime", "MIXED_OR_CHOP")
    c = classify_asset(trade_store[ticker])
    return {"engine": "v4.0", "ticker": ticker, "classification": c, "strategy": strategy_selection_v4(c, regime), "probability": probability_engine(c, regime), "risk": risk_engine(c, regime), "theta": theta_engine(c, regime), "expected_pl": expected_pl_engine(c)}



# ==============================
# V4 COMPLETION PATCH
# Adds v4 report/html/routes without touching v3 endpoints.
# ==============================

@app.get("/get_report_v4")
def get_report_v4():
    dashboard = build_dashboard_v4()
    regime = v4_market_regime()

    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i

    lines = []
    lines.append("SUPER ENGINE BOLSA v4.0 — DECISION INTELLIGENCE CORE")
    lines.append(f"Generado UTC: {now_utc().isoformat()}")
    lines.append("")
    lines.append("RÉGIMEN DE MERCADO")
    lines.append(f"- Estado: {regime['regime']}")
    lines.append(f"- Lectura: {regime['summary']}")
    lines.append("")

    if not dashboard:
        lines.append("No hay señales suficientes todavía.")
        return {
            "generated_at": now_utc().isoformat(),
            "engine": "v4.0",
            "report": "\n".join(lines),
            "dashboard": []
        }

    ready = [x for x in dashboard if x["state"] in ["LONG_READY", "SHORT_READY", "LONG_ACTIVE", "SHORT_ACTIVE"]]
    extended = [x for x in dashboard if x["state"] in ["EXTENDED_LONG", "EXTENDED_SHORT"]]
    radar = [x for x in dashboard if x["state"] in ["PRE_LONG", "PRE_SHORT", "PARTIAL_LONG", "PARTIAL_SHORT"]]
    avoid = [x for x in dashboard if not x["risk"]["trade_allowed"]]

    lines.append("RESUMEN EJECUTIVO")
    lines.append(f"- Setups listos/activos: {len(ready)}")
    lines.append(f"- Extendidos/no perseguir: {len(extended)}")
    lines.append(f"- Radar: {len(radar)}")
    lines.append(f"- Evitar/sin edge/riesgo alto: {len(avoid)}")
    lines.append("")

    lines.append("TOP PRIORITY SETUPS")
    for x in dashboard[:5]:
        lines.append(
            f"{x['priority_rank']}. {x['ticker']} | {x['grade']} | {x['conviction']} | "
            f"{x['state']} | Priority {x['priority_score']} | Prob {x['probability']['probability_estimate']}% | "
            f"Risk {x['risk']['risk_level']} | {x['primary_strategy']}"
        )

    if ready:
        lines.append("")
        lines.append("SETUPS LISTOS / ACTIVOS")
        for x in ready:
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['conviction']} | {x['state']} | "
                f"Priority {x['priority_score']} | Prob {x['probability']['probability_estimate']}% | "
                f"{x['recommendation']} | {x['reason']}"
            )

    if radar:
        lines.append("")
        lines.append("RADAR / EN FORMACIÓN")
        for x in radar:
            missing = ", ".join(x["missing_timeframes"]) if x["missing_timeframes"] else "confirmación"
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['state']} | "
                f"Priority {x['priority_score']} | Falta: {missing} | {x['reason']}"
            )

    if extended:
        lines.append("")
        lines.append("EXTENDIDOS — NO PERSEGUIR")
        for x in extended:
            lines.append(f"- {x['ticker']} | {x['state']} | {x['reason']}")

    return {
        "generated_at": now_utc().isoformat(),
        "engine": "v4.0",
        "supabase_enabled": supabase_enabled(),
        "report": "\n".join(lines),
        "dashboard": dashboard,
        "best_setups": dashboard[:5],
    }


@app.get("/dashboard_html_v4", response_class=HTMLResponse)
def dashboard_html_v4():
    dashboard = build_dashboard_v4()
    regime = v4_market_regime()

    rows = ""
    color_map = {
        "A+": "#0B6E4F",
        "A": "#1A936F",
        "B": "#F4A261",
        "C": "#E76F51",
    }

    for i, item in enumerate(dashboard, start=1):
        color = color_map.get(item["grade"], "#999")
        prob = item.get("probability", {}).get("probability_estimate", "")
        risk = item.get("risk", {}).get("risk_level", "")
        theta = item.get("theta", {}).get("naked_put_bias", "")
        allowed = item.get("risk", {}).get("trade_allowed", False)

        rows += (
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{item['ticker']}</td>"
            f"<td style='background:{color}; color:white; font-weight:bold;'>{item['grade']}</td>"
            f"<td>{item['conviction']}</td>"
            f"<td>{item['state']}</td>"
            f"<td>{item['primary_strategy']}</td>"
            f"<td>{theta}</td>"
            f"<td>{prob}%</td>"
            f"<td>{risk}</td>"
            f"<td>{allowed}</td>"
            f"<td>{item['priority_score']}</td>"
            f"<td>{item['weighted_score']}</td>"
            f"<td>{item['alignment']}</td>"
            f"<td>{item['reason']}</td>"
            "</tr>"
        )

    html = (
        "<html><head><title>Super Engine Bolsa v4 Dashboard</title>"
        "<style>"
        "body{font-family:Arial;margin:30px;background:#f7f7f7}"
        "h1{color:#111}"
        "table{border-collapse:collapse;width:100%;background:white}"
        "th,td{border:1px solid #ddd;padding:10px;text-align:left;font-size:13px}"
        "th{background:#111;color:white}"
        ".regime{padding:15px;background:white;margin-bottom:20px;border-left:5px solid #111}"
        ".meta{font-size:13px;color:#555;margin-bottom:20px}"
        "</style></head><body>"
        "<h1>Super Engine Bolsa v4.0</h1>"
        f"<div class='meta'>Supabase enabled: {supabase_enabled()}</div>"
        f"<div class='regime'><b>Market Regime:</b> {regime['regime']}<br><b>Lectura:</b> {regime['summary']}</div>"
        "<table><tr>"
        "<th>Rank</th><th>Ticker</th><th>Grade</th><th>Conviction</th><th>State</th>"
        "<th>Strategy</th><th>Theta</th><th>Prob</th><th>Risk</th><th>Allowed</th>"
        "<th>Priority</th><th>Score</th><th>Alignment</th><th>Reason</th>"
        "</tr>"
        f"{rows}"
        "</table></body></html>"
    )

    return html


@app.get("/debug/routes_v4")
def debug_routes_v4():
    return {
        "engine": "v4.0",
        "preserved_v3_routes": [
            "/",
            "/health",
            "/webhook/tradingview",
            "/test_signal",
            "/get_trade_context",
            "/get_dashboard",
            "/get_report",
            "/latest",
            "/history",
            "/stats",
            "/stats/ticker/{ticker}",
            "/debug/supabase",
            "/debug/routes",
            "/dashboard_html",
        ],
        "added_v4_routes": [
            "/gpt_report",
            "/get_dashboard_v4",
            "/get_report_v4",
            "/get_trade_context_v4",
            "/dashboard_html_v4",
            "/position_sizing",
            "/evaluate_option",
            "/debug/regime",
            "/debug/scoring",
            "/debug/routes_v4",
        ],
    }

# ==============================
# END V4 COMPLETION PATCH
# ==============================

# ==============================
# END V4 ADDITIVE LAYER
# ==============================
'''

if "V4 ADDITIVE DECISION INTELLIGENCE LAYER" not in text:
    text = text + append_code

tmp = MAIN.with_suffix(".v4_candidate.py")
tmp.write_text(text)
py_compile.compile(str(tmp), doraise=True)
MAIN.write_text(text)

print(f"OK: v4 aditivo aplicado preservando v3. Backup creado: {backup}")
print("Validación Python: OK")
print("Nuevas rutas: /gpt_report, /get_dashboard_v4, /get_trade_context_v4, /position_sizing, /evaluate_option, /debug/regime, /debug/scoring")

