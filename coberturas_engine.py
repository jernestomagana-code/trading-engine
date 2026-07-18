"""Coberturas RSP recommendation engine.

Read-only strategy support for the RSP coverage workflow. This module never
places orders and always returns execution_authorized=false.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
MANUAL_CONTEXT_PATH = RUNTIME / "coberturas_rsp_manual_context.json"
TICKER = "RSP"
TARGET_WEEKLY_PREMIUM = 100.0
MAX_CONTRACTS = 1
SHARES_PER_LOT = 100


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        number = safe_float(value, None)
        return int(number) if number is not None else default
    except Exception:
        return default


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_levels(raw: Any) -> list[float]:
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw or "").replace(";", ",").split(",")
    levels: list[float] = []
    for item in values:
        value = safe_float(item, None)
        if value is not None and value > 0:
            levels.append(round(value, 4))
    return sorted(set(levels))


def extract_numbers(raw: Any) -> list[float]:
    text = str(raw or "")
    values: list[float] = []
    for item in re.findall(r"[-+]?\d+(?:\.\d+)?", text):
        value = safe_float(item, None)
        if value is not None:
            values.append(value)
    return values


def parse_first_number_after(patterns: list[str], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            numbers = extract_numbers(match.group(1) if match.groups() else match.group(0))
            if numbers:
                return numbers[0]
    return None


def parse_levels_after(labels: list[str], text: str) -> list[float]:
    for label in labels:
        pattern = r"(?:{})(?:\s|:|=|-)+([^\n]+)".format(label)
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            levels = parse_levels(match.group(1))
            if levels:
                return levels
    return []




def flatten_numbers(value: Any) -> list[float]:
    out: list[float] = []
    if isinstance(value, dict):
        low = safe_float(value.get("low"), None)
        high = safe_float(value.get("high"), None)
        if low is not None and high is not None:
            out.append(round((low + high) / 2, 4))
        else:
            for item in value.values():
                out.extend(flatten_numbers(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(flatten_numbers(item))
    else:
        number = safe_float(value, None)
        if number is not None and number > 0:
            out.append(round(number, 4))
    return out


def parse_gamma_json_blob(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    technical = data.get("technical_levels") if isinstance(data.get("technical_levels"), dict) else {}
    gamma = data.get("gamma_context") if isinstance(data.get("gamma_context"), dict) else {}
    expected = data.get("expected_move") if isinstance(data.get("expected_move"), dict) else {}
    low = expected.get("low")
    high = expected.get("high")
    if isinstance(low, dict):
        low = low.get("2026-07-24") or low.get("all_expirations") or next(iter(low.values()), None)
    if isinstance(high, dict):
        high = high.get("2026-07-24") or high.get("all_expirations") or next(iter(high.values()), None)
    parsed = {
        "spot": safe_float(data.get("spot"), None),
        "support_levels": sorted(set(flatten_numbers(technical.get("supports")))),
        "resistance_levels": sorted(set(flatten_numbers(technical.get("resistances")))),
        "expected_move_low": safe_float(low, None),
        "expected_move_high": safe_float(high, None),
        "call_wall": safe_float(gamma.get("call_wall"), None),
        "put_wall": safe_float(gamma.get("put_wall"), None),
        "gamma_bias": safe_upper(gamma.get("bias"), "UNKNOWN"),
    }
    return {key: value for key, value in parsed.items() if value not in [None, [], "", "UNKNOWN"]}

def parse_gamma_blob(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    compact = re.sub(r"[ \t]+", " ", text)
    parsed: dict[str, Any] = {"gamma_blob": text}
    parsed.update(parse_gamma_json_blob(text))
    parsed["spot"] = parsed.get("spot") or parse_first_number_after(
        [
            r"\bspot(?:\s|:|=|-)+([0-9][0-9.,]*)",
            r"\bprecio(?:\s|:|=|-)+([0-9][0-9.,]*)",
            r"\bRSP(?:\s|:|=|-)+([0-9][0-9.,]*)",
        ],
        compact,
    )
    parsed["expected_move_low"] = parsed.get("expected_move_low") or parse_first_number_after(
        [
            r"(?:expected move|expected range|rango esperado|em)\s*(?:low|bajo|min|inferior)(?:\s|:|=|-)+([0-9][0-9.,]*)",
            r"(?:low|min|bajo)(?:\s|:|=|-)+([0-9][0-9.,]*).{0,40}(?:expected|em|rango)",
        ],
        compact,
    )
    parsed["expected_move_high"] = parsed.get("expected_move_high") or parse_first_number_after(
        [
            r"(?:expected move|expected range|rango esperado|em)\s*(?:high|alto|max|superior)(?:\s|:|=|-)+([0-9][0-9.,]*)",
            r"(?:high|max|alto)(?:\s|:|=|-)+([0-9][0-9.,]*).{0,40}(?:expected|em|rango)",
        ],
        compact,
    )
    expected_pair = re.search(
        r"(?:expected move|expected range|rango esperado|em)[^\n]{0,80}?([0-9]+(?:\.[0-9]+)?)[^\n]{1,20}([0-9]+(?:\.[0-9]+)?)",
        compact,
        flags=re.IGNORECASE,
    )
    if expected_pair and (parsed.get("expected_move_low") is None or parsed.get("expected_move_high") is None):
        pair = sorted(extract_numbers(expected_pair.group(0))[-2:])
        if len(pair) == 2:
            parsed["expected_move_low"] = parsed.get("expected_move_low") or pair[0]
            parsed["expected_move_high"] = parsed.get("expected_move_high") or pair[1]
    parsed["call_wall"] = parsed.get("call_wall") or parse_first_number_after([r"(?:call wall|wall call|callwall)(?:\s|:|=|-)+([0-9][0-9.,]*)"], compact)
    parsed["put_wall"] = parsed.get("put_wall") or parse_first_number_after([r"(?:put wall|wall put|putwall)(?:\s|:|=|-)+([0-9][0-9.,]*)"], compact)
    parsed["support_levels"] = parsed.get("support_levels") or parse_levels_after([r"soportes?", r"supports?", r"support levels?"], text)
    parsed["resistance_levels"] = parsed.get("resistance_levels") or parse_levels_after([r"resistencias?", r"resistance?s?", r"resistance levels?"], text)
    bias_match = re.search(r"(gamma|sesgo)[^\n]{0,30}\b(positivo|positive|negativo|negative|neutral|neutro)\b", compact, flags=re.IGNORECASE)
    if bias_match and not parsed.get("gamma_bias"):
        parsed["gamma_bias"] = bias_match.group(2).upper()
    return {key: value for key, value in parsed.items() if value not in [None, [], ""]}


def write_manual_context(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    path = path or MANUAL_CONTEXT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    gamma_blob = str(payload.get("gamma_blob") or "").strip()
    parsed = parse_gamma_blob(gamma_blob)
    context = {
        "context_version": "coberturas_rsp_manual_context_v1",
        "ticker": TICKER,
        "updated_at": now_iso(),
        "source": "manual_console_form",
        "spot": safe_float(payload.get("spot"), safe_float(parsed.get("spot"), None)),
        "position_mode": safe_upper(payload.get("position_mode"), "AUTO"),
        "gamma_blob": gamma_blob,
        "support_levels": parse_levels(payload.get("support_levels") or parsed.get("support_levels")),
        "resistance_levels": parse_levels(payload.get("resistance_levels") or parsed.get("resistance_levels")),
        "expected_move_low": safe_float(payload.get("expected_move_low"), safe_float(parsed.get("expected_move_low"), None)),
        "expected_move_high": safe_float(payload.get("expected_move_high"), safe_float(parsed.get("expected_move_high"), None)),
        "call_wall": safe_float(payload.get("call_wall"), safe_float(parsed.get("call_wall"), None)),
        "put_wall": safe_float(payload.get("put_wall"), safe_float(parsed.get("put_wall"), None)),
        "gamma_bias": safe_upper(payload.get("gamma_bias") or parsed.get("gamma_bias"), "UNKNOWN"),
        "gamma_notes": str(payload.get("gamma_notes") or "").strip(),
        "chart_notes": str(payload.get("chart_notes") or "").strip(),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return context


def load_manual_context(path: Path | None = None) -> dict[str, Any]:
    path = path or MANUAL_CONTEXT_PATH
    data = load_json(path)
    if not data:
        return {
            "context_version": "coberturas_rsp_manual_context_v1",
            "ticker": TICKER,
            "available": False,
            "support_levels": [],
            "resistance_levels": [],
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    data.setdefault("available", True)
    parsed = parse_gamma_blob(data.get("gamma_blob"))
    if not data.get("spot") and parsed.get("spot"):
        data["spot"] = parsed.get("spot")
    if not data.get("support_levels") and parsed.get("support_levels"):
        data["support_levels"] = parsed.get("support_levels")
    if not data.get("resistance_levels") and parsed.get("resistance_levels"):
        data["resistance_levels"] = parsed.get("resistance_levels")
    for key in ["expected_move_low", "expected_move_high", "call_wall", "put_wall"]:
        if data.get(key) in [None, "", []] and parsed.get(key) is not None:
            data[key] = parsed.get(key)
    if safe_upper(data.get("gamma_bias"), "UNKNOWN") == "UNKNOWN" and parsed.get("gamma_bias"):
        data["gamma_bias"] = parsed.get("gamma_bias")
    data.setdefault("support_levels", [])
    data.setdefault("resistance_levels", [])
    data.setdefault("execution_authorized", False)
    data.setdefault("not_order_instruction", True)
    data.setdefault("manual_review_required", True)
    return data


def scan_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from scan_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from scan_dicts(item)


def runtime_files(runtime_dir: Path) -> list[Path]:
    if not runtime_dir.exists():
        return []
    return sorted(runtime_dir.glob("*.json"))


def load_runtime_jsons(runtime_dir: Path = RUNTIME) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for path in runtime_files(runtime_dir):
        payload = load_json(path)
        if payload:
            data[path.name] = payload
    return data


def row_mid(row: dict[str, Any]) -> float | None:
    mid = safe_float(row.get("mid") or row.get("mark") or row.get("option_price"), None)
    if mid is not None and mid > 0:
        return mid
    bid = safe_float(row.get("bid"), None)
    ask = safe_float(row.get("ask"), None)
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        return round((bid + ask) / 2, 4)
    price = safe_float(row.get("price"), None)
    strike = safe_float(row.get("strike"), None)
    # Some runtime rows carry the underlying price in `price`; do not treat
    # a 200+ stock price as option premium.
    if price is not None and price > 0 and price < 50 and (strike is None or price < strike * 0.5):
        return price
    return None


def extract_option_rows(runtime_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_name, payload in runtime_data.items():
        if file_name == "coberturas_rsp_margin_preview_latest.json":
            continue
        for item in scan_dicts(payload):
            ticker = safe_upper(item.get("ticker") or item.get("symbol"), "")
            if ticker != TICKER:
                continue
            option_like = any(key in item for key in ["strike", "expiration", "expiry", "dte", "delta", "bid", "ask"])
            strategy_like = any(word in safe_upper(item.get("strategy") or item.get("strategy_hint"), "") for word in ["PUT", "CALL"])
            if not option_like and not strategy_like:
                continue
            row = dict(item)
            row["ticker"] = TICKER
            row["source_file"] = file_name
            row["strategy"] = safe_upper(row.get("strategy") or row.get("strategy_hint"), "UNKNOWN")
            row["expiration"] = row.get("expiration") or row.get("expiry") or row.get("exp")
            row["strike"] = safe_float(row.get("strike"), None)
            row["dte"] = safe_int(row.get("dte"), -1)
            row["delta"] = safe_float(row.get("delta"), None)
            row["bid"] = safe_float(row.get("bid"), None)
            row["ask"] = safe_float(row.get("ask"), None)
            row["mid"] = row_mid(row)
            row["premium_100"] = round(row["mid"] * 100, 2) if row.get("mid") is not None else None
            row["spread_pct"] = safe_float(row.get("spread_pct"), None)
            if row["spread_pct"] is None and row.get("bid") and row.get("ask") and row.get("mid"):
                row["spread_pct"] = round(((row["ask"] - row["bid"]) / row["mid"]) * 100, 2)
            row["open_interest"] = safe_float(row.get("open_interest") or row.get("oi"), None)
            row["volume"] = safe_float(row.get("volume"), None)
            row["not_order_instruction"] = True
            rows.append(row)
    priority = {
        "v32_ibkr_chain_coverage.json": 0,
        "decision_desk_snapshot.json": 1,
    }

    def row_quality(row: dict[str, Any]) -> int:
        score = 0
        if row.get("expiration"):
            score += 3
        if row.get("strike") is not None:
            score += 3
        if safe_int(row.get("dte"), -1) >= 0:
            score += 2
        if row.get("mid") is not None:
            score += 4
        if row.get("bid") is not None:
            score += 2
        if row.get("ask") is not None:
            score += 2
        if row.get("delta") is not None:
            score += 3
        if row.get("data_quality"):
            score += 1
        return score

    rows = sorted(
        rows,
        key=lambda row: (
            priority.get(str(row.get("source_file") or ""), 5),
            -row_quality(row),
        ),
    )
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get("strategy"), row.get("expiration"), row.get("strike"), candidate_side(row))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def extract_rsp_underlying_price(runtime_data: dict[str, Any], manual_context: dict[str, Any]) -> float | None:
    manual_spot = safe_float(manual_context.get("spot"), None)
    if manual_spot is not None:
        return manual_spot
    for payload in runtime_data.values():
        for item in scan_dicts(payload):
            ticker = safe_upper(item.get("ticker") or item.get("symbol"), "")
            if ticker == TICKER:
                price = safe_float(item.get("stock_price") or item.get("underlying_price") or item.get("spot") or item.get("price"), None)
                if price is not None and price > 0:
                    return price
    return None


def extract_position_state(runtime_data: dict[str, Any], manual_context: dict[str, Any]) -> dict[str, Any]:
    manual_mode = safe_upper(manual_context.get("position_mode"), "AUTO")
    if manual_mode not in {"", "AUTO", "UNKNOWN"}:
        mapping = {
            "NO_SHARES": "NO_SHARES",
            "SIN_ACCIONES": "NO_SHARES",
            "WITH_SHARES": "WITH_SHARES",
            "CON_ACCIONES": "WITH_SHARES",
            "SHORT_PUT_OPEN": "SHORT_PUT_OPEN",
            "PUT_ABIERTA": "SHORT_PUT_OPEN",
            "SHORT_CALL_OPEN": "SHORT_CALL_OPEN",
            "CALL_ABIERTA": "SHORT_CALL_OPEN",
        }
        return {
            "state": mapping.get(manual_mode, manual_mode),
            "source": "manual_context",
            "shares": None,
            "open_rsp_options": [],
        }

    shares = 0.0
    open_options: list[dict[str, Any]] = []
    for file_name, payload in runtime_data.items():
        # What-if margin previews are hypothetical orders, not positions.
        if file_name == "coberturas_rsp_margin_preview_latest.json":
            continue
        for item in scan_dicts(payload):
            ticker = safe_upper(item.get("ticker") or item.get("symbol"), "")
            if ticker != TICKER:
                continue
            sec_type = safe_upper(item.get("type") or item.get("secType") or item.get("security_type"), "")
            klass = safe_upper(item.get("class") or item.get("position_class") or item.get("strategy"), "")
            qty = safe_float(item.get("size") or item.get("position") or item.get("quantity") or item.get("qty"), None)
            if sec_type in {"STK", "STOCK", "ETF"} and qty is not None:
                shares += qty
            looks_like_position_option = sec_type in {"OPT", "OPTION"} or (qty is not None and ("PUT" in klass or "CALL" in klass))
            is_preview = item.get("what_if") is True or safe_upper(item.get("status"), "").startswith("MARGIN_PREVIEW")
            if looks_like_position_option and not is_preview:
                option = dict(item)
                option["source_file"] = file_name
                open_options.append(option)

    if any("SHORT_PUT" in safe_upper(item.get("class") or item.get("strategy"), "") for item in open_options):
        state = "SHORT_PUT_OPEN"
    elif any("SHORT_CALL" in safe_upper(item.get("class") or item.get("strategy"), "") for item in open_options):
        state = "SHORT_CALL_OPEN"
    elif shares >= 100:
        state = "WITH_SHARES"
    elif shares == 0 and runtime_data:
        state = "NO_SHARES"
    else:
        state = "UNKNOWN"

    return {
        "state": state,
        "source": "runtime_scan" if runtime_data else "missing_runtime",
        "shares": shares,
        "open_rsp_options": open_options[:10],
    }


def strategy_for_position(position_state: str) -> tuple[str, str]:
    if position_state == "NO_SHARES":
        return "SELL_PUT", "Sin acciones RSP: buscar venta de put asegurada por efectivo/margen."
    if position_state == "WITH_SHARES":
        return "SELL_COVERED_CALL", "Con 100+ acciones RSP: buscar covered call."
    if position_state in {"SHORT_PUT_OPEN", "SHORT_CALL_OPEN"}:
        return "MANAGE_OPEN_POSITION", "Hay opcion RSP abierta: revisar cierre, rolleo o asignacion antes de abrir otra."
    return "WAIT_DATA", "Falta confirmar si tienes acciones u opcion RSP abierta."


def candidate_side(row: dict[str, Any]) -> str:
    strategy = safe_upper(row.get("strategy"), "")
    right = safe_upper(row.get("right") or row.get("option_type"), "")
    local_symbol = safe_upper(row.get("local_symbol"), "")
    if "CALL" in strategy or right == "C" or " C" in local_symbol:
        return "CALL"
    if "PUT" in strategy or right == "P" or " P" in local_symbol:
        return "PUT"
    delta = safe_float(row.get("delta"), None)
    if delta is not None:
        return "PUT" if delta < 0 else "CALL"
    return "UNKNOWN"

def probability_from_delta(row: dict[str, Any], side: str) -> dict[str, Any]:
    delta = safe_float(row.get("delta"), None)
    if delta is None:
        return {
            "available": False,
            "method": "delta_missing",
            "probability_otm": None,
            "probability_assignment": None,
            "note": "IBKR no entrego delta; no se estima probabilidad.",
        }
    assignment = max(0.0, min(abs(delta), 0.99))
    return {
        "available": True,
        "method": "abs_delta_proxy",
        "probability_otm": round((1.0 - assignment) * 100, 2),
        "probability_assignment": round(assignment * 100, 2),
        "note": "Estimacion aproximada usando abs(delta), no garantia.",
    }


def option_premium(row: dict[str, Any]) -> float | None:
    if safe_upper(row.get("data_quality"), "") == "NO_VALID_OPTION_PRICE":
        return None
    premium = safe_float(row.get("premium_100"), None)
    if premium is not None and 0 < premium < 5000:
        return premium
    mid = row_mid(row)
    if mid is not None and mid > 0:
        return round(mid * SHARES_PER_LOT, 2)
    bid = safe_float(row.get("bid"), None)
    ask = safe_float(row.get("ask"), None)
    if bid is not None and ask is not None and ask >= bid:
        return round(((bid + ask) / 2) * SHARES_PER_LOT, 2)
    return None


def build_sell_put_scenario(row: dict[str, Any] | None, spot: float | None) -> dict[str, Any]:
    if not row:
        return {"available": False, "strategy": "SELL_PUT", "reason": "No hay put RSP candidata."}
    strike = safe_float(row.get("strike"), None)
    premium = option_premium(row)
    scenario = {
        "available": bool(strike and premium is not None),
        "strategy": "SELL_PUT",
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "strike": strike,
        "premium": premium,
        "premium_yield_on_cash_pct": round(premium / (strike * SHARES_PER_LOT) * 100, 2) if strike and premium is not None else None,
        "cash_secured_notional": round(strike * SHARES_PER_LOT, 2) if strike else None,
        "max_profit": premium,
        "breakeven": round(strike - premium / SHARES_PER_LOT, 2) if strike and premium is not None else None,
        "probability": probability_from_delta(row, "PUT"),
        "candidate": row,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return scenario


def build_buy_write_scenario(row: dict[str, Any] | None, spot: float | None) -> dict[str, Any]:
    if not row:
        return {"available": False, "strategy": "BUY_100_SELL_CALL", "reason": "No hay call RSP candidata."}
    strike = safe_float(row.get("strike"), None)
    premium = option_premium(row)
    stock_cost = round(spot * SHARES_PER_LOT, 2) if spot else None
    net_debit = round(stock_cost - premium, 2) if stock_cost is not None and premium is not None else None
    max_profit = round(max(0.0, (strike - spot) * SHARES_PER_LOT) + premium, 2) if strike and spot and premium is not None else None
    scenario = {
        "available": bool(strike and spot and premium is not None),
        "strategy": "BUY_100_SELL_CALL",
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "stock_entry": spot,
        "shares": SHARES_PER_LOT,
        "strike": strike,
        "premium": premium,
        "stock_cost": stock_cost,
        "net_debit": net_debit,
        "max_profit_if_called": max_profit,
        "max_profit_pct_on_net_debit": round(max_profit / net_debit * 100, 2) if max_profit is not None and net_debit else None,
        "breakeven": round(spot - premium / SHARES_PER_LOT, 2) if spot and premium is not None else None,
        "called_away_price": strike,
        "probability": probability_from_delta(row, "CALL"),
        "candidate": row,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return scenario


def first_scenario_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if row.get("strike") is not None and row.get("expiration") and option_premium(row) is not None:
            return row
    for row in rows:
        if row.get("strike") is not None and row.get("expiration"):
            return row
    return rows[0] if rows else None



def strategy_success_probability(scenario: dict[str, Any]) -> dict[str, Any]:
    probability = scenario.get("probability") if isinstance(scenario.get("probability"), dict) else {}
    if not probability.get("available"):
        return {
            "available": False,
            "target_outcome_probability": None,
            "target_outcome": "delta_missing",
            "note": "Falta delta; no se puede estimar probabilidad de exito.",
        }
    strategy = safe_upper(scenario.get("strategy"), "")
    if strategy == "SELL_PUT":
        return {
            "available": True,
            "target_outcome": "put_expires_otm",
            "target_outcome_probability": probability.get("probability_otm"),
            "assignment_probability": probability.get("probability_assignment"),
            "method": probability.get("method"),
        }
    if strategy == "BUY_100_SELL_CALL":
        return {
            "available": True,
            "target_outcome": "called_away_at_or_above_call_strike",
            "target_outcome_probability": probability.get("probability_assignment"),
            "keep_shares_probability": probability.get("probability_otm"),
            "method": probability.get("method"),
        }
    return probability


def gamma_alignment_for_scenario(scenario: dict[str, Any], manual_context: dict[str, Any]) -> dict[str, Any]:
    strike = safe_float(scenario.get("strike"), None)
    strategy = safe_upper(scenario.get("strategy"), "")
    supports = parse_levels(manual_context.get("support_levels"))
    resistances = parse_levels(manual_context.get("resistance_levels"))
    expected_low = safe_float(manual_context.get("expected_move_low"), None)
    expected_high = safe_float(manual_context.get("expected_move_high"), None)
    put_wall = safe_float(manual_context.get("put_wall"), None)
    call_wall = safe_float(manual_context.get("call_wall"), None)
    gamma_bias = safe_upper(manual_context.get("gamma_bias"), "UNKNOWN")
    checks: list[str] = []
    warnings: list[str] = []
    score = 0
    if strike is None:
        warnings.append("STRIKE_MISSING")
    elif strategy == "SELL_PUT":
        if supports and any(strike <= level for level in supports):
            checks.append("put strike below/at support")
            score += 1
        else:
            warnings.append("put strike not confirmed below support")
        if expected_low is not None and strike < expected_low:
            checks.append("put strike below expected move low")
            score += 1
        elif expected_low is not None:
            warnings.append("put strike inside expected move")
        if put_wall is not None and strike >= put_wall:
            checks.append("put strike near/above put wall")
    elif strategy == "BUY_100_SELL_CALL":
        if resistances and any(strike >= level for level in resistances):
            checks.append("call strike above/at resistance")
            score += 1
        else:
            warnings.append("call strike not confirmed above resistance")
        if expected_high is not None and strike > expected_high:
            checks.append("call strike above expected move high")
            score += 1
        elif expected_high is not None:
            warnings.append("call strike inside expected move")
        if call_wall is not None and strike >= call_wall:
            checks.append("call strike near/above call wall")
            score += 1
    if gamma_bias in {"POSITIVO", "POSITIVE"}:
        checks.append("positive gamma context favors range/mean-reversion discipline")
    elif gamma_bias in {"NEGATIVO", "NEGATIVE"}:
        warnings.append("negative gamma can increase move risk")
    status = "SUPPORTIVE" if score >= 2 else "MIXED" if score >= 1 else "WEAK_OR_MISSING"
    return {
        "status": status,
        "score": score,
        "checks": checks,
        "warnings": warnings,
        "manual_levels_used": {
            "support_levels": supports,
            "resistance_levels": resistances,
            "expected_move_low": expected_low,
            "expected_move_high": expected_high,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gamma_bias": gamma_bias,
        },
    }


def apply_probability_and_gamma(scenarios: dict[str, Any], manual_context: dict[str, Any]) -> dict[str, Any]:
    for scenario in scenarios.values():
        if not isinstance(scenario, dict):
            continue
        scenario["success_probability"] = strategy_success_probability(scenario)
        scenario["gamma_alignment"] = gamma_alignment_for_scenario(scenario, manual_context)
    return scenarios


def margin_decision_sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy = {row.get("strategy"): row for row in rows if isinstance(row, dict)}
    sell_put = by_strategy.get("SELL_PUT") or {}
    buy_write = by_strategy.get("BUY_100_SELL_CALL") or {}
    sp_profit = safe_float(sell_put.get("max_profit"), None)
    bw_profit = safe_float(buy_write.get("max_profit"), None)
    sp_capital = safe_float(sell_put.get("decision_capital_required"), None)
    bw_capital = safe_float(buy_write.get("decision_capital_required"), None)
    sp_return = safe_float(sell_put.get("decision_return_on_capital_pct"), None)
    bw_return = safe_float(buy_write.get("decision_return_on_capital_pct"), None)
    out = {
        "question": "Would real IBKR margin change the preferred strategy?",
        "current_basis": "decision_capital_required",
        "sell_put_current_return_pct": sp_return,
        "buy_write_current_return_pct": bw_return,
        "could_change_with_real_margin": None,
        "tie_margin_examples": {},
    }
    if sp_profit is not None and bw_return and bw_return > 0:
        out["tie_margin_examples"]["sell_put_margin_needed_to_tie_buy_write"] = round(sp_profit / (bw_return / 100), 2)
    if bw_profit is not None and sp_return and sp_return > 0:
        out["tie_margin_examples"]["buy_write_margin_needed_to_tie_sell_put"] = round(bw_profit / (sp_return / 100), 2)
    if sp_capital and bw_capital and sp_return is not None and bw_return is not None:
        gap = abs(bw_return - sp_return)
        out["could_change_with_real_margin"] = gap < 1.0
        out["note"] = (
            "Real margin could change decision only if it moves returns close enough to overcome the current return gap."
            if out["could_change_with_real_margin"]
            else "Current return gap is wide; real IBKR margin is still preferred, but unlikely to flip unless margin differs dramatically."
        )
    return out

def scenario_summary(put_rows: list[dict[str, Any]], call_rows: list[dict[str, Any]], spot: float | None) -> dict[str, Any]:
    best_put = first_scenario_candidate(put_rows)
    best_call = first_scenario_candidate(call_rows)
    return {
        "sell_put": build_sell_put_scenario(best_put, spot),
        "buy_100_sell_call": build_buy_write_scenario(best_call, spot),
    }


def margin_preview_by_strategy(margin_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    previews = margin_payload.get("previews") if isinstance(margin_payload.get("previews"), list) else []
    for item in previews:
        if not isinstance(item, dict):
            continue
        strategy = safe_upper(item.get("strategy") or item.get("label"), "")
        if strategy:
            out[strategy] = item
    return out


def margin_requirement(preview: dict[str, Any] | None) -> float | None:
    if not isinstance(preview, dict):
        return None
    for key in ["init_margin_change", "maint_margin_change"]:
        value = safe_float(preview.get(key), None)
        if value is not None:
            return abs(value)
    return None


def apply_margin_previews(scenarios: dict[str, Any], margin_payload: dict[str, Any], account_capacity: dict[str, Any]) -> dict[str, Any]:
    by_strategy = margin_preview_by_strategy(margin_payload)
    available_funds = safe_float(account_capacity.get("available_funds") or account_capacity.get("available_capacity"), None)
    buying_power = safe_float(account_capacity.get("buying_power"), None)
    mapping = {
        "sell_put": "SELL_PUT",
        "buy_100_sell_call": "BUY_100_SELL_CALL",
    }
    for scenario_key, preview_key in mapping.items():
        scenario = scenarios.get(scenario_key)
        if not isinstance(scenario, dict):
            continue
        preview = by_strategy.get(preview_key)
        req = margin_requirement(preview)
        max_profit = safe_float(scenario.get("max_profit") or scenario.get("max_profit_if_called"), None)
        scenario["margin_preview"] = preview or {
            "status": "MARGIN_PREVIEW_MISSING",
            "strategy": preview_key,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        scenario["ibkr_initial_margin_required"] = req
        scenario["ibkr_margin_preview_status"] = scenario["margin_preview"].get("status")
        scenario["return_on_margin_pct"] = (
            round(max_profit / req * 100, 2) if max_profit is not None and req and req > 0 else None
        )
        cash_base = safe_float(scenario.get("cash_secured_notional") or scenario.get("net_debit"), None)
        scenario["return_on_cash_or_debit_pct"] = (
            round(max_profit / cash_base * 100, 2) if max_profit is not None and cash_base and cash_base > 0 else None
        )
        decision_capital = req if req is not None else cash_base
        scenario["decision_capital_required"] = decision_capital
        scenario["decision_capital_source"] = "IBKR_WHAT_IF_MARGIN" if req is not None else "CONSERVATIVE_CASH_OR_DEBIT_FALLBACK"
        scenario["can_afford_by_available_funds"] = (
            available_funds >= decision_capital if available_funds is not None and decision_capital is not None else None
        )
        scenario["can_afford_by_buying_power"] = (
            buying_power >= decision_capital if buying_power is not None and decision_capital is not None else None
        )
        scenario["decision_return_on_capital_pct"] = (
            round(max_profit / decision_capital * 100, 2)
            if max_profit is not None and decision_capital and decision_capital > 0 else None
        )
    return scenarios


def scenario_data_warnings(scenario: dict[str, Any]) -> list[str]:
    candidate = scenario.get("candidate") if isinstance(scenario.get("candidate"), dict) else {}
    blockers = candidate.get("coberturas_blockers") if isinstance(candidate.get("coberturas_blockers"), list) else []
    warnings = []
    for key in ["MISSING_DELTA", "MISSING_SPREAD", "MISSING_PREMIUM", "PREMIUM_BELOW_TARGET", "SPREAD_TOO_WIDE"]:
        if key in blockers:
            warnings.append(key)
    if not scenario.get("available"):
        warnings.append("SCENARIO_DATA_INCOMPLETE")
    if scenario.get("ibkr_initial_margin_required") is None:
        warnings.append("IBKR_MARGIN_PREVIEW_MISSING")
    return sorted(set(warnings))


def build_strategy_recommendation(scenarios: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    sell_put = scenarios.get("sell_put") if isinstance(scenarios.get("sell_put"), dict) else {}
    buy_write = scenarios.get("buy_100_sell_call") if isinstance(scenarios.get("buy_100_sell_call"), dict) else {}
    options = [
        ("SELL_PUT", sell_put),
        ("BUY_100_SELL_CALL", buy_write),
    ]
    rows = []
    for strategy, scenario in options:
        margin = safe_float(scenario.get("ibkr_initial_margin_required"), None)
        decision_capital = safe_float(scenario.get("decision_capital_required"), None)
        max_profit = safe_float(scenario.get("max_profit") or scenario.get("max_profit_if_called"), None)
        return_margin = safe_float(scenario.get("return_on_margin_pct"), None)
        return_capital = safe_float(scenario.get("decision_return_on_capital_pct"), None)
        rows.append({
            "strategy": strategy,
            "available": bool(scenario.get("available")),
            "margin_available": margin is not None,
            "ibkr_initial_margin_required": margin,
            "decision_capital_required": decision_capital,
            "decision_capital_source": scenario.get("decision_capital_source"),
            "max_profit": max_profit,
            "return_on_margin_pct": return_margin,
            "decision_return_on_capital_pct": return_capital,
            "return_on_cash_or_debit_pct": scenario.get("return_on_cash_or_debit_pct"),
            "can_afford_by_available_funds": scenario.get("can_afford_by_available_funds"),
            "can_afford_by_buying_power": scenario.get("can_afford_by_buying_power"),
            "success_probability": scenario.get("success_probability"),
            "gamma_alignment": scenario.get("gamma_alignment"),
            "warnings": scenario_data_warnings(scenario),
        })

    comparable = [
        row for row in rows
        if row["available"]
        and row.get("decision_capital_required") is not None
        and row.get("decision_return_on_capital_pct") is not None
        and row.get("can_afford_by_buying_power") is not False
    ]
    if blockers:
        return {
            "status": "WAIT_DATA",
            "recommended_strategy": None,
            "reason": "Hay bloqueadores previos antes de comparar estrategia.",
            "blockers": blockers,
            "comparison": rows,
            "margin_decision_sensitivity": margin_decision_sensitivity(rows),
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    if len(comparable) < 2:
        capacity_blocked = [
            row
            for row in rows
            if row["available"]
            and row.get("decision_capital_required") is not None
            and (
                row.get("can_afford_by_buying_power") is False
                or row.get("can_afford_by_available_funds") is False
            )
        ]
        if capacity_blocked:
            required = [
                safe_float(row.get("decision_capital_required"), None)
                for row in capacity_blocked
            ]
            required = [value for value in required if value is not None]
            required_note = (
                " Capital requerido estimado: ${:,.2f} a ${:,.2f}.".format(min(required), max(required))
                if required
                else ""
            )
            return {
                "status": "WAIT_ACCOUNT_CAPACITY",
                "recommended_strategy": None,
                "reason": (
                    "El capital conservador si esta calculado, pero los fondos disponibles o el poder de compra "
                    "no alcanzan para comparar ambos caminos de forma operable."
                    + required_note
                ),
                "blockers": ["INSUFFICIENT_ACCOUNT_CAPACITY"],
                "comparison": rows,
                "margin_decision_sensitivity": margin_decision_sensitivity(rows),
                "execution_authorized": False,
                "not_order_instruction": True,
            }
        return {
            "status": "WAIT_CAPITAL_DATA",
            "recommended_strategy": None,
            "reason": "Falta margen IBKR y tampoco hay capital/debito conservador suficiente para comparar ambos caminos.",
            "blockers": ["CAPITAL_DATA_MISSING"],
            "comparison": rows,
            "margin_decision_sensitivity": margin_decision_sensitivity(rows),
            "execution_authorized": False,
            "not_order_instruction": True,
        }

    best = sorted(
        comparable,
        key=lambda row: (
            safe_float(row.get("decision_return_on_capital_pct"), -999),
            safe_float(row.get("max_profit"), -999),
        ),
        reverse=True,
    )[0]
    other = [row for row in comparable if row["strategy"] != best["strategy"]][0]
    sensitivity = margin_decision_sensitivity(rows)
    missing_ibkr_margin = any(not row.get("margin_available") for row in comparable)
    conditional = bool(best.get("warnings") or other.get("warnings") or missing_ibkr_margin)
    status = "RECOMMEND_{}_CONDITIONAL".format(best["strategy"])
    if missing_ibkr_margin:
        status = "RECOMMEND_{}_CONDITIONAL_ESTIMATED_CAPITAL".format(best["strategy"])
    elif not conditional:
        status = "RECOMMEND_{}_MANUAL_REVIEW".format(best["strategy"])
    reason = (
        "{} ofrece mejor retorno potencial sobre capital usado para decision: {}% vs {}%."
        .format(best["strategy"], best.get("decision_return_on_capital_pct"), other.get("decision_return_on_capital_pct"))
    )
    if missing_ibkr_margin:
        reason += " IBKR no devolvio margen what-if completo; use capital/debito conservador como fallback."
    if conditional:
        reason += " Recomendacion condicionada porque faltan delta/spread, margen IBKR completo o calidad de datos ejecutables."
    return {
        "status": status,
        "recommended_strategy": best["strategy"],
        "reason": reason,
        "comparison": rows,
        "margin_decision_sensitivity": sensitivity,
        "conditional": conditional,
        "warnings": sorted(set(best.get("warnings") or [])),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def score_candidate(row: dict[str, Any], mode: str, spot: float | None, manual_context: dict[str, Any]) -> dict[str, Any]:
    side = candidate_side(row)
    score = 50.0
    reasons: list[str] = []
    blockers: list[str] = []
    mid = safe_float(row.get("mid"), None)
    premium = safe_float(row.get("premium_100"), None)
    dte = safe_int(row.get("dte"), -1)
    delta = safe_float(row.get("delta"), None)
    strike = safe_float(row.get("strike"), None)
    spread_pct = safe_float(row.get("spread_pct"), None)

    expected_side = "PUT" if mode == "SELL_PUT" else "CALL" if mode == "SELL_COVERED_CALL" else "UNKNOWN"
    if expected_side != "UNKNOWN" and side != expected_side:
        blockers.append("WRONG_OPTION_SIDE_FOR_MODE")
        score -= 35
    else:
        reasons.append("lado correcto para el modo")
        score += 8

    if 7 <= dte <= 14:
        score += 16
        reasons.append("DTE en ventana 7-14 dias")
    elif 4 <= dte < 7 or 15 <= dte <= 21:
        score += 5
        reasons.append("DTE cercano a ventana")
    else:
        score -= 12
        blockers.append("DTE_OUTSIDE_TARGET_WINDOW")

    if delta is not None:
        abs_delta = abs(delta)
        if 0.10 <= abs_delta <= 0.30:
            score += 16
            reasons.append("delta en rango conservador")
        elif 0.30 < abs_delta <= 0.40:
            score += 2
            reasons.append("delta mas agresiva")
        else:
            score -= 10
            blockers.append("DELTA_OUTSIDE_TARGET")
    else:
        blockers.append("MISSING_DELTA")
        score -= 8

    if premium is not None:
        premium_gap = abs(premium - TARGET_WEEKLY_PREMIUM)
        if premium >= TARGET_WEEKLY_PREMIUM:
            score += 14
            reasons.append("prima cumple meta semanal")
        elif premium >= 60:
            score += 5
            reasons.append("prima aceptable sin forzar")
        else:
            score -= 8
            blockers.append("PREMIUM_BELOW_TARGET")
        if premium_gap <= 25:
            score += 4
    elif mid is None:
        blockers.append("MISSING_PREMIUM")
        score -= 12

    if spread_pct is not None:
        if spread_pct <= 18:
            score += 8
            reasons.append("spread razonable")
        else:
            score -= 12
            blockers.append("SPREAD_TOO_WIDE")
    else:
        blockers.append("MISSING_SPREAD")
        score -= 6

    supports = parse_levels(manual_context.get("support_levels"))
    resistances = parse_levels(manual_context.get("resistance_levels"))
    expected_low = safe_float(manual_context.get("expected_move_low"), None)
    expected_high = safe_float(manual_context.get("expected_move_high"), None)
    put_wall = safe_float(manual_context.get("put_wall"), None)
    call_wall = safe_float(manual_context.get("call_wall"), None)

    if strike is not None:
        if mode == "SELL_PUT":
            below_supports = [level for level in supports if strike <= level]
            if below_supports:
                score += 12
                reasons.append("strike debajo/de soporte manual")
            if expected_low is not None and strike < expected_low:
                score += 8
                reasons.append("strike debajo del expected move bajo")
            if put_wall is not None and strike >= put_wall:
                score += 4
                reasons.append("strike sobre put wall, revisar soporte institucional")
        elif mode == "SELL_COVERED_CALL":
            above_resistances = [level for level in resistances if strike >= level]
            if above_resistances:
                score += 12
                reasons.append("strike sobre/de resistencia manual")
            if expected_high is not None and strike > expected_high:
                score += 8
                reasons.append("strike sobre expected move alto")
            if call_wall is not None and strike >= call_wall:
                score += 4
                reasons.append("strike en/sobre call wall")
        if spot is not None:
            distance_pct = abs(strike - spot) / spot * 100
            row["distance_pct"] = round(distance_pct, 2)
            if distance_pct >= 1.0:
                score += min(8, distance_pct)
            else:
                score -= 8
                blockers.append("STRIKE_TOO_CLOSE_TO_SPOT")

    confidence = "HIGH" if score >= 82 and not blockers else "MEDIUM" if score >= 65 else "LOW"
    enriched = dict(row)
    enriched.update({
        "side": side,
        "coberturas_score": round(max(0, min(score, 100)), 2),
        "coberturas_confidence": confidence,
        "coberturas_reasons": reasons,
        "coberturas_blockers": blockers,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    })
    return enriched


def build_recommendation(runtime_dir: Path = RUNTIME) -> dict[str, Any]:
    manual_context = load_manual_context()
    runtime_data = load_runtime_jsons(runtime_dir)
    option_rows = extract_option_rows(runtime_data)
    spot = extract_rsp_underlying_price(runtime_data, manual_context)
    position = extract_position_state(runtime_data, manual_context)
    mode, mode_reason = strategy_for_position(position.get("state"))

    put_candidates = [
        score_candidate(row, "SELL_PUT", spot, manual_context)
        for row in option_rows
        if candidate_side(row) == "PUT"
    ]
    call_candidates = [
        score_candidate(row, "SELL_COVERED_CALL", spot, manual_context)
        for row in option_rows
        if candidate_side(row) == "CALL"
    ]
    put_candidates = sorted(put_candidates, key=lambda row: safe_float(row.get("coberturas_score"), 0), reverse=True)
    call_candidates = sorted(call_candidates, key=lambda row: safe_float(row.get("coberturas_score"), 0), reverse=True)

    if mode == "SELL_PUT":
        candidate_rows = put_candidates
    elif mode == "SELL_COVERED_CALL":
        candidate_rows = call_candidates
    else:
        candidate_rows = []

    account_capacity = load_json(runtime_dir / "ibkr_account_capacity_latest.json")
    margin_preview = load_json(runtime_dir / "coberturas_rsp_margin_preview_latest.json")
    scenarios = apply_probability_and_gamma(
        apply_margin_previews(
            scenario_summary(put_candidates, call_candidates, spot),
            margin_preview,
            account_capacity,
        ),
        manual_context,
    )

    blockers: list[str] = []
    if position.get("state") == "UNKNOWN":
        blockers.append("POSITION_STATE_UNKNOWN")
    if spot is None:
        blockers.append("RSP_SPOT_MISSING")
    if mode in {"SELL_PUT", "SELL_COVERED_CALL"} and not option_rows:
        blockers.append("RSP_OPTION_CHAIN_MISSING")
    if mode in {"SELL_PUT", "SELL_COVERED_CALL"} and not manual_context.get("available"):
        blockers.append("MANUAL_GAMMA_CONTEXT_MISSING")
    if mode == "MANAGE_OPEN_POSITION":
        blockers.append("OPEN_RSP_OPTION_REQUIRES_MANAGEMENT")

    strategy_recommendation = build_strategy_recommendation(scenarios, blockers)

    if mode == "SELL_PUT" and put_candidates and call_candidates:
        recommendation_status = str(strategy_recommendation.get("status") or "")
        if recommendation_status.startswith("RECOMMEND_"):
            decision = recommendation_status
            next_action = strategy_recommendation.get("reason") or "Revisar recomendacion comparativa antes de preparar orden manual."
        elif recommendation_status in {"WAIT_MARGIN_PREVIEW", "WAIT_CAPITAL_DATA", "WAIT_ACCOUNT_CAPACITY"}:
            decision = recommendation_status
            next_action = strategy_recommendation.get("reason") or "Refrescar margen IBKR para comparar caminos."
        else:
            decision = "REVIEW_RSP_COVERAGE_PATHS"
            next_action = "Comparar vender put contra comprar 100 acciones y vender call; confirmar datos faltantes antes de preparar orden manual."
    elif mode == "SELL_PUT" and candidate_rows:
        decision = "REVIEW_SELL_PUT_CANDIDATES"
        next_action = "Revisar candidatos de put, confirmar gamma/niveles y preparar orden manual solo si el strike sigue valido."
    elif mode == "SELL_COVERED_CALL" and candidate_rows:
        decision = "REVIEW_COVERED_CALL_CANDIDATES"
        next_action = "Revisar candidatos de covered call y confirmar que aceptar asignacion/salida sea correcto."
    elif mode == "MANAGE_OPEN_POSITION":
        decision = "MANAGE_EXISTING_RSP_OPTION"
        next_action = "No abrir nueva cobertura; revisar cierre, rolleo o asignacion de la opcion RSP abierta."
    else:
        decision = "WAIT_DATA"
        next_action = "Cargar gamma/niveles manuales y refrescar bridge IBKR con RSP incluido."

    if blockers:
        decision = "WAIT_DATA" if decision.startswith("REVIEW") else decision

    chain_coverage = load_json(runtime_dir / "v32_ibkr_chain_coverage.json")

    return {
        "engine": "COBERTURAS_RSP_V0",
        "generated_at": now_iso(),
        "ticker": TICKER,
        "status": "OK",
        "decision": decision,
        "mode": mode,
        "mode_reason": mode_reason,
        "position": position,
        "spot": spot,
        "manual_context": manual_context,
        "candidate_count": len(candidate_rows),
        "top_candidates": candidate_rows[:5],
        "put_candidate_count": len(put_candidates),
        "call_candidate_count": len(call_candidates),
        "top_put_candidates": put_candidates[:5],
        "top_call_candidates": call_candidates[:5],
        "strategy_scenarios": scenarios,
        "strategy_recommendation": strategy_recommendation,
        "margin_preview": margin_preview,
        "all_rsp_option_rows_found": len(option_rows),
        "blockers": blockers,
        "next_action": next_action,
        "risk_limits": {
            "max_contracts": MAX_CONTRACTS,
            "target_weekly_premium": TARGET_WEEKLY_PREMIUM,
            "buy_write_supported": True,
            "sell_put_supported": True,
            "underlying_only": TICKER,
            "real_account_read_only_recommendation": True,
        },
        "ibkr": {
            "account_capacity_available": bool(account_capacity.get("available")),
            "available_funds": account_capacity.get("available_funds"),
            "buying_power": account_capacity.get("buying_power"),
            "chain_has_rsp": TICKER in ((chain_coverage.get("chain_by_ticker") or {}).keys()),
            "chain_coverage_generated_at": chain_coverage.get("generated_at"),
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
