"""Evidence-quality scoring for Stock Ultimus decisions.

The score is deterministic evidence hygiene only. It does not authorize orders
and does not replace strategy, risk, broker, or manual-review gates.
"""

from __future__ import annotations

from typing import Any

import source_attribution


EVIDENCE_QUALITY_VERSION = "evidence_quality_v1"
ENTRY_READY_MIN_EVIDENCE_SCORE = 70


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in [None, "", "None"]:
            return default
        return float(value)
    except Exception:
        return default


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _contract(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision.get("selected_contract") if isinstance(decision.get("selected_contract"), dict) else {}
    return contract


def _technical(decision: dict[str, Any]) -> dict[str, Any]:
    technical = decision.get("technical") if isinstance(decision.get("technical"), dict) else {}
    return technical


def evidence_quality_report(decision: dict[str, Any]) -> dict[str, Any]:
    decision = decision if isinstance(decision, dict) else {}
    attribution = decision.get("source_attribution")
    if not isinstance(attribution, dict):
        attribution = source_attribution.build_source_attribution(decision, decision.get("source_decision"))

    contract = _contract(decision)
    technical = _technical(decision)
    score = 0.0
    reasons: list[str] = []
    blockers: list[str] = []

    candidate_source = safe_upper(attribution.get("candidate_source"))
    confirmation_source = safe_upper(attribution.get("confirmation_source"))
    if candidate_source not in {"", "UNKNOWN", source_attribution.NO_CANDIDATE_SOURCE}:
        score += 20
        reasons.append("CANDIDATE_SOURCE_PRESENT")
    else:
        blockers.append("MISSING_CANDIDATE_SOURCE")

    if confirmation_source not in {"", "UNKNOWN", source_attribution.NO_CONFIRMATION_SOURCE}:
        score += 20
        reasons.append("CONFIRMATION_SOURCE_PRESENT")
    else:
        blockers.append("MISSING_CONFIRMATION_SOURCE")

    missing_contract_fields = source_attribution.entry_ready_evidence_gaps({
        **decision,
        "source_attribution": attribution,
    })
    missing_contract_fields = [gap for gap in missing_contract_fields if gap.startswith("MISSING_CONTRACT_")]
    if not missing_contract_fields:
        score += 20
        reasons.append("CONTRACT_EXECUTION_FIELDS_COMPLETE")
    else:
        blockers.extend(missing_contract_fields)

    if safe_upper(attribution.get("source_confidence")) == "HIGH":
        score += 10
        reasons.append("SOURCE_CONFIDENCE_HIGH")
    elif safe_upper(attribution.get("source_confidence")) == "PARTIAL":
        score += 4
        reasons.append("SOURCE_CONFIDENCE_PARTIAL")

    data_quality = safe_upper(contract.get("data_quality") or decision.get("data_quality"))
    if data_quality == "FULL_WITH_GREEKS":
        score += 10
        reasons.append("OPTION_DATA_FULL_WITH_GREEKS")
    elif data_quality in {"PRICE_WITH_GREEKS_NO_BIDASK", "PARTIAL_OPTION_DATA"}:
        score += 3
        blockers.append(data_quality)

    spread_pct = safe_float(contract.get("spread_pct") or decision.get("spread_pct"))
    if spread_pct is not None:
        if spread_pct <= 18:
            score += 8
            reasons.append("SPREAD_ACCEPTABLE")
        elif spread_pct <= 30:
            score += 3
            blockers.append("SPREAD_WIDE")
        else:
            blockers.append("SPREAD_TOO_WIDE")
    else:
        blockers.append("SPREAD_MISSING")

    if technical.get("confirmed") is True:
        score += 8
        reasons.append("TECHNICAL_CONFIRMED")
    elif technical:
        score += 4
        reasons.append("TECHNICAL_CONTEXT_PRESENT")

    context_completeness = safe_float(
        decision.get("context_completeness_pct")
        or decision.get("tradingview_context_completeness_pct"),
    )
    if context_completeness is not None:
        score += min(max(context_completeness, 0), 100) * 0.04
        if context_completeness < 60:
            blockers.append("TRADINGVIEW_CONTEXT_INCOMPLETE")

    discard_reasons = list(contract.get("option_discard_reasons") or decision.get("option_discard_reasons") or [])
    for reason in discard_reasons:
        blockers.append(str(reason))
    score -= min(len(discard_reasons) * 8, 32)

    score = round(max(0.0, min(100.0, score)), 2)
    deduped_blockers = []
    for blocker in blockers:
        if blocker and blocker not in deduped_blockers:
            deduped_blockers.append(blocker)

    status = "PASS" if score >= ENTRY_READY_MIN_EVIDENCE_SCORE and not deduped_blockers else "WARN"
    if score < ENTRY_READY_MIN_EVIDENCE_SCORE:
        status = "BLOCKED"

    return {
        "evidence_quality_version": EVIDENCE_QUALITY_VERSION,
        "score": score,
        "status": status,
        "minimum_entry_ready_score": ENTRY_READY_MIN_EVIDENCE_SCORE,
        "reasons": reasons,
        "blockers": deduped_blockers,
        "candidate_source": attribution.get("candidate_source"),
        "confirmation_source": attribution.get("confirmation_source"),
        "source_confidence": attribution.get("source_confidence"),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def evidence_quality_wait_state(report: dict[str, Any]) -> str:
    blockers = [safe_upper(item) for item in (report.get("blockers") or [])]
    option_blockers = [
        blocker for blocker in blockers
        if blocker.startswith("MISSING_CONTRACT_")
        or blocker in {"MISSING_CANDIDATE_SOURCE", "NO_BID_ASK", "NO_GREEKS", "NO_SPREAD", "SPREAD_WIDE", "SPREAD_TOO_WIDE", "NO_VALID_OPTION_PRICE"}
    ]
    return "WAIT_OPTIONS_DATA" if option_blockers else "WAIT_TECHNICAL"


def apply_evidence_quality(decision: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(decision or {})
    report = evidence_quality_report(enriched)
    enriched["evidence_quality"] = report
    enriched["evidence_quality_score"] = report["score"]
    enriched["evidence_quality_status"] = report["status"]
    enriched["evidence_quality_blockers"] = report["blockers"]
    enriched["manual_review_required"] = True
    enriched["execution_authorized"] = False
    enriched["not_order_instruction"] = True
    return enriched
