"""IBKR multi-account reader that excludes real account identifiers from output."""

from __future__ import annotations

from copy import copy
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

    @staticmethod
    def _position_key(position: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(position.get("ticker") or "UNKNOWN").upper(),
            str(position.get("security_type") or "UNKNOWN").upper(),
            str(position.get("expiration") or ""),
            str(control_tower.safe_float(position.get("strike")) or 0),
            str(position.get("right") or "").upper(),
        )

    @staticmethod
    def _contract_key(contract: Any) -> tuple[str, str, str, str, str]:
        return (
            str(getattr(contract, "symbol", None) or getattr(contract, "localSymbol", None) or "UNKNOWN").upper(),
            str(getattr(contract, "secType", None) or "UNKNOWN").upper(),
            str(getattr(contract, "lastTradeDateOrContractMonth", None) or ""),
            str(control_tower.safe_float(getattr(contract, "strike", None)) or 0),
            str(getattr(contract, "right", None) or "").upper(),
        )

    @staticmethod
    def _option_greeks(ticker: Any) -> dict[str, float | None]:
        greeks = (
            getattr(ticker, "modelGreeks", None)
            or getattr(ticker, "bidGreeks", None)
            or getattr(ticker, "askGreeks", None)
            or getattr(ticker, "lastGreeks", None)
        )
        return {
            "implied_volatility": control_tower.safe_float(getattr(greeks, "impliedVol", None)),
            "delta": control_tower.safe_float(getattr(greeks, "delta", None)),
            "gamma": control_tower.safe_float(getattr(greeks, "gamma", None)),
            "theta": control_tower.safe_float(getattr(greeks, "theta", None)),
            "vega": control_tower.safe_float(getattr(greeks, "vega", None)),
        }

    @staticmethod
    def _historical_closes(ib: Any, contract: Any) -> list[float]:
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="6 M",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            )
        except Exception:
            return []
        values = []
        for bar in (bars or [])[-130:]:
            close = control_tower.safe_float(getattr(bar, "close", None))
            if close is not None and close > 0:
                values.append(close)
        return values

    @classmethod
    def _enrich_positions(
        cls,
        ib: Any,
        clean: list[dict[str, Any]],
        contracts: dict[tuple[str, str, str, str, str], Any],
        history_cache: dict[str, list[float]],
    ) -> list[dict[str, Any]]:
        try:
            from ib_insync import Stock
        except Exception:
            Stock = None
        for position in clean:
            key = cls._position_key(position)
            contract = contracts.get(key)
            ticker = key[0]
            if ticker not in history_cache:
                history_contract = contract
                if Stock is not None:
                    history_contract = Stock(ticker, "SMART", str(position.get("currency") or "USD"))
                history_cache[ticker] = cls._historical_closes(ib, history_contract) if history_contract is not None else []
            position["historical_closes"] = list(history_cache.get(ticker) or [])
            if key[1] not in {"OPT", "FOP"} or contract is None:
                continue
            try:
                quote_contract = copy(contract)
                if key[1] == "OPT" and not str(getattr(quote_contract, "exchange", "") or "").strip():
                    quote_contract.exchange = "SMART"
                quote_rows = ib.reqTickers(quote_contract)
                quote = quote_rows[0] if quote_rows else None
                if quote is not None:
                    position.update(cls._option_greeks(quote))
            except Exception:
                pass
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
            ib.RequestTimeout = max(1.0, min(self.timeout, 5.0))
            managed = {str(value).strip() for value in ib.managedAccounts() or []}
            summary = list(ib.accountSummary() or [])
            positions = list(ib.positions() or [])
            output = {}
            history_cache: dict[str, list[float]] = {}
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
                portfolio_rows = []
                try:
                    # accountSummary/positions do not necessarily populate
                    # PortfolioItem market values in multi-account sessions.
                    # This is still a read-only subscription and places no orders.
                    ib.reqAccountUpdates(account_id)
                    portfolio_rows = list(ib.portfolio(account_id) or [])
                except Exception:
                    portfolio_rows = []
                finally:
                    try:
                        ib.client.reqAccountUpdates(False, account_id)
                    except Exception:
                        pass
                source_rows = portfolio_rows or [row for row in positions if str(getattr(row, "account", "") or "").strip() == account_id]
                contracts = {
                    self._contract_key(getattr(row, "contract", None)): getattr(row, "contract", None)
                    for row in source_rows
                    if getattr(row, "contract", None) is not None
                }
                clean_positions = (
                    self._portfolio_positions(portfolio_rows, account_id)
                    or self._positions(positions, account_id)
                )
                clean_positions = self._enrich_positions(ib, clean_positions, contracts, history_cache)
                output[alias] = control_tower.account_snapshot(
                    broker=self.broker,
                    alias=alias,
                    scope=item["account_scope"],
                    capacity=self._summary_capacity(summary, account_id),
                    positions=clean_positions,
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
