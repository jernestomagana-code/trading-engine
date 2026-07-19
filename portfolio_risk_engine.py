"""Explainable, read-only portfolio risk evaluation for sanitized broker snapshots."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower


RISK_ENGINE_VERSION = "stock_ultimus_portfolio_risk_engine_v1"
SEVERITY_ORDER = {"INFO": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "stock_ultimus_portfolio_risk_policy_v1",
    "max_data_age_minutes": 15,
    "thresholds": {
        "excess_liquidity_ratio": {"watch_below": 0.30, "high_below": 0.20, "critical_below": 0.10},
        "available_funds_ratio": {"watch_below": 0.20, "high_below": 0.10, "critical_below": 0.05},
        "maintenance_margin_ratio": {"watch_above": 0.55, "high_above": 0.70, "critical_above": 0.85},
        "leverage": {"watch_above": 1.75, "high_above": 2.50, "critical_above": 4.00},
        "account_nav_share": {"watch_above": 0.70, "high_above": 0.85, "critical_above": 0.95},
        "short_option_contracts": {"watch_at": 1, "high_at": 5, "critical_at": 10},
    },
    "negative_cash_severity": "WATCH",
    "account_overrides": {},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_policy(path: Path | None = None) -> dict[str, Any]:
    policy = deepcopy(DEFAULT_POLICY)
    warnings: list[str] = []
    if path:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("policy must be a JSON object")
            policy = _deep_merge(policy, raw)
        except Exception as exc:
            warnings.append(f"POLICY_LOAD_FAILED:{type(exc).__name__}")
    policy["_policy_warnings"] = warnings
    return policy


def _number(value: Any) -> float | None:
    return control_tower.safe_float(value)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    top = _number(numerator)
    bottom = _number(denominator)
    if top is None or bottom is None or bottom <= 0:
        return None
    return round(top / bottom, 6)


def _severity_below(value: float | None, thresholds: dict[str, Any]) -> tuple[str, float] | None:
    if value is None:
        return None
    for severity, key in (("CRITICAL", "critical_below"), ("HIGH", "high_below"), ("WATCH", "watch_below")):
        limit = _number(thresholds.get(key))
        if limit is not None and value < limit:
            return severity, limit
    return None


def _severity_above(value: float | None, thresholds: dict[str, Any]) -> tuple[str, float] | None:
    if value is None:
        return None
    for severity, key in (("CRITICAL", "critical_above"), ("HIGH", "high_above"), ("WATCH", "watch_above")):
        limit = _number(thresholds.get(key))
        if limit is not None and value > limit:
            return severity, limit
    return None


def _severity_at(value: float | None, thresholds: dict[str, Any]) -> tuple[str, float] | None:
    if value is None:
        return None
    for severity, key in (("CRITICAL", "critical_at"), ("HIGH", "high_at"), ("WATCH", "watch_at")):
        limit = _number(thresholds.get(key))
        if limit is not None and value >= limit:
            return severity, limit
    return None


def _alert_id(scope: str, rule: str, alias: str = "", instrument: str = "") -> str:
    material = "|".join([RISK_ENGINE_VERSION, scope, rule, alias, instrument])
    return "prisk_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def make_alert(
    *,
    scope: str,
    rule: str,
    severity: str,
    title: str,
    message: str,
    recommended_action: str,
    metric: str = "",
    value: float | None = None,
    threshold: float | None = None,
    account_alias: str = "",
    instrument: str = "",
) -> dict[str, Any]:
    severity = severity if severity in SEVERITY_ORDER else "WATCH"
    return {
        "alert_id": _alert_id(scope, rule, account_alias, instrument),
        "rule": rule,
        "scope": scope,
        "account_alias": account_alias,
        "instrument": instrument,
        "severity": severity,
        "title": title,
        "message": message,
        "metric": metric,
        "value": _number(value),
        "threshold": _number(threshold),
        "recommended_action": recommended_action,
        "acknowledgement_required": severity in {"HIGH", "CRITICAL"},
        "automatic_action_authorized": False,
        "real_account_id_excluded": True,
    }


def _account_policy(policy: dict[str, Any], alias: str) -> dict[str, Any]:
    overrides = policy.get("account_overrides") if isinstance(policy.get("account_overrides"), dict) else {}
    override = overrides.get(alias) if isinstance(overrides.get(alias), dict) else {}
    clean = {key: value for key, value in policy.items() if not key.startswith("_") and key != "account_overrides"}
    return _deep_merge(clean, override)


def _account_metrics(account: dict[str, Any]) -> dict[str, Any]:
    capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
    nav = _number(capacity.get("net_liquidation"))
    short_options = 0.0
    for position in account.get("positions") or []:
        if not isinstance(position, dict):
            continue
        if str(position.get("security_type") or "").upper() in {"OPT", "FOP"}:
            quantity = _number(position.get("quantity"))
            if quantity is not None and quantity < 0:
                short_options += abs(quantity)
    return {
        "net_liquidation": nav,
        "available_funds": _number(capacity.get("available_funds")),
        "excess_liquidity": _number(capacity.get("excess_liquidity")),
        "maintenance_margin_required": _number(capacity.get("maintenance_margin_required")),
        "gross_position_value": _number(capacity.get("gross_position_value")),
        "total_cash_value": _number(capacity.get("total_cash_value")),
        "excess_liquidity_ratio": _ratio(capacity.get("excess_liquidity"), nav),
        "available_funds_ratio": _ratio(capacity.get("available_funds"), nav),
        "maintenance_margin_ratio": _ratio(capacity.get("maintenance_margin_required"), nav),
        "leverage": _ratio(capacity.get("gross_position_value"), nav),
        "short_option_contracts": round(short_options, 4),
    }


def _metric_alert(
    alerts: list[dict[str, Any]],
    *,
    account_alias: str,
    rule: str,
    metric: str,
    value: float | None,
    breach: tuple[str, float] | None,
    title: str,
    message: str,
    recommended_action: str,
) -> None:
    if not breach:
        return
    severity, threshold = breach
    alerts.append(make_alert(
        scope="ACCOUNT",
        rule=rule,
        severity=severity,
        title=title,
        message=message,
        recommended_action=recommended_action,
        metric=metric,
        value=value,
        threshold=threshold,
        account_alias=account_alias,
    ))


def evaluate(control_tower_payload: dict[str, Any], policy: dict[str, Any] | None = None, *, reference: datetime | None = None) -> dict[str, Any]:
    policy = deepcopy(policy or DEFAULT_POLICY)
    reference = reference or datetime.now(timezone.utc)
    alerts: list[dict[str, Any]] = []
    account_results = []
    policy_warnings = list(policy.get("_policy_warnings") or [])
    if policy_warnings:
        alerts.append(make_alert(
            scope="SYSTEM",
            rule="RISK_POLICY_INVALID",
            severity="CRITICAL",
            title="Política de riesgo no disponible",
            message="No fue posible leer correctamente la política configurada.",
            recommended_action="Corregir el archivo de política antes de interpretar el estado de riesgo.",
        ))

    tower_status = str(control_tower_payload.get("status") or "WAIT_ACCOUNT_REFRESH").upper()
    if tower_status != "READY":
        alerts.append(make_alert(
            scope="SYSTEM",
            rule="CONTROL_TOWER_NOT_READY",
            severity="CRITICAL",
            title="Datos multicuenta incompletos",
            message=f"Control Tower reporta {tower_status}; la evaluación no puede considerarse completa.",
            recommended_action="Refrescar todas las cuentas y resolver cualquier cuenta vencida o fallida.",
        ))

    accounts = [row for row in (control_tower_payload.get("accounts") or []) if isinstance(row, dict)]
    if not accounts:
        alerts.append(make_alert(
            scope="SYSTEM",
            rule="NO_CONFIGURED_ACCOUNTS",
            severity="CRITICAL",
            title="No hay cuentas evaluables",
            message="La Torre de Control no contiene ninguna cuenta para evaluar.",
            recommended_action="Configurar y refrescar al menos una cuenta antes de usar el estado de riesgo.",
        ))
    consolidated_nav = _number((control_tower_payload.get("consolidated_capacity") or {}).get("net_liquidation"))
    for index, account in enumerate(accounts):
        try:
            alias = control_tower.normalize_alias(account.get("account_alias"))
        except ValueError:
            alias = f"unknown-{index + 1}"
        local_policy = _account_policy(policy, alias)
        thresholds = local_policy.get("thresholds") if isinstance(local_policy.get("thresholds"), dict) else {}
        metrics = _account_metrics(account)
        state = str(account.get("refresh_status") or "UNREFRESHED").upper()
        computed_age = control_tower.snapshot_age_minutes({"generated_at": account.get("generated_at")}, reference)
        age = computed_age if computed_age is not None else _number(account.get("snapshot_age_minutes"))
        max_age = _number(local_policy.get("max_data_age_minutes")) or 15.0
        if state == "READY" and age is not None and age > max_age:
            state = "STALE"

        if state != "READY" or age is None or age > max_age:
            alerts.append(make_alert(
                scope="ACCOUNT",
                rule="ACCOUNT_DATA_NOT_READY",
                severity="CRITICAL",
                title=f"Datos no confiables en {alias}",
                message=f"Estado {state}; antigüedad {age if age is not None else 'N/D'} minutos.",
                recommended_action="Refrescar esta cuenta y no aumentar riesgo hasta recuperar datos válidos.",
                metric="snapshot_age_minutes",
                value=age,
                threshold=max_age,
                account_alias=alias,
            ))

        nav = metrics["net_liquidation"]
        if nav is None or nav <= 0:
            alerts.append(make_alert(
                scope="ACCOUNT",
                rule="NET_LIQUIDATION_NON_POSITIVE",
                severity="CRITICAL",
                title=f"NAV inválido en {alias}",
                message="La liquidación neta no está disponible o no es positiva.",
                recommended_action="Revisar el broker y bloquear cualquier aumento de exposición.",
                metric="net_liquidation",
                value=nav,
                threshold=0,
                account_alias=alias,
            ))

        required_metrics = [
            "excess_liquidity_ratio",
            "available_funds_ratio",
            "maintenance_margin_ratio",
            "leverage",
        ]
        missing_metrics = [metric for metric in required_metrics if metrics.get(metric) is None]
        if missing_metrics:
            alerts.append(make_alert(
                scope="ACCOUNT",
                rule="RISK_METRICS_MISSING",
                severity="CRITICAL",
                title=f"Métricas de riesgo incompletas en {alias}",
                message="Faltan métricas necesarias: " + ", ".join(missing_metrics) + ".",
                recommended_action="Refrescar el broker y no interpretar esta cuenta como libre de riesgo.",
                account_alias=alias,
            ))

        _metric_alert(
            alerts,
            account_alias=alias,
            rule="EXCESS_LIQUIDITY_LOW",
            metric="excess_liquidity_ratio",
            value=metrics["excess_liquidity_ratio"],
            breach=_severity_below(metrics["excess_liquidity_ratio"], thresholds.get("excess_liquidity_ratio") or {}),
            title=f"Colchón de liquidez reducido en {alias}",
            message="ExcessLiquidity representa una fracción reducida del NAV.",
            recommended_action="Revisar margen, exposición y posibles reducciones manuales antes de asumir riesgo nuevo.",
        )
        _metric_alert(
            alerts,
            account_alias=alias,
            rule="AVAILABLE_FUNDS_LOW",
            metric="available_funds_ratio",
            value=metrics["available_funds_ratio"],
            breach=_severity_below(metrics["available_funds_ratio"], thresholds.get("available_funds_ratio") or {}),
            title=f"Fondos disponibles reducidos en {alias}",
            message="AvailableFunds está por debajo del nivel configurado respecto del NAV.",
            recommended_action="No comprometer capital adicional sin revisar capacidad y obligaciones abiertas.",
        )
        _metric_alert(
            alerts,
            account_alias=alias,
            rule="MAINTENANCE_MARGIN_HIGH",
            metric="maintenance_margin_ratio",
            value=metrics["maintenance_margin_ratio"],
            breach=_severity_above(metrics["maintenance_margin_ratio"], thresholds.get("maintenance_margin_ratio") or {}),
            title=f"Uso de margen elevado en {alias}",
            message="MaintMarginReq consume una proporción elevada del NAV.",
            recommended_action="Revisar posiciones que más consumen margen y preparar reducción manual si empeora.",
        )
        _metric_alert(
            alerts,
            account_alias=alias,
            rule="LEVERAGE_HIGH",
            metric="leverage",
            value=metrics["leverage"],
            breach=_severity_above(metrics["leverage"], thresholds.get("leverage") or {}),
            title=f"Apalancamiento elevado en {alias}",
            message="GrossPositionValue supera el múltiplo de NAV configurado.",
            recommended_action="Revisar exposición bruta y evitar incrementarla hasta volver al rango objetivo.",
        )
        _metric_alert(
            alerts,
            account_alias=alias,
            rule="SHORT_OPTION_EXPOSURE",
            metric="short_option_contracts",
            value=metrics["short_option_contracts"],
            breach=_severity_at(metrics["short_option_contracts"], thresholds.get("short_option_contracts") or {}),
            title=f"Opciones cortas presentes en {alias}",
            message="Hay contratos de opciones con cantidad negativa; esta señal no presume que estén descubiertos.",
            recommended_action="Confirmar cobertura, vencimiento, asignación y capacidad de mantenimiento.",
        )

        cash = metrics["total_cash_value"]
        negative_cash_severity = str(local_policy.get("negative_cash_severity") or "WATCH").upper()
        if cash is not None and cash < 0 and negative_cash_severity in SEVERITY_ORDER:
            alerts.append(make_alert(
                scope="ACCOUNT",
                rule="NEGATIVE_CASH_BALANCE",
                severity=negative_cash_severity,
                title=f"Efectivo negativo en {alias}",
                message="TotalCashValue es negativo y puede representar financiación por margen.",
                recommended_action="Confirmar que el débito sea intencional y sostenible bajo el plan de liquidez.",
                metric="total_cash_value",
                value=cash,
                threshold=0,
                account_alias=alias,
            ))

        nav_share = _ratio(nav, consolidated_nav)
        if len(accounts) > 1:
            _metric_alert(
                alerts,
                account_alias=alias,
                rule="ACCOUNT_NAV_CONCENTRATION",
                metric="account_nav_share",
                value=nav_share,
                breach=_severity_above(nav_share, thresholds.get("account_nav_share") or {}),
                title=f"Concentración de patrimonio en {alias}",
                message="Esta cuenta concentra una proporción elevada del NAV consolidado.",
                recommended_action="Revisar si la concentración entre cuentas coincide con la asignación estratégica.",
            )
        account_results.append({
            "account_alias": alias,
            "refresh_status": state,
            "snapshot_age_minutes": age,
            "metrics": metrics,
            "alert_count": 0,
            "highest_severity": "NONE",
            "real_account_id_excluded": True,
        })

    by_alias = {row["account_alias"]: row for row in account_results}
    for alert in alerts:
        row = by_alias.get(alert.get("account_alias"))
        if not row:
            continue
        row["alert_count"] += 1
        current = row["highest_severity"]
        if current == "NONE" or SEVERITY_ORDER[alert["severity"]] > SEVERITY_ORDER[current]:
            row["highest_severity"] = alert["severity"]

    alerts.sort(key=lambda item: (-SEVERITY_ORDER[item["severity"]], item.get("account_alias") or "", item["rule"]))
    counts = {severity.lower(): sum(1 for alert in alerts if alert["severity"] == severity) for severity in SEVERITY_ORDER}
    highest = alerts[0]["severity"] if alerts else "NONE"
    status = {"CRITICAL": "BLOCKED", "HIGH": "ACTION_REQUIRED", "WATCH": "WATCH", "INFO": "INFO", "NONE": "READY"}[highest]
    decision = {"BLOCKED": "NO_NEW_RISK", "ACTION_REQUIRED": "REVIEW_REQUIRED", "WATCH": "MONITOR", "INFO": "MONITOR", "READY": "CLEAR"}[status]
    weights = {"CRITICAL": 100, "HIGH": 75, "WATCH": 45, "INFO": 20}
    risk_score = min(100, max([weights.get(alert["severity"], 0) for alert in alerts] + [0]) + max(0, len(alerts) - 1) * 2)
    return {
        "risk_engine_version": RISK_ENGINE_VERSION,
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": reference.isoformat(),
        "source_control_tower_generated_at": control_tower_payload.get("generated_at"),
        "status": status,
        "decision_support": decision,
        "risk_score": risk_score,
        "highest_severity": highest,
        "alert_count": len(alerts),
        "alert_counts": counts,
        "accounts": account_results,
        "alerts": alerts,
        "policy_warnings": policy_warnings,
        "manual_review_required": bool(alerts),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }
