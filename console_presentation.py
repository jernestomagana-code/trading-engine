"""Shared presentation vocabulary and identities. Never authorizes broker actions."""
from typing import Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import re

FRIENDLY_OPERATOR_STATES = {
    "WAIT_MARKET": "Esperando nuevas señales",
    "WAIT_DATA": "Faltan datos",
    "WAIT_NO_ELIGIBLE_STRUCTURE": "Esperar: ninguna estructura cumple",
    "WAIT_ACCOUNT_CAPACITY": "Capacidad de cuenta insuficiente",
    "WAIT_MARGIN_PREVIEW": "Margen IBKR pendiente",
    "WAIT_CAPITAL_DATA": "Datos de capital pendientes",
    "COVERED_CALL_OPEN": "Covered call abierto",
    "SHORT_CALL_OPEN": "Call vendida abierta",
    "SHORT_PUT_OPEN": "Put vendida abierta",
    "READY_FOR_MANUAL_REVIEW": "Listo para revisión manual",
    "ACTION_REQUIRED": "Atención requerida",
    "REVIEW_REQUIRED": "Revisión necesaria",
    "REVIEW_RISK": "Revisar riesgo",
    "REVIEW_DEFENSIVE_EXIT": "Revisar defensa",
    "RISK_REVIEW": "Revisión de riesgo",
    "REVIEW_ASSIGNMENT": "Revisar posible asignación",
    "REVIEW_CLOSE_OR_BUY_BACK": "Revisar cierre o recompra",
    "REVIEW_ROLL": "Revisar rolleo",
    "REFRESH_DATA": "Actualizar datos",
    "ASSIGNMENT_REVIEW": "Revisar asignación",
    "TAKE_PROFIT_REVIEW": "Revisar toma de ganancia",
    "NO_ACTION_RECOMMENDED": "Mantener sin cambios",
    "NO_POSITION": "Sin posición abierta",
    "FRESH": "Actualizados",
    "STALE": "Desactualizados",
    "READY_FOR_DECISION_REVIEW": "Listo para revisar decisiones",
    "NO_NEW_RISK": "No aumentar riesgo",
    "WATCH": "Vigilancia",
    "MONITOR": "Monitoreo",
    "BLOCKED": "Bloqueado",
    "SELL_PUT": "Venta de put",
    "SELL_COVERED_CALL": "Covered call",
    "CASH_SECURED_PUT": "Put garantizada con efectivo",
    "NAKED_PUT": "Venta de put",
    "COVERED_CALL": "Covered call",
    "LONG_CALL": "Call comprada",
    "LONG_PUT": "Put comprada",
    "MANAGE_COVERED_CALL": "Gestionar covered call abierto",
    "MANAGE_EXISTING_AND_WAIT_NEW_ENTRY_DATA": "Gestionar la posición actual y esperar datos para una nueva entrada",
    "FULLY_COVERED_CALL": "Covered call completo",
    "PARTIAL_COVERED_CALL": "Covered call parcial",
    "LONG_STOCK": "Acciones compradas",
    "FUTURES_POSITION": "Posición de futuros",
    "STK": "Acciones",
    "FUT": "Futuro",
    "OPT": "Opción",
    "WATCH_ONLY": "Sólo vigilancia",
    "ENTRY_COMPARISON_MODE": "Comparar alternativas de entrada",
    "NO_SHARES": "Sin acciones RSP",
    "ACUMULANDO EVIDENCIA": "Aprendizaje en curso",
}

