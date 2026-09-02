"""Research-only gates for proposed premium-selling strategies.

This module deliberately cannot produce ENTRY_READY or authorize execution.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Iterable


CONFIG_VERSION = "premium_strategy_research_v1"
DEFAULT_CONFIG_PATH = Path("config/premium_strategy_research_v1.json")
SAFE_STATES = {"RESEARCH_BLOCKED", "RESEARCH_CANDIDATE", "PAPER_ELIGIBLE"}


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(Path(path).read_text())
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if config.get("config_version") != CONFIG_VERSION:
        raise ValueError(f"expected {CONFIG_VERSION}")
    if config.get("mode") != "RESEARCH_PAPER_ONLY":
        raise ValueError("premium strategies must remain research/paper only")
    if config.get("not_order_instruction") is not True or config.get("execution_authorized") is not False:
        raise ValueError("execution safety contract is invalid")
    if config.get("maximum_state") != "PAPER_ELIGIBLE":
        raise ValueError("maximum_state must be PAPER_ELIGIBLE")
    for section in ("earnings_volatility_harvest", "long_dated_putwrite", "promotion_gate"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"missing configuration section {section}")


def _result(state: str, blockers: Iterable[str], evidence: dict[str, Any]) -> dict[str, Any]:
    unique_blockers = list(dict.fromkeys(blockers))
    if state not in SAFE_STATES:
        raise ValueError(f"unsafe research state {state}")
    return {
        "state": state,
        "blockers": unique_blockers,
        "evidence": evidence,
        "maximum_state": "PAPER_ELIGIBLE",
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def parameter_grid(strategy_id: str, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    config = config or load_config()
    strategy_id = str(strategy_id).strip().upper()
    earnings = config["earnings_volatility_harvest"]
    long_dated = config["long_dated_putwrite"]
    if strategy_id == earnings["strategy_id"]:
        keys = ("structure", "entry_days_before", "expiration_days_after", "put_delta")
        values = (
            earnings["allowed_structures"],
            earnings["entry_days_before_earnings"],
            earnings["expiration_days_after_earnings"],
            earnings["put_delta_grid"],
        )
    elif strategy_id == long_dated["strategy_id"]:
        keys = ("ticker", "dte", "delta", "profit_target_pct")
        values = (
            long_dated["allowed_tickers"],
            long_dated["dte_grid"],
            long_dated["delta_grid"],
            long_dated["profit_target_pct"],
        )
    else:
        raise ValueError(f"unknown premium research strategy {strategy_id}")
    return [dict(zip(keys, combination)) for combination in itertools.product(*values)]


def earnings_candidate_gate(candidate: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = (config or load_config())["earnings_volatility_harvest"]
    blockers: list[str] = []
    structure = str(candidate.get("structure") or "").upper()
    if not candidate.get("earnings_confirmed"):
        blockers.append("EARNINGS_DATE_UNCONFIRMED")
    if not candidate.get("canslim_pass") or float(candidate.get("canslim_coverage_pct") or 0) < rules["minimum_canslim_coverage_pct"]:
        blockers.append("CANSLIM_QUALITY_INSUFFICIENT")
    if float(candidate.get("iv_percentile") or 0) < rules["minimum_iv_percentile"]:
        blockers.append("IV_PERCENTILE_INSUFFICIENT")
    if float(candidate.get("iv_rank") or 0) < rules["minimum_iv_rank"]:
        blockers.append("IV_RANK_INSUFFICIENT")
    if float(candidate.get("event_move_ratio") or 0) < rules["minimum_event_move_ratio"]:
        blockers.append("EVENT_VOLATILITY_PREMIUM_INSUFFICIENT")
    if float(candidate.get("iv_to_realized_ratio") or 0) < rules["minimum_iv_to_realized_ratio"]:
        blockers.append("VOLATILITY_RISK_PREMIUM_INSUFFICIENT")
    if float(candidate.get("bid_ask_spread_pct") or 999) > rules["maximum_bid_ask_spread_pct"] or int(candidate.get("open_interest") or 0) < rules["minimum_open_interest"]:
        blockers.append("OPTIONS_LIQUIDITY_INSUFFICIENT")
    if structure not in rules["allowed_structures"]:
        blockers.append("UNDEFINED_OR_UNCOVERED_RISK_NOT_ALLOWED")
    if float(candidate.get("stress_loss_pct_of_account") or 999) > rules["maximum_stress_loss_pct_of_account"]:
        blockers.append("STRESS_LOSS_EXCEEDS_BUDGET")
    return _result("RESEARCH_BLOCKED" if blockers else "RESEARCH_CANDIDATE", blockers, dict(candidate))


def long_dated_candidate_gate(candidate: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = (config or load_config())["long_dated_putwrite"]
    blockers: list[str] = []
    ticker = str(candidate.get("ticker") or "").upper()
    if ticker not in rules["allowed_tickers"]:
        blockers.append("TICKER_NOT_ALLOWED")
    if int(candidate.get("dte") or 0) not in rules["dte_grid"]:
        blockers.append("DTE_OUTSIDE_RESEARCH_GRID")
    if float(candidate.get("delta") or 0) not in rules["delta_grid"]:
        blockers.append("DELTA_OUTSIDE_RESEARCH_GRID")
    if float(candidate.get("iv_percentile") or 0) < rules["minimum_iv_percentile"]:
        blockers.append("IV_PERCENTILE_INSUFFICIENT")
    if float(candidate.get("iv_to_realized_ratio") or 0) < rules["minimum_iv_to_realized_ratio"] or float(candidate.get("iv_minus_realized_points") or 0) < rules["minimum_iv_minus_realized_points"]:
        blockers.append("VOLATILITY_RISK_PREMIUM_INSUFFICIENT")
    if float(candidate.get("bid_ask_spread_pct") or 999) > rules["maximum_bid_ask_spread_pct"] or int(candidate.get("open_interest") or 0) < rules["minimum_open_interest"]:
        blockers.append("OPTIONS_LIQUIDITY_INSUFFICIENT")
    if not candidate.get("cash_secured_or_stress_margin"):
        blockers.append("STRESS_MARGIN_UNAVAILABLE")
    if float(candidate.get("cycle_capacity_pct") or 999) > rules["maximum_cycle_capacity_pct"]:
        blockers.append("CYCLE_CAPACITY_TOO_HIGH")
    if float(candidate.get("aggregate_spy_rsp_exposure_pct") or 999) > rules["maximum_aggregate_spy_rsp_exposure_pct"]:
        blockers.append("AGGREGATE_SPY_RSP_EXPOSURE_TOO_HIGH")
    return _result("RESEARCH_BLOCKED" if blockers else "RESEARCH_CANDIDATE", blockers, dict(candidate))


def evaluate_backtest_sample(
    trades: Iterable[dict[str, Any]],
    strategy_id: str,
    *,
    starting_capital: float,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    gate = config["promotion_gate"]
    rows = [row for row in trades if row.get("closed", True)]
    pnls = [float(row.get("pnl") or 0) for row in rows]
    blockers: list[str] = []
    wins = sum(value > 0 for value in pnls)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    equity = peak = float(starting_capital)
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    oos_count = sum(bool(row.get("out_of_sample")) for row in rows)
    years = {str(row.get("date") or "")[:4] for row in rows if str(row.get("date") or "")[:4].isdigit()}
    regimes = {str(row.get("regime") or "").upper() for row in rows}
    stress_periods = {str(row.get("stress_period") or "") for row in rows if row.get("stress_period")}
    if len(rows) < gate["minimum_closed_trades"]:
        blockers.append("INSUFFICIENT_CLOSED_TRADES")
    if oos_count < gate["minimum_out_of_sample_trades"]:
        blockers.append("INSUFFICIENT_OUT_OF_SAMPLE_TRADES")
    if len(years) < gate["minimum_distinct_years"]:
        blockers.append("INSUFFICIENT_TIME_COVERAGE")
    if not set(gate["minimum_regimes"]).issubset(regimes):
        blockers.append("MARKET_REGIMES_INCOMPLETE")
    if not set(gate["required_stress_periods"]).issubset(stress_periods):
        blockers.append("STRESS_HISTORY_INCOMPLETE")
    if profit_factor < gate["minimum_profit_factor"]:
        blockers.append("PROFIT_FACTOR_INSUFFICIENT")
    if max_drawdown > gate["maximum_drawdown_pct"]:
        blockers.append("MAX_DRAWDOWN_EXCEEDS_LIMIT")
    evidence = {
        "strategy_id": strategy_id,
        "closed_trades": len(rows),
        "out_of_sample_trades": oos_count,
        "distinct_years": len(years),
        "regimes": sorted(regimes),
        "stress_periods": sorted(stress_periods),
        "total_pnl": round(sum(pnls), 2),
        "win_rate_pct": round(wins / len(rows) * 100, 2) if rows else 0.0,
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "INF",
        "max_drawdown_pct": round(max_drawdown, 2),
    }
    return _result("RESEARCH_BLOCKED" if blockers else "PAPER_ELIGIBLE", blockers, evidence)
