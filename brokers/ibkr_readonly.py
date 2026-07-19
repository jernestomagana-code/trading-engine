"""IBKR multi-account reader that excludes real account identifiers from output."""

from __future__ import annotations

from typing import Any

import broker_control_tower as control_tower


SUMMARY_FIELDS = {
    "NetLiquidation": "net_liquidation",
    "BuyingPower": "buying_power",
    "AvailableFunds": "available_funds",
    "ExcessLiquidity": "excess_liquidity",
    "TotalCashValue": "total_cash_value",
    "InitMarginReq": "initial_margin_required",
    "MaintMarginReq": "maintenance_margin_required",
    "GrossPositionValue": "gross_position_value",
}


class IBKRReadOnlyAdapter:
    broker = "IBKR"

    def __init__(self, host: str = "127.0.0.1", port: int = 7496, client_id: int = 84, timeout: float = 20):
        self.host = host
        self.port = int(port)
        self.client_id = int(client_id)
        self.timeout = float(timeout)

    @staticmethod
    def _safe_error(error: Exception, accounts: list[dict[str, str]]) -> str:
        message = f"{type(error).__name__}: {error}"
        for item in accounts:
            account_id = str(item.get("account_id") or "")
            if account_id:
                message = message.replace(account_id, "[ACCOUNT_ID_REDACTED]")
        return message

    @staticmethod
    def _summary_capacity(rows: list[Any], account_id: str) -> dict[str, Any]:
        capacity: dict[str, Any] = {"currency": "USD"}
        preferred = []
        fallback = []
        for row in rows or []:
            if str(getattr(row, "account", "") or "").strip() not in {"", account_id}:
                continue
            field = SUMMARY_FIELDS.get(getattr(row, "tag", None))
            if not field:
                continue
            currency = str(getattr(row, "currency", "") or "").upper()
            target = preferred if currency in {"", "BASE", "USD"} else fallback
            target.append((field, getattr(row, "value", None), currency))
        for field, value, currency in preferred + fallback:
            if capacity.get(field) is not None:
                continue
            parsed = control_tower.safe_float(value)
            if parsed is not None:
                capacity[field] = parsed
                if currency:
                    capacity["currency"] = currency
        capacity["available_capacity"] = capacity.get("available_funds")
        return capacity

    @staticmethod
    def _positions(rows: list[Any], account_id: str) -> list[dict[str, Any]]:
        clean = []
        for row in rows or []:
            if str(getattr(row, "account", "") or "").strip() != account_id:
                continue
            contract = getattr(row, "contract", None)
            clean.append({
                "ticker": getattr(contract, "symbol", None) or getattr(contract, "localSymbol", None) or "UNKNOWN",
                "security_type": getattr(contract, "secType", None) or "UNKNOWN",
                "currency": getattr(contract, "currency", None) or "",
                "quantity": getattr(row, "position", None),
                "average_cost": getattr(row, "avgCost", None),
                "strike": getattr(contract, "strike", None),
                "expiration": getattr(contract, "lastTradeDateOrContractMonth", None) or "",
                "right": getattr(contract, "right", None) or "",
                "multiplier": getattr(contract, "multiplier", None) or "",
            })
        return clean

    @staticmethod
    def _portfolio_positions(rows: list[Any], account_id: str) -> list[dict[str, Any]]:
        """Normalize IBKR PortfolioItem rows while excluding the real account id."""
        clean = []
        for row in rows or []:
            row_account = str(getattr(row, "account", "") or "").strip()
            if row_account and row_account != account_id:
                continue
            contract = getattr(row, "contract", None)
            clean.append({
                "ticker": getattr(contract, "symbol", None) or getattr(contract, "localSymbol", None) or "UNKNOWN",
                "security_type": getattr(contract, "secType", None) or "UNKNOWN",
                "currency": getattr(contract, "currency", None) or "",
                "quantity": getattr(row, "position", None),
                "average_cost": getattr(row, "averageCost", None),
                "market_price": getattr(row, "marketPrice", None),
                "market_value": getattr(row, "marketValue", None),
                "unrealized_pl": getattr(row, "unrealizedPNL", None),
                "strike": getattr(contract, "strike", None),
                "expiration": getattr(contract, "lastTradeDateOrContractMonth", None) or "",
                "right": getattr(contract, "right", None) or "",
                "multiplier": getattr(contract, "multiplier", None) or "",
            })
        return clean

    def collect(self, accounts: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        try:
            from ib_insync import IB
        except Exception as exc:
            return {
                item["account_alias"]: control_tower.account_snapshot(
                    broker=self.broker,
                    alias=item["account_alias"],
                    scope=item["account_scope"],
                    status="IB_INSYNC_IMPORT_FAILED",
                    error=str(exc),
                )
                for item in accounts
            }
        ib = IB()
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, readonly=True, timeout=self.timeout)
            managed = {str(value).strip() for value in ib.managedAccounts() or []}
            summary = list(ib.accountSummary() or [])
            positions = list(ib.positions() or [])
            output = {}
            for item in accounts:
                alias = item["account_alias"]
                account_id = item["account_id"]
                if account_id not in managed:
                    output[alias] = control_tower.account_snapshot(
                        broker=self.broker,
                        alias=alias,
                        scope=item["account_scope"],
                        status="ACCOUNT_NOT_VISIBLE",
                        error="Configured account is not visible in the current TWS/IB Gateway session.",
                    )
                    continue
                output[alias] = control_tower.account_snapshot(
                    broker=self.broker,
                    alias=alias,
                    scope=item["account_scope"],
                    capacity=self._summary_capacity(summary, account_id),
                    positions=(
                        self._portfolio_positions(ib.portfolio(account_id), account_id)
                        or self._positions(positions, account_id)
                    ),
                )
            return output
        except Exception as exc:
            return {
                item["account_alias"]: control_tower.account_snapshot(
                    broker=self.broker,
                    alias=item["account_alias"],
                    scope=item["account_scope"],
                    status="BROKER_REFRESH_FAILED",
                    error=self._safe_error(exc, accounts),
                )
                for item in accounts
            }
        finally:
            try:
                if ib.isConnected():
                    ib.disconnect()
            except Exception:
                pass
