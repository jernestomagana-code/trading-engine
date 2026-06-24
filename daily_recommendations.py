"""Daily multi-strategy recommendation contract for Stock Ultimus."""

from __future__ import annotations

from typing import Any


RECOMMENDATION_VERSION = "daily_recommendation_v1"
STATE_PRIORITY = {
    "ENTRY_READY": 1000,
    "MANUAL_REVIEW": 850,
    "WAIT_OPTIONS_DATA": 700,
    "WAIT_TECHNICAL": 520,
    "WAIT_MARKET": 420,
    "WAIT_ACCOUNT_CONTEXT": 300,
    "RISK_BLOCKED": 120,
    "NO_DATA": 0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _technical(decision: dict[str, Any]) -> dict[str, Any]:
    technical = decision.get("technical") if isinstance(decision.get("technical"), dict) else {}
    raw = technical.get("raw") if isinstance(technical.get("raw"), dict) else {}
    return {
        "status": decision.get("technical_status"),
        "confirmed": bool(technical.get("confirmed")),
        "score": technical.get("score"),
        "trend": technical.get("trend"),
        "strategy_context": technical.get("strategy_context"),
        "available_strategy_contexts": technical.get("available_strategy_contexts") or [],
        "raw_fields_present": sorted([key for key in raw.keys() if key not in {"account", "token", "secret"}])[:50],
    }


def _fundamental(decision: dict[str, Any]) -> dict[str, Any]:
    technical = decision.get("technical") if isinstance(decision.get("technical"), dict) else {}
    raw = technical.get("raw") if isinstance(technical.get("raw"), dict) else {}
    canslim = raw.get("canslim") if isinstance(raw.get("canslim"), dict) else {}
    fundamental = raw.get("fundamental") if isinstance(raw.get("fundamental"), dict) else {}
    return {
        "canslim": {
            "available": bool(canslim),
            "passes": canslim.get("passes"),
            "score": canslim.get("score") or canslim.get("rating_score"),
            "rating": canslim.get("rating"),
        },
        "fundamental": {
            "available": bool(fundamental),
            "summary": {
                key: fundamental.get(key)
                for key in ["eps_growth", "sales_growth", "roe", "debt_to_equity", "institutional_ownership"]
                if key in fundamental
            },
        },
    }


def _options(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision.get("selected_contract") if isinstance(decision.get("selected_contract"), dict) else {}
    return {
        "status": decision.get("construction_status"),
        "score": decision.get("options_score"),
        "contract": {
            "ticker": contract.get("ticker"),
            "strategy": contract.get("strategy"),
            "strike": contract.get("strike"),
            "expiration": contract.get("expiration"),
            "dte": contract.get("dte"),
            "bid": contract.get("bid"),
            "ask": contract.get("ask"),
            "mid": contract.get("mid"),
            "spread": contract.get("spread"),
            "spread_pct": contract.get("spread_pct"),
            "delta": contract.get("delta"),
            "iv": contract.get("iv"),
            "volume": contract.get("volume"),
            "open_interest": contract.get("open_interest"),
            "quality": contract.get("quality"),
        },
    }


def _risk_profile(decision: dict[str, Any]) -> dict[str, Any]:
    risk_profile = decision.get("risk_profile") if isinstance(decision.get("risk_profile"), dict) else {}
    blocked_checks = risk_profile.get("blocked_checks")
    if not isinstance(blocked_checks, list):
        blocked_checks = []
    return {
        "status": risk_profile.get("status"),
        "primary_blocker": risk_profile.get("primary_blocker") or decision.get("risk_blocker"),
        "blockers": risk_profile.get("blockers") or [],
        "blocked_checks": blocked_checks,
        "notes": risk_profile.get("notes") or [],
        "not_order_instruction": True,
    }


def _broker_check(decision: dict[str, Any]) -> dict[str, Any]:
    broker = decision.get("broker_check") if isinstance(decision.get("broker_check"), dict) else {}
    return {
        "status": broker.get("status"),
        "ok_for_manual_review": broker.get("ok_for_manual_review"),
        "blockers": broker.get("blockers") or [],
        "warnings": broker.get("warnings") or [],
        "checks": broker.get("checks") or [],
        "manual_broker_ticket_still_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def action_for_state(state: str) -> str:
    return {
        "ENTRY_READY": "REVIEW_MANUALLY",
        "MANUAL_REVIEW": "REVIEW_MANUALLY",
        "WAIT_OPTIONS_DATA": "WAIT_FOR_EXECUTABLE_OPTION_DATA",
        "WAIT_TECHNICAL": "WAIT_FOR_TECHNICAL_CONFIRMATION",
        "WAIT_MARKET": "WAIT_FOR_MARKET_WINDOW",
        "WAIT_ACCOUNT_CONTEXT": "WAIT_FOR_ACCOUNT_CONTEXT",
        "RISK_BLOCKED": "DO_NOT_TRADE_RISK_BLOCKED",
        "NO_DATA": "NO_TRADE_NO_DATA",
    }.get(state, "NO_TRADE_UNCLASSIFIED")


def instruction_for_state(state: str, ticker: str, strategy: str) -> str:
    if state == "ENTRY_READY":
        return f"{ticker}: {strategy} listo solo para revision manual; validar tamano, liquidez, evento y riesgo antes de decidir."
    if state == "MANUAL_REVIEW":
        return f"{ticker}: revisar manualmente; la oportunidad no autoriza ejecucion."
    if state == "WAIT_OPTIONS_DATA":
        return f"{ticker}: esperar bid/ask/spread/delta/DTE/strike/expiration completos antes de evaluar entrada."
    if state == "WAIT_TECHNICAL":
        return f"{ticker}: esperar confirmacion tecnica alineada con {strategy}."
    if state == "WAIT_MARKET":
        return f"{ticker}: esperar ventana confiable de mercado/opciones."
    if state == "RISK_BLOCKED":
        return f"{ticker}: no operar; riesgo o reglas bloquean la idea."
    if state == "WAIT_ACCOUNT_CONTEXT":
        return f"{ticker}: esperar contexto de cuenta/posicion antes de decidir."
    return f"{ticker}: sin datos suficientes; no operar."


def conviction_score(decision: dict[str, Any]) -> float:
    state = _upper(decision.get("final_state"), "NO_DATA")
    score = float(STATE_PRIORITY.get(state, 0))
    technical = decision.get("technical") if isinstance(decision.get("technical"), dict) else {}
    score += min(max(_number(technical.get("score"), 0), 0), 100)
    score += min(max(_number(decision.get("options_score"), 0), 0), 100)
    if technical.get("confirmed") is True:
        score += 50
    if decision.get("manual_review_ready") is True:
        score += 100
    score -= 25 * len(decision.get("required_missing_fields") or [])
    score -= 15 * len(decision.get("blockers") or [])
    if state == "RISK_BLOCKED":
        score -= 300
    return round(score, 2)


def recommendation_item(decision: dict[str, Any], rank: int) -> dict[str, Any]:
    state = _upper(decision.get("final_state"), "NO_DATA")
    ticker = _upper(decision.get("ticker"), "UNKNOWN")
    strategy = _upper(decision.get("strategy"), "UNKNOWN")
    score = conviction_score(decision)
    risk_profile = _risk_profile(decision)
    broker_check = _broker_check(decision)
    item = {
        "rank": rank,
        "ticker": ticker,
        "strategy": strategy,
        "final_state": state,
        "recommendation_action": action_for_state(state),
        "conviction_score": score,
        "manual_review_required": True,
        "manual_review_ready": bool(decision.get("manual_review_ready")),
        "can_operate": False,
        "not_order_instruction": True,
        "main_blocker": decision.get("main_blocker"),
        "blockers": decision.get("blockers") or [],
        "required_missing_fields": decision.get("required_missing_fields") or [],
        "instruction": instruction_for_state(state, ticker, strategy),
        "why": decision.get("explanation"),
        "risk_note": decision.get("risk_note") or "Decision support solamente; no es orden ni autorizacion de ejecucion.",
        "risk_profile": risk_profile,
        "broker_check": broker_check,
        "risk_blocker": decision.get("risk_blocker"),
        "risk_blocked_details": decision.get("risk_blocked_details") or risk_profile.get("blocked_checks") or [],
        "evidence": {
            "technical": _technical(decision),
            "fundamental": _fundamental(decision),
            "options": _options(decision),
            "broker": broker_check,
            "market": decision.get("market") if isinstance(decision.get("market"), dict) else {},
        },
        "source": {
            "decision_version": decision.get("decision_version"),
            "strategy_version": decision.get("strategy_version"),
            "ruleset_version": decision.get("ruleset_version"),
            "snapshot_version": decision.get("snapshot_version"),
            "master_source": decision.get("master_source"),
        },
    }
    return item


def build_daily_recommendations(
    decisions: list[dict[str, Any]],
    *,
    generated_at: str,
    market: dict[str, Any] | None = None,
    risk_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_items = [recommendation_item(decision, 0) for decision in decisions]
    sorted_items = sorted(raw_items, key=lambda item: item["conviction_score"], reverse=True)
    for idx, item in enumerate(sorted_items, start=1):
        item["rank"] = idx

    actionable = [
        item for item in sorted_items
        if item["final_state"] in {"ENTRY_READY", "MANUAL_REVIEW", "WAIT_OPTIONS_DATA", "WAIT_TECHNICAL"}
    ]
    no_trade = [
        item for item in sorted_items
        if item["recommendation_action"].startswith("NO_TRADE") or item["final_state"] == "RISK_BLOCKED"
    ]
    summary = {
        "total": len(sorted_items),
        "manual_review_ready": sum(1 for item in sorted_items if item["manual_review_ready"]),
        "entry_ready": sum(1 for item in sorted_items if item["final_state"] == "ENTRY_READY"),
        "wait_options_data": sum(1 for item in sorted_items if item["final_state"] == "WAIT_OPTIONS_DATA"),
        "wait_technical": sum(1 for item in sorted_items if item["final_state"] == "WAIT_TECHNICAL"),
        "wait_market": sum(1 for item in sorted_items if item["final_state"] == "WAIT_MARKET"),
        "wait_account_context": sum(1 for item in sorted_items if item["final_state"] == "WAIT_ACCOUNT_CONTEXT"),
        "risk_blocked": sum(1 for item in sorted_items if item["final_state"] == "RISK_BLOCKED"),
        "no_data": sum(1 for item in sorted_items if item["final_state"] == "NO_DATA"),
    }

    return {
        "engine": "V31_DAILY_RECOMMENDATION_ENGINE",
        "recommendation_version": RECOMMENDATION_VERSION,
        "generated_at": generated_at,
        "status": "OK",
        "market": market or {},
        "risk_profile": risk_profile or {},
        "summary": summary,
        "top_recommendations": actionable[:10],
        "no_trade": no_trade[:25],
        "items": sorted_items,
        "research_overlay": {
            "status": "RULES_ONLY",
            "detail": "Research ideas must be converted into versioned, testable rules before affecting recommendations.",
        },
        "manual_review_required": True,
        "can_operate": False,
        "not_order_instruction": True,
    }
