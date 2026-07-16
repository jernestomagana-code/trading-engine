"""Operational checks for TradingView alert coverage and received evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tradingview_alert_coverage
import tradingview_payload_contract
import tradingview_signal_ledger


HEALTH_VERSION = "tradingview_alert_health_v1"
AUDIT_VERSION = "tradingview_production_audit_v1"
E2E_VERSION = "tradingview_e2e_readiness_v1"
VISIBLE_HEALTH_VERSION = "tradingview_visible_health_v1"
FIRST_OPEN_DAY_CHECKLIST_VERSION = "tradingview_first_open_day_checklist_v1"
ALERT_BUNDLE_HEALTH_VERSION = "tradingview_alert_bundle_health_v1"
DEFAULT_RUNTIME_DIR = Path("runtime")
DEFAULT_BUNDLE_COVERAGES = [
    {
        "name": "intraday_index_futures",
        "coverage_path": "config/tradingview_alert_coverage_v1.json",
        "required_for_entry_ready": True,
    },
    {
        "name": "options_underlying_confirmation",
        "coverage_path": "config/tradingview_options_underlying_alert_coverage_v1.json",
        "required_for_options_entry_ready": True,
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _symbol_key(value: Any) -> str:
    text = _safe_upper(value)
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


def _event_code(value: Any) -> str:
    return _safe_upper(value)


def _age_minutes(received_at: Any, *, generated_at: datetime) -> float | None:
    parsed = _parse_iso(received_at)
    if parsed is None:
        return None
    return round(max((generated_at - parsed).total_seconds(), 0) / 60, 2)


def load_runtime_events(runtime_dir: Path | str = DEFAULT_RUNTIME_DIR, *, limit: int = 20000) -> list[dict[str, Any]]:
    path = Path(runtime_dir) / "v32_signal_events.json"
    return tradingview_signal_ledger.load_signal_events(path, limit=limit)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def latest_events_by_code(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        code = _event_code(event.get("event_code"))
        if not code:
            continue
        previous = latest.get(code)
        if previous is None or str(event.get("received_at") or "") >= str(previous.get("received_at") or ""):
            latest[code] = event
    return latest


def _unknown_or_quarantined_events(
    events: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_codes = {
        _event_code(item.get("event_code"))
        for item in tradingview_alert_coverage.alerts(coverage)
        if _event_code(item.get("event_code"))
    }
    allowed_symbols = {_symbol_key(item) for item in coverage.get("symbols", [])}
    rows = []
    for event in events:
        code = _event_code(event.get("event_code"))
        symbol = _symbol_key(event.get("ticker"))
        reasons = list(event.get("quarantine_reasons") or [])
        if not code:
            reasons.append("MISSING_EVENT_CODE")
        elif expected_codes and code not in expected_codes:
            reasons.append("UNKNOWN_EVENT_CODE")
        if event.get("accepted_for_engine") is False or event.get("alert_contract_status") == "QUARANTINED":
            reasons.append("QUARANTINED")
        reasons = sorted(set(str(item) for item in reasons if item))
        if not reasons:
            continue
        if "QUARANTINED" not in reasons and symbol not in allowed_symbols and code not in expected_codes:
            continue
        rows.append(
            {
                "event_id": event.get("event_id") or event.get("id"),
                "received_at": event.get("received_at"),
                "ticker": event.get("ticker"),
                "timeframe": event.get("timeframe"),
                "event_code": code or event.get("event_code"),
                "action": event.get("action"),
                "alert_contract_status": event.get("alert_contract_status"),
                "accepted_for_engine": event.get("accepted_for_engine"),
                "quarantine_reasons": reasons,
                "payload_hash_present": bool(event.get("payload_hash")),
                "raw_payload_present": isinstance(event.get("raw_payload"), dict),
            }
        )
    return rows


def _visible_status_from_health(health: dict[str, Any], *, ibkr_primary_gap: str = "UNKNOWN") -> dict[str, Any]:
    missing_required = health.get("missing_required_event_codes") or []
    missing_health = health.get("missing_health_event_codes") or []
    quarantine_count = int(health.get("quarantine_event_count") or 0)
    stale_or_invalid = sum(
        int((health.get("status_counts") or {}).get(status) or 0)
        for status in ["STALE", "INVALID_PAYLOAD"]
    )
    tv_state = "TV_OK"
    tv_blockers = []
    if "NO_REAL_TRADINGVIEW_EVENT" in (health.get("blockers") or []):
        tv_state = "TV_MISSING"
        tv_blockers.append("NO_REAL_TRADINGVIEW_EVENT")
    if quarantine_count:
        tv_state = "TV_UNKNOWN_PAYLOAD"
        tv_blockers.append("UNKNOWN_OR_QUARANTINED_TRADINGVIEW_PAYLOADS")
    if missing_required or missing_health:
        tv_state = "TV_MISSING"
        tv_blockers.append("MISSING_EXPECTED_TRADINGVIEW_ALERTS")
    if stale_or_invalid:
        tv_blockers.append("STALE_OR_INVALID_TRADINGVIEW_EVIDENCE")

    ibkr_state = "IBKR_OK" if ibkr_primary_gap == "COVERAGE_REVIEWABLE" else "IBKR_STALE"
    return {
        "visible_health_version": VISIBLE_HEALTH_VERSION,
        "state": "OK" if tv_state == "TV_OK" and ibkr_state == "IBKR_OK" else "ATTENTION",
        "tv": tv_state,
        "ibkr": ibkr_state,
        "paper_loop": "PAPER_LOOP_PENDING",
        "blockers": sorted(set(tv_blockers + ([] if ibkr_state == "IBKR_OK" else ["IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE"]))),
        "summary": {
            "expected_alert_count": health.get("expected_alert_count"),
            "received_expected_event_count": health.get("received_expected_event_count"),
            "quarantine_event_count": quarantine_count,
            "missing_required_event_codes": missing_required,
            "missing_health_event_codes": missing_health,
            "ibkr_primary_gap": ibkr_primary_gap,
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _expected_alerts(coverage: dict[str, Any], *, include_optional: bool = True) -> list[dict[str, Any]]:
    rows = []
    for item in tradingview_alert_coverage.alerts(coverage):
        if item.get("required") is True or include_optional:
            rows.append(item)
    return rows


def _include_optional_alerts_in_health(coverage: dict[str, Any]) -> bool:
    policy = coverage.get("global_policy") if isinstance(coverage.get("global_policy"), dict) else {}
    value = policy.get("include_optional_alerts_in_health")
    if value is None:
        return True
    return value is True


def _require_required_real_events_in_health(coverage: dict[str, Any]) -> bool:
    policy = coverage.get("global_policy") if isinstance(coverage.get("global_policy"), dict) else {}
    value = policy.get("require_required_real_events_in_health")
    if value is None:
        return True
    return value is True


def _event_status(
    expected: dict[str, Any],
    event: dict[str, Any] | None,
    *,
    generated_at: datetime,
    market_closed_ok: bool,
) -> dict[str, Any]:
    freshness = int(expected.get("freshness_minutes") or 0)
    status = "NEVER_RECEIVED"
    blocker = "NO_REAL_TRADINGVIEW_EVENT"
    age = None
    validation = {}
    if event:
        age = _age_minutes(event.get("received_at"), generated_at=generated_at)
        validation = event.get("payload_validation") if isinstance(event.get("payload_validation"), dict) else {}
        valid_payload = validation.get("valid") is True
        stale = freshness > 0 and age is not None and age > freshness
        if stale and market_closed_ok:
            status = "WAIT_MARKET"
            blocker = "MARKET_CLOSED_OR_NO_NEW_BAR"
        elif stale:
            status = "STALE"
            blocker = "ALERT_FRESHNESS_EXPIRED"
        elif not valid_payload:
            status = "INVALID_PAYLOAD"
            blocker = "PAYLOAD_CONTRACT_FAILED"
        else:
            status = "OK"
            blocker = None
    return {
        "alert_name": expected.get("alert_name"),
        "event_code": expected.get("event_code"),
        "symbol": expected.get("symbol"),
        "timeframe": expected.get("timeframe"),
        "alert_role": expected.get("alert_role"),
        "required": expected.get("required") is True,
        "freshness_minutes": freshness,
        "status": status,
        "blocker": blocker,
        "latest_event_id": (event or {}).get("event_id") or (event or {}).get("id"),
        "latest_received_at": (event or {}).get("received_at"),
        "age_minutes": age,
        "payload_valid": validation.get("valid"),
        "missing_fields": validation.get("missing_fields") or [],
        "invalid_numeric_fields": validation.get("invalid_numeric_fields") or [],
        "candidate_source": (event or {}).get("candidate_source"),
        "confirmation_source": (event or {}).get("confirmation_source"),
        "payload_hash_present": bool((event or {}).get("payload_hash")),
        "raw_payload_present": isinstance((event or {}).get("raw_payload"), dict),
    }


def build_alert_health(
    runtime_dir: Path | str = DEFAULT_RUNTIME_DIR,
    *,
    coverage_path: Path | str = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    coverage = tradingview_alert_coverage.load_coverage(coverage_path)
    coverage_validation = tradingview_alert_coverage.validate_coverage(coverage)
    generated_dt = _parse_iso(generated_at) or datetime.now(timezone.utc)
    generated = generated_dt.isoformat()
    events = load_runtime_events(runtime_dir)
    latest_by_code = latest_events_by_code(events)
    expected = _expected_alerts(coverage, include_optional=_include_optional_alerts_in_health(coverage))
    rows = [
        _event_status(
            item,
            latest_by_code.get(_event_code(item.get("event_code"))),
            generated_at=generated_dt,
            market_closed_ok=market_closed_ok,
        )
        for item in expected
    ]
    required_rows = [row for row in rows if row["required"]]
    health_rows = [row for row in rows if row["alert_role"] == "HEARTBEAT_SNAPSHOT"]
    require_required_real_events = _require_required_real_events_in_health(coverage)
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    allowed_symbols = {_symbol_key(item) for item in coverage.get("symbols", [])}
    unexpected_symbols = sorted(
        {
            _symbol_key(event.get("ticker"))
            for event in events
            if _event_code(event.get("event_code")) in {
                _event_code(item.get("event_code")) for item in expected
            }
            and _symbol_key(event.get("ticker"))
            and _symbol_key(event.get("ticker")) not in allowed_symbols
        }
    )
    unknown_or_quarantined = _unknown_or_quarantined_events(events, coverage)
    blocker_rows = rows if require_required_real_events else health_rows
    blockers = sorted({row["blocker"] for row in blocker_rows if row.get("blocker")})
    if not events:
        blockers.append("NO_REAL_TRADINGVIEW_EVENT")
    if unknown_or_quarantined:
        blockers.append("UNKNOWN_OR_QUARANTINED_TRADINGVIEW_PAYLOADS")
    ok = coverage_validation["valid"] and not [
        row for row in rows
        if require_required_real_events and row["required"] and row["status"] not in {"OK", "WAIT_MARKET"}
    ] and not [
        row for row in health_rows
        if row["status"] not in {"OK", "WAIT_MARKET"}
    ] and bool(events) and not unknown_or_quarantined
    report = {
        "health_version": HEALTH_VERSION,
        "generated_at": generated,
        "status": "OK" if ok else "DEGRADED",
        "coverage_valid": coverage_validation["valid"],
        "coverage_validation": coverage_validation,
        "runtime_dir": str(runtime_dir),
        "ledger_event_count": len(events),
        "production_active_alert_count": coverage_validation.get("production_active_alert_count", 0),
        "logical_event_count": coverage_validation.get("logical_event_count", len(rows)),
        "required_logical_event_count": coverage_validation.get("required_logical_event_count", len(required_rows)),
        "health_logical_event_count": coverage_validation.get("health_logical_event_count", len(health_rows)),
        "expected_alert_count": len(rows),
        "required_alert_count": len(required_rows),
        "health_alert_count": len(health_rows),
        "received_expected_event_count": sum(1 for row in rows if row["latest_event_id"]),
        "received_required_event_count": sum(1 for row in required_rows if row["latest_event_id"]),
        "received_health_event_count": sum(1 for row in health_rows if row["latest_event_id"]),
        "status_counts": dict(sorted(status_counts.items())),
        "quarantine_event_count": len(unknown_or_quarantined),
        "unknown_event_code_count": sum(
            1 for row in unknown_or_quarantined if "UNKNOWN_EVENT_CODE" in row.get("quarantine_reasons", [])
        ),
        "unknown_or_quarantined_events": unknown_or_quarantined[-25:],
        "required_real_events_required": require_required_real_events,
        "missing_required_event_codes": [
            row["event_code"]
            for row in required_rows
            if require_required_real_events and row["status"] == "NEVER_RECEIVED"
        ],
        "missing_opportunistic_event_codes": [
            row["event_code"]
            for row in required_rows
            if not require_required_real_events and row["status"] == "NEVER_RECEIVED"
        ],
        "missing_health_event_codes": [
            row["event_code"] for row in health_rows if row["status"] == "NEVER_RECEIVED"
        ],
        "blockers": sorted(set(blockers)),
        "unexpected_symbols": unexpected_symbols,
        "market_closed_ok": market_closed_ok,
        "alerts": rows,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    report["visible_health"] = _visible_status_from_health(report)
    return report


def build_production_audit(
    runtime_dir: Path | str = DEFAULT_RUNTIME_DIR,
    *,
    coverage_path: Path | str = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    coverage = tradingview_alert_coverage.load_coverage(coverage_path)
    health = build_alert_health(
        runtime_dir,
        coverage_path=coverage_path,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
    )
    policy = coverage.get("global_policy") if isinstance(coverage.get("global_policy"), dict) else {}
    minimum_core = int(policy.get("minimum_core_alert_count") or 0)
    minimum_health = int(policy.get("minimum_health_alert_count") or 0)
    approved_symbols = [_symbol_key(item) for item in coverage.get("symbols", [])]
    policy_approved_symbols = [_symbol_key(item) for item in policy.get("approved_symbols", [])]
    disallowed = [_symbol_key(item) for item in policy.get("disallowed_equivalent_futures_expansion", [])]
    futures_equivalent_policy = bool(disallowed)
    ibkr_payload = read_json(Path(runtime_dir) / "v32_ibkr_chain_coverage.json", {})
    ibkr_primary_gap = str((ibkr_payload if isinstance(ibkr_payload, dict) else {}).get("primary_gap") or "NO_IBKR_OPTION_DIAGNOSTICS")
    visible_health = _visible_status_from_health(health, ibkr_primary_gap=ibkr_primary_gap)
    rows = health["alerts"]
    require_required_real_events = health.get("required_real_events_required") is True
    source_failures = [
        row["event_code"] for row in rows
        if row["latest_event_id"]
        and (row.get("candidate_source") != "TRADINGVIEW_ALERT" or row.get("confirmation_source") != "TRADINGVIEW_ALERT")
    ]
    persistence_failures = [
        row["event_code"] for row in rows
        if row["latest_event_id"] and not (row.get("payload_hash_present") and row.get("raw_payload_present"))
    ]
    payload_failures = [
        row["event_code"] for row in rows
        if row["latest_event_id"] and row.get("payload_valid") is not True
    ]
    checks = {
        "coverage_matrix_valid": health["coverage_valid"],
        "core_alerts_configured": health["required_alert_count"] >= minimum_core,
        "session_snapshot_alerts_configured": health["health_alert_count"] >= minimum_health,
        "approved_symbols_in_scope": not policy_approved_symbols or approved_symbols == policy_approved_symbols,
        "only_mnq_mes_in_scope": approved_symbols == ["MNQ1!", "MES1!"] if futures_equivalent_policy else True,
        "no_nq_es_expansion": ("NQ1!" in disallowed and "ES1!" in disallowed) if futures_equivalent_policy else True,
        "ledger_present": health["ledger_event_count"] > 0,
        "required_real_events_observed": (
            health["received_required_event_count"] == health["required_alert_count"]
            if require_required_real_events
            else True
        ),
        "session_snapshot_real_events_observed": health["received_health_event_count"] == health["health_alert_count"],
        "source_attribution_present": not source_failures,
        "raw_payload_and_hash_present": not persistence_failures,
        "payload_contract_valid": not payload_failures,
        "no_unknown_or_quarantined_tv_payloads": health["quarantine_event_count"] == 0,
        "visible_health_reviewable": visible_health.get("tv") == "TV_OK",
    }
    open_items = [name for name, passed in checks.items() if not passed]
    return {
        "audit_version": AUDIT_VERSION,
        "generated_at": health["generated_at"],
        "status": "PASS" if not open_items else "OPEN",
        "checks": checks,
        "open_items": open_items,
        "source_attribution_failures": source_failures,
        "persistence_failures": persistence_failures,
        "payload_failures": payload_failures,
        "unknown_or_quarantined_events": health.get("unknown_or_quarantined_events") or [],
        "visible_health": visible_health,
        "approved_symbols": approved_symbols,
        "disallowed_equivalent_futures_expansion": disallowed,
        "health_summary": {
            "status": health["status"],
            "required_real_events_required": require_required_real_events,
            "ledger_event_count": health["ledger_event_count"],
            "received_required_event_count": health["received_required_event_count"],
            "received_health_event_count": health["received_health_event_count"],
            "missing_required_event_codes": health["missing_required_event_codes"],
            "missing_opportunistic_event_codes": health.get("missing_opportunistic_event_codes") or [],
            "missing_health_event_codes": health["missing_health_event_codes"],
            "blockers": health["blockers"],
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def concrete_payload_for_event_code(
    event_code: str,
    *,
    coverage_path: Path | str = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
) -> dict[str, Any]:
    coverage = tradingview_alert_coverage.load_coverage(coverage_path)
    alert = tradingview_alert_coverage.alert_by_code(coverage, event_code)
    if not alert:
        raise ValueError(f"Unknown event_code: {event_code}")
    payload = tradingview_alert_coverage.payload_for_alert(alert)
    replacements = {
        "ticker": alert.get("symbol"),
        "timeframe": alert.get("timeframe"),
        "price": 100.0,
        "vwap": 99.5,
        "opening_range_high": 100.5,
        "opening_range_low": 98.5,
        "adx": 22.0,
        "atr": 8.0,
        "volume_relative": 1.4,
        "premarket_high": 101.0,
        "premarket_low": 97.5,
        "logical_stop": 98.75,
        "logical_target": 102.0,
        "rsi": 55.0,
        "ema_fast": 100.25,
        "ema_slow": 99.75,
        "trend_strength": 0.5,
        "score": 82.0,
        "score_long": 82.0,
        "score_short": 18.0,
        "macd_z": -1.25,
        "stoch_k": 18.0,
        "stoch_d": 21.0,
        "mtf_votes": 2.0,
        "mtf_long_votes": 2.0,
        "mtf_short_votes": 1.0,
        "atr_pct": 0.12,
    }
    payload.update(replacements)
    return payload


def _first_replayable_event_code(coverage_path: Path | str) -> str:
    coverage = tradingview_alert_coverage.load_coverage(coverage_path)
    health_alerts = [
        item for item in tradingview_alert_coverage.alerts(coverage)
        if item.get("alert_role") == "HEARTBEAT_SNAPSHOT" and item.get("required") is True
    ]
    required_alerts = [
        item for item in tradingview_alert_coverage.alerts(coverage)
        if item.get("required") is True
    ]
    candidates = health_alerts or required_alerts or tradingview_alert_coverage.alerts(coverage)
    if not candidates:
        raise ValueError(f"No replayable alerts in coverage: {coverage_path}")
    return str(candidates[0].get("event_code") or "")


def _coverage_label(coverage_path: Path | str) -> str:
    path = str(coverage_path)
    if "options_underlying" in path:
        return "SPY/QQQ/VIX options-underlying"
    if "chris_ia" in path:
        return "USTEC.F/US500F Chris IA"
    return "MNQ/MES futures"


def build_e2e_readiness(
    runtime_dir: Path | str = DEFAULT_RUNTIME_DIR,
    *,
    coverage_path: Path | str = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
    allow_local_replay_validation: bool = False,
) -> dict[str, Any]:
    health = build_alert_health(
        runtime_dir,
        coverage_path=coverage_path,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
    )
    local_replay_validation = None
    if allow_local_replay_validation:
        replay_event_code = _first_replayable_event_code(coverage_path)
        payload = concrete_payload_for_event_code(replay_event_code, coverage_path=coverage_path)
        event = tradingview_signal_ledger.normalize_signal_event(
            payload,
            raw_text=json.dumps(payload, sort_keys=True),
            endpoint="/technical_snapshot_local_replay",
            received_at=health["generated_at"],
            coverage_path=coverage_path,
        )
        local_replay_validation = {
            "event_code": payload.get("event_code"),
            "payload_valid": event["payload_validation"]["valid"],
            "candidate_source": event.get("candidate_source"),
            "confirmation_source": event.get("confirmation_source"),
            "raw_payload_present": isinstance(event.get("raw_payload"), dict),
            "payload_hash_present": bool(event.get("payload_hash")),
        }
    require_required_real_events = health.get("required_real_events_required") is True
    required_real_events_ready = (
        health["received_required_event_count"] == health["required_alert_count"]
        if require_required_real_events
        else health["ledger_event_count"] > 0 and health["quarantine_event_count"] == 0
    )
    ready = (
        health["coverage_valid"]
        and required_real_events_ready
        and health["received_health_event_count"] == health["health_alert_count"]
    )
    return {
        "e2e_version": E2E_VERSION,
        "generated_at": health["generated_at"],
        "status": "REAL_E2E_CONFIRMED" if ready else "WAITING_FOR_REAL_TRADINGVIEW_EVENTS",
        "real_e2e_confirmed": ready,
        "coverage_valid": health["coverage_valid"],
        "required_real_events_required": require_required_real_events,
        "required_real_events_observed": health["received_required_event_count"],
        "required_real_events_expected": health["required_alert_count"],
        "session_snapshot_real_events_observed": health["received_health_event_count"],
        "session_snapshot_real_events_expected": health["health_alert_count"],
        "missing_required_event_codes": health["missing_required_event_codes"],
        "missing_opportunistic_event_codes": health.get("missing_opportunistic_event_codes") or [],
        "missing_health_event_codes": health["missing_health_event_codes"],
        "local_replay_validation": local_replay_validation,
        "synthetic_runtime_write_performed": False,
        "next_real_trigger": "Wait for TradingView to fire {label} alerts during the next market session.".format(
            label=_coverage_label(coverage_path)
        ),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_alert_bundle_health(
    runtime_dir: Path | str = DEFAULT_RUNTIME_DIR,
    *,
    coverages: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
    allow_local_replay_validation: bool = False,
) -> dict[str, Any]:
    coverage_specs = coverages or DEFAULT_BUNDLE_COVERAGES
    generated_at = generated_at or now_iso()
    reports = []
    for spec in coverage_specs:
        path = spec.get("coverage_path")
        if not path or not Path(path).exists():
            reports.append(
                {
                    "name": spec.get("name") or str(path),
                    "coverage_path": str(path or ""),
                    "status": "MISSING_COVERAGE",
                    "coverage_valid": False,
                    "missing_required_event_codes": [],
                    "missing_health_event_codes": [],
                    "blockers": ["MISSING_COVERAGE_FILE"],
                    "required_for_entry_ready": spec.get("required_for_entry_ready") is True,
                    "required_for_options_entry_ready": spec.get("required_for_options_entry_ready") is True,
                }
            )
            continue
        health = build_alert_health(
            runtime_dir,
            coverage_path=path,
            generated_at=generated_at,
            market_closed_ok=market_closed_ok,
        )
        e2e = build_e2e_readiness(
            runtime_dir,
            coverage_path=path,
            generated_at=generated_at,
            market_closed_ok=market_closed_ok,
            allow_local_replay_validation=allow_local_replay_validation,
        )
        reports.append(
            {
                "name": spec.get("name") or Path(path).stem,
                "coverage_path": str(path),
                "status": health.get("status"),
                "e2e_status": e2e.get("status"),
                "real_e2e_confirmed": e2e.get("real_e2e_confirmed"),
                "coverage_valid": health.get("coverage_valid"),
                "ledger_event_count": health.get("ledger_event_count"),
                "production_active_alert_count": health.get("production_active_alert_count"),
                "logical_event_count": health.get("logical_event_count"),
                "required_logical_event_count": health.get("required_logical_event_count"),
                "health_logical_event_count": health.get("health_logical_event_count"),
                "expected_alert_count": health.get("expected_alert_count"),
                "required_alert_count": health.get("required_alert_count"),
                "health_alert_count": health.get("health_alert_count"),
                "received_required_event_count": health.get("received_required_event_count"),
                "received_health_event_count": health.get("received_health_event_count"),
                "missing_required_event_codes": health.get("missing_required_event_codes") or [],
                "missing_health_event_codes": health.get("missing_health_event_codes") or [],
                "quarantine_event_count": health.get("quarantine_event_count"),
                "blockers": health.get("blockers") or [],
                "visible_health": health.get("visible_health") or {},
                "local_replay_validation": e2e.get("local_replay_validation"),
                "required_for_entry_ready": spec.get("required_for_entry_ready") is True,
                "required_for_options_entry_ready": spec.get("required_for_options_entry_ready") is True,
            }
        )
    all_valid = all(item.get("coverage_valid") is True for item in reports)
    real_e2e_confirmed = all(item.get("real_e2e_confirmed") is True for item in reports)
    missing_required = {
        item["name"]: item.get("missing_required_event_codes") or []
        for item in reports
        if item.get("missing_required_event_codes")
    }
    missing_health = {
        item["name"]: item.get("missing_health_event_codes") or []
        for item in reports
        if item.get("missing_health_event_codes")
    }
    quarantine_count = sum(int(item.get("quarantine_event_count") or 0) for item in reports)
    blockers = []
    for item in reports:
        blockers.extend(
            "{name}:{blocker}".format(name=item["name"], blocker=blocker)
            for blocker in item.get("blockers") or []
        )
    status = "REAL_E2E_CONFIRMED" if all_valid and real_e2e_confirmed and quarantine_count == 0 else "WAITING_FOR_REAL_TRADINGVIEW_EVENTS"
    return {
        "bundle_health_version": ALERT_BUNDLE_HEALTH_VERSION,
        "generated_at": generated_at,
        "status": status,
        "coverage_valid": all_valid,
        "real_e2e_confirmed": real_e2e_confirmed,
        "coverage_count": len(reports),
        "total_production_active_alert_count": sum(int(item.get("production_active_alert_count") or 0) for item in reports),
        "total_logical_event_count": sum(int(item.get("logical_event_count") or 0) for item in reports),
        "total_required_logical_event_count": sum(int(item.get("required_logical_event_count") or 0) for item in reports),
        "total_health_logical_event_count": sum(int(item.get("health_logical_event_count") or 0) for item in reports),
        "total_expected_alert_count": sum(int(item.get("expected_alert_count") or 0) for item in reports),
        "total_required_alert_count": sum(int(item.get("required_alert_count") or 0) for item in reports),
        "total_health_alert_count": sum(int(item.get("health_alert_count") or 0) for item in reports),
        "total_received_required_event_count": sum(int(item.get("received_required_event_count") or 0) for item in reports),
        "total_received_health_event_count": sum(int(item.get("received_health_event_count") or 0) for item in reports),
        "total_quarantine_event_count": quarantine_count,
        "missing_required_event_codes_by_coverage": missing_required,
        "missing_health_event_codes_by_coverage": missing_health,
        "blockers": sorted(set(blockers)),
        "coverages": reports,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_first_open_day_checklist(
    runtime_dir: Path | str = DEFAULT_RUNTIME_DIR,
    *,
    coverage_path: Path | str = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    audit = build_production_audit(
        runtime_dir,
        coverage_path=coverage_path,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
    )
    health_summary = audit.get("health_summary") if isinstance(audit.get("health_summary"), dict) else {}
    visible = audit.get("visible_health") if isinstance(audit.get("visible_health"), dict) else {}
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    checklist = [
        {
            "name": "coverage_matrix_valid",
            "status": "PASS" if checks.get("coverage_matrix_valid") else "OPEN",
            "detail": "Local expected TradingView alert matrix is valid.",
        },
        {
            "name": "only_mnq_mes_active_scope",
            "status": "PASS" if checks.get("only_mnq_mes_in_scope") and checks.get("no_nq_es_expansion") else "OPEN",
            "detail": "MNQ/MES are the only active futures scope; NQ/ES expansion remains blocked.",
        },
        {
            "name": "real_required_alerts_observed",
            "status": "PASS" if checks.get("required_real_events_observed") else "OPEN",
            "detail": "All 10 required MNQ/MES strategy alerts have fired real payloads.",
            "missing": health_summary.get("missing_required_event_codes") or [],
        },
        {
            "name": "real_session_snapshots_observed",
            "status": "PASS" if checks.get("session_snapshot_real_events_observed") else "OPEN",
            "detail": "Both MNQ/MES 5m session snapshot health alerts have fired.",
            "missing": health_summary.get("missing_health_event_codes") or [],
        },
        {
            "name": "no_unknown_or_quarantined_payloads",
            "status": "PASS" if checks.get("no_unknown_or_quarantined_tv_payloads") else "OPEN",
            "detail": "No legacy, malformed, or unknown TradingView payload is feeding the engine.",
        },
        {
            "name": "payload_persistence_complete",
            "status": "PASS" if checks.get("raw_payload_and_hash_present") else "OPEN",
            "detail": "Received payloads have raw_payload and payload_hash/idempotency evidence.",
        },
        {
            "name": "source_attribution_complete",
            "status": "PASS" if checks.get("source_attribution_present") else "OPEN",
            "detail": "TradingView events include candidate_source and confirmation_source.",
        },
        {
            "name": "visible_health_reviewable",
            "status": "PASS" if checks.get("visible_health_reviewable") else "OPEN",
            "detail": "Visible health is TV_OK and IBKR_OK.",
            "visible_health": visible,
        },
        {
            "name": "manual_execution_guard",
            "status": "PASS",
            "detail": "Checklist is evidence-only; automated order execution remains disabled.",
        },
    ]
    open_items = [item["name"] for item in checklist if item["status"] != "PASS"]
    return {
        "checklist_version": FIRST_OPEN_DAY_CHECKLIST_VERSION,
        "generated_at": audit["generated_at"],
        "status": "READY_FOR_MANUAL_REVIEW" if not open_items else "WAITING_FOR_REAL_MARKET_EVIDENCE",
        "open_items": open_items,
        "checklist": checklist,
        "production_audit_status": audit.get("status"),
        "visible_health": visible,
        "next_action": (
            "Review live payloads and paper outcomes; do not change parameters."
            if not open_items
            else "Wait for real MNQ/MES TradingView alerts and refresh IBKR coverage during market hours."
        ),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def write_report(report: dict[str, Any], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
