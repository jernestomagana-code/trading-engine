"""Source-attribution helpers for Stock Ultimus decision evidence.

The helpers in this module are intentionally pure. They do not fetch market
data, do not persist secrets, and never authorize execution. Their job is to
make every decision auditable by naming where the candidate and confirmation
came from.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


ATTRIBUTION_VERSION = "source_attribution_v1"
NO_CANDIDATE_SOURCE = "NO_CANDIDATE_SOURCE"
NO_CONFIRMATION_SOURCE = "NO_CONFIRMATION_SOURCE"
ENTRY_READY_REQUIRED_CONTRACT_FIELDS = ["strike", "expiration", "dte", "bid", "ask", "delta"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _infer_candidate_source(decision: dict[str, Any], source_decision: dict[str, Any]) -> str:
    row = decision.get("selected_contract")
    if not isinstance(row, dict):
        row = source_decision.get("selected_contract")
    if not isinstance(row, dict):
        row = source_decision.get("best_row")
    if not isinstance(row, dict):
        row = {}

    explicit = _first_text(
        decision.get("candidate_source"),
        row.get("candidate_source"),
        row.get("source"),
        row.get("engine_layer"),
        source_decision.get("candidate_source"),
        source_decision.get("source"),
    )
    explicit_upper = safe_upper(explicit)
    if "IBKR" in explicit_upper or "OPTION" in explicit_upper or row.get("option_symbol") or row.get("local_symbol"):
        return "IBKR_OPTION_CHAIN"
    if "LOCAL_STRATEGY" in explicit_upper or "SCANNER" in explicit_upper:
        return "LOCAL_STRATEGY_SCANNER"
    if "TRADINGVIEW" in explicit_upper or "TRADING_VIEW" in explicit_upper:
        return "TRADINGVIEW_ALERT"
    if row:
        return "SNAPSHOT_OPTION_ROW"
    if decision.get("final_state") == "NO_DATA":
        return NO_CANDIDATE_SOURCE
    return explicit_upper or NO_CANDIDATE_SOURCE


def _infer_confirmation_source(decision: dict[str, Any], source_decision: dict[str, Any]) -> str:
    technical = decision.get("technical")
    if not isinstance(technical, dict):
        technical = source_decision.get("technical")
    if not isinstance(technical, dict):
        technical = {}

    explicit = _first_text(
        decision.get("confirmation_source"),
        technical.get("confirmation_source"),
        technical.get("source"),
        technical.get("engine_layer"),
        technical.get("source_priority"),
        source_decision.get("confirmation_source"),
    )
    explicit_upper = safe_upper(explicit)
    if "TRADINGVIEW" in explicit_upper or "TRADING_VIEW" in explicit_upper or "TECHNICAL_SNAPSHOT" in explicit_upper:
        return "TRADINGVIEW_ALERT"
    if "LOCAL_TECHNICAL" in explicit_upper or "LOCAL_FALLBACK" in explicit_upper:
        return "LOCAL_TECHNICAL_ENGINE"
    if "IBKR_HISTORICAL" in explicit_upper:
        return "IBKR_HISTORICAL_BARS_LOCAL_TECHNICALS"
    if technical:
        return "TECHNICAL_SNAPSHOT"
    return NO_CONFIRMATION_SOURCE


def _source_confidence(candidate_source: str, confirmation_source: str, decision: dict[str, Any]) -> str:
    if candidate_source == NO_CANDIDATE_SOURCE and confirmation_source == NO_CONFIRMATION_SOURCE:
        return "NONE"
    contract = decision.get("selected_contract") if isinstance(decision.get("selected_contract"), dict) else {}
    complete_contract = all(contract.get(field) not in [None, "", "None"] for field in ["strike", "expiration", "dte", "bid", "ask", "delta"])
    if complete_contract and confirmation_source not in {NO_CONFIRMATION_SOURCE, ""}:
        return "HIGH"
    if candidate_source != NO_CANDIDATE_SOURCE or confirmation_source != NO_CONFIRMATION_SOURCE:
        return "PARTIAL"
    return "LOW"


def decision_signal_id(decision: dict[str, Any], source_decision: dict[str, Any] | None = None) -> str:
    source_decision = source_decision if isinstance(source_decision, dict) else {}
    existing = _first_text(decision.get("signal_id"), source_decision.get("signal_id"), decision.get("decision_id"))
    if existing:
        return existing
    generated_at = str(decision.get("generated_at") or source_decision.get("generated_at") or now_iso())
    day = generated_at[:10]
    ticker = safe_upper(decision.get("ticker") or source_decision.get("ticker"), "UNKNOWN")
    strategy = safe_upper(decision.get("strategy") or source_decision.get("strategy"), "UNKNOWN")
    state = safe_upper(decision.get("final_state") or source_decision.get("final_state"), "UNKNOWN")
    return f"SIG-{day}-{ticker}-{strategy}-{state}-{_json_hash([ticker, strategy, state, generated_at])}"


def snapshot_id_from_decision(decision: dict[str, Any], source_decision: dict[str, Any] | None = None) -> str:
    source_decision = source_decision if isinstance(source_decision, dict) else {}
    explicit = _first_text(decision.get("snapshot_id"), source_decision.get("snapshot_id"))
    if explicit:
        return explicit
    master_source = _first_text(decision.get("master_source"), source_decision.get("master_source"), source_decision.get("source"))
    generated_at = _first_text(decision.get("generated_at"), source_decision.get("generated_at"))
    return f"SNAP-{_json_hash([master_source, generated_at])}"


def build_source_attribution(decision: dict[str, Any], source_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = decision if isinstance(decision, dict) else {}
    source_decision = source_decision if isinstance(source_decision, dict) else {}
    candidate_source = _infer_candidate_source(decision, source_decision)
    confirmation_source = _infer_confirmation_source(decision, source_decision)
    signal_id = decision_signal_id(decision, source_decision)
    snapshot_id = snapshot_id_from_decision(decision, source_decision)
    lineage = [
        {
            "role": "candidate",
            "source": candidate_source,
            "status": "AVAILABLE" if candidate_source != NO_CANDIDATE_SOURCE else "MISSING",
        },
        {
            "role": "confirmation",
            "source": confirmation_source,
            "status": "AVAILABLE" if confirmation_source != NO_CONFIRMATION_SOURCE else "MISSING",
        },
    ]
    return {
        "source_attribution_version": ATTRIBUTION_VERSION,
        "candidate_source": candidate_source,
        "confirmation_source": confirmation_source,
        "signal_source": confirmation_source if confirmation_source != NO_CONFIRMATION_SOURCE else candidate_source,
        "signal_id": signal_id,
        "snapshot_id": snapshot_id,
        "source_confidence": _source_confidence(candidate_source, confirmation_source, decision),
        "data_lineage": lineage,
        "unknown_source": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def apply_source_attribution(decision: dict[str, Any], source_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    enriched = dict(decision or {})
    attribution = build_source_attribution(enriched, source_decision)
    enriched["source_attribution"] = attribution
    for key in ["candidate_source", "confirmation_source", "signal_source", "signal_id", "snapshot_id", "source_confidence", "data_lineage"]:
        enriched[key] = attribution[key]
    enriched["manual_review_required"] = True
    enriched["execution_authorized"] = False
    enriched["not_order_instruction"] = True
    return enriched


def entry_ready_evidence_gaps(decision: dict[str, Any]) -> list[str]:
    """Return hard evidence gaps that must block ENTRY_READY.

    This is a deterministic gate for the decision engine. It does not fetch new
    data and it does not decide whether a setup is good; it only verifies that
    an ENTRY_READY candidate is auditable.
    """

    decision = decision if isinstance(decision, dict) else {}
    attribution = decision.get("source_attribution")
    if not isinstance(attribution, dict):
        attribution = build_source_attribution(decision, decision.get("source_decision"))

    gaps: list[str] = []
    candidate_source = safe_upper(attribution.get("candidate_source"))
    confirmation_source = safe_upper(attribution.get("confirmation_source"))
    if candidate_source in {"", "UNKNOWN", NO_CANDIDATE_SOURCE}:
        gaps.append("MISSING_CANDIDATE_SOURCE")
    if confirmation_source in {"", "UNKNOWN", NO_CONFIRMATION_SOURCE}:
        gaps.append("MISSING_CONFIRMATION_SOURCE")

    contract = decision.get("selected_contract") if isinstance(decision.get("selected_contract"), dict) else {}
    for field in ENTRY_READY_REQUIRED_CONTRACT_FIELDS:
        if contract.get(field) in [None, "", "None"]:
            gaps.append(f"MISSING_CONTRACT_{field.upper()}")

    deduped = []
    for gap in gaps:
        if gap not in deduped:
            deduped.append(gap)
    return deduped


def entry_ready_evidence_wait_state(gaps: list[str]) -> str:
    option_gap = any(
        gap == "MISSING_CANDIDATE_SOURCE" or gap.startswith("MISSING_CONTRACT_")
        for gap in gaps or []
    )
    return "WAIT_OPTIONS_DATA" if option_gap else "WAIT_TECHNICAL"