FRIENDLY_OPERATOR_STATES.update({'NO_DATA': 'Faltan datos para evaluar', 'UNKNOWN': 'Sin información confirmada', 'HIGH': 'Alta', 'LOW': 'Baja', 'MEDIUM': 'Media', 'OPEN': 'Pendiente de revisión', 'HOLD': 'Mantener sin cambios', 'FUTURES_RATIO_CALENDAR_SPREAD': 'Spread calendario de futuros en proporción', 'FUTURES_CALENDAR_SPREAD': 'Spread calendario de futuros', 'RSP_FRESH_CHAIN_MISSING': 'Actualizar la cadena de opciones RSP', 'HISTORICAL_EXPIRED_OPTION_BACKFILL': 'Falta historial de opciones vencidas', 'LIQUID_LONG_DATED_GRID_INCOMPLETE': 'Faltan cotizaciones líquidas de largo plazo', 'DATA_COLLECTION_REQUIRED': 'Recopilación de datos en curso', 'RESEARCH_ONLY': 'Sólo investigación', 'PAPER_ELIGIBLE': 'Sólo evaluación simulada', 'PASS': 'Cumple preselección', 'LEADER': 'Líder en preselección'})


FRIENDLY_OPERATOR_STATES.update({
    "WITH_SHARES": "Acciones en cartera",
    "READY_FOR_COVERED_CALL_MANAGEMENT": "Revisar cobertura de las acciones",
    "MANAGE_SHORT_CALL": "Gestionar la call vendida",
    "MANAGE_SHORT_PUT": "Gestionar la put vendida",
    "BUY_100_SELL_CALL": "Comprar 100 acciones y vender una call",
    "MIXED": "Mixta",
    "PRIORITIZE COVERED CALL MANAGEMENT OVER NAKED PUT ENTRY.": "Priorizar la gestión de las acciones y su cobertura antes de evaluar una put vendida sin cobertura.",
    "COMPARE SELL PUT VS BUY-WRITE; USE RECOMMENDATION, EV, GAMMA AND CAPACITY CHECKS.": "Comparar venta de put con compra de acciones y venta de call; revisar recomendación, valor esperado, gamma y capacidad.",
    "DO NOT OPEN A NEW RSP TRADE; EVALUATE CLOSE, ROLL, OR ASSIGNMENT PLAN.": "Revisar cierre, rolleo o asignación de la put actual antes de abrir otra operación RSP.",
    "MANAGE THE EXISTING COVERED CALL; DO NOT OPEN ANOTHER RSP CALL.": "Gestionar el covered call actual antes de abrir otra call RSP.",
    "DO NOT SELL ANOTHER CALL; MANAGE SHORT CALL EXPOSURE FIRST.": "Gestionar primero la exposición de la call vendida antes de vender otra.",
    "EVALUATE NEW ENTRY ONLY IF DATA QUALITY AND MANUAL REVIEW ARE ACCEPTABLE.": "Evaluar una nueva entrada sólo con datos suficientes y revisión manual.",
})


def friendly_operator_state(value: Any, fallback: str = "Pendiente") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    friendly = FRIENDLY_OPERATOR_STATES.get(raw.upper())
    if friendly:
        return friendly
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", raw) and "_" in raw:
        return "Revisar detalle; estado pendiente de interpretación"
    label = raw.replace("_", " ").strip()
    return label[:1].upper() + label[1:]


def reviewed_today(value, now=None):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        current = now or datetime.now(timezone.utc)
        return stamp <= current and stamp.astimezone(ZoneInfo("America/Mexico_City")).date() == current.astimezone(ZoneInfo("America/Mexico_City")).date()
    except (ValueError, TypeError):
        return False

def position_anchor(item):
    identity = [item.get(k) for k in ("account_alias", "account_scope", "position_id", "con_id", "ticker", "strategy", "expiration", "strike", "right")]
    return "position-" + hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()[:16]

def position_plan(item):
    alternatives = item.get("management_alternatives") or {}
    recommendation = alternatives.get("recommendation") or {}
    # Present the engine's selected alternative as the plan, preserving review priority separately.
    return recommendation.get("label") or friendly_operator_state(item.get("management_action"))

def case_identity(row):
    account = row.get("account_alias") or row.get("account_scope")
    cycle = row.get("trade_id") or row.get("trade_cycle_id")
    return (str(account), str(cycle)) if account and cycle else None
