import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import broker_control_tower as tower
from brokers.ibkr_readonly import IBKRReadOnlyAdapter
from scripts import ibkr_account_profile as account_console


class BrokerControlTowerTests(unittest.TestCase):
    def test_registry_is_sanitized_and_has_no_default_account(self):
        registry = tower.build_registry(
            {
                "remanente": {"alias": "remanente", "account_scope": "remanente", "keychain_service": "secret-a"},
                "retiro": {"alias": "retiro", "account_scope": "retiro", "keychain_service": "secret-b"},
            },
            active_alias="remanente",
            keychain_ready={"remanente": True, "retiro": True},
        )

        encoded = json.dumps(registry)
        self.assertEqual(registry["account_count"], 2)
        self.assertFalse(registry["ambiguous_default_account"])
        self.assertTrue(registry["sensitive_identifiers_excluded"])
        self.assertNotIn("keychain_service", encoded)
        self.assertNotIn('"account_id":', encoded)

    def test_consolidation_keeps_accounts_isolated_and_sums_capacity(self):
        generated = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        registry = tower.build_registry(
            {
                "marginal": {"alias": "marginal", "account_scope": "marginal"},
                "remanente": {"alias": "remanente", "account_scope": "remanente"},
            },
            active_alias="remanente",
        )
        snapshots = {
            "marginal": tower.account_snapshot(
                broker="IBKR", alias="marginal", scope="marginal",
                capacity={"net_liquidation": 10000, "available_funds": 4000, "buying_power": 16000},
                positions=[{"ticker": "QQQ", "security_type": "STK", "quantity": 10, "average_cost": 500}],
                generated_at=generated.isoformat(),
            ),
            "remanente": tower.account_snapshot(
                broker="IBKR", alias="remanente", scope="remanente",
                capacity={"net_liquidation": 15.76, "available_funds": 15.76, "buying_power": 15.76},
                positions=[{"ticker": "QQQ", "security_type": "STK", "quantity": 2, "average_cost": 510}],
                generated_at=generated.isoformat(),
            ),
        }

        payload = tower.consolidate(registry, snapshots, reference=generated + timedelta(minutes=1))

        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["ready_account_count"], 2)
        self.assertEqual(payload["consolidated_capacity"]["net_liquidation"], 10015.76)
        self.assertEqual(payload["consolidated_capacity"]["available_funds"], 4015.76)
        self.assertEqual(payload["consolidated_positions"][0]["quantity"], 12.0)
        self.assertEqual(payload["consolidated_positions"][0]["account_aliases"], ["marginal", "remanente"])
        aliases = {row["account_alias"] for row in payload["accounts"]}
        self.assertEqual(aliases, {"marginal", "remanente"})

    def test_stale_or_missing_account_prevents_ready(self):
        reference = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        registry = tower.build_registry({
            "marginal": {"alias": "marginal"},
            "retiro": {"alias": "retiro"},
        })
        snapshots = {
            "marginal": tower.account_snapshot(
                broker="IBKR", alias="marginal", scope="marginal",
                capacity={"net_liquidation": 100},
                generated_at=(reference - timedelta(minutes=40)).isoformat(),
            ),
        }

        payload = tower.consolidate(registry, snapshots, max_age_minutes=15, reference=reference)

        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["stale_account_count"], 1)
        self.assertEqual(payload["failed_account_count"], 1)
        self.assertIn("STALE_ACCOUNT_SNAPSHOTS", payload["warnings"])
        self.assertIn("ACCOUNT_REFRESH_INCOMPLETE", payload["warnings"])

    def test_ready_snapshot_without_capacity_fails_closed(self):
        snapshot = tower.account_snapshot(
            broker="IBKR", alias="marginal", scope="marginal", capacity={}, status="READY"
        )

        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["status"], "CAPACITY_UNAVAILABLE")

    def test_snapshot_files_are_partitioned_by_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            snapshot = tower.account_snapshot(
                broker="IBKR", alias="retiro", scope="retiro",
                capacity={"net_liquidation": 500},
            )
            path = tower.write_snapshot(runtime, snapshot)
            registry = tower.build_registry({"retiro": {"alias": "retiro"}})
            loaded = tower.load_snapshots(runtime, registry)

        self.assertTrue(str(path).endswith("accounts/retiro/account_snapshot.json"))
        self.assertEqual(loaded["retiro"]["account_alias"], "retiro")

    def test_ibkr_normalizers_filter_by_real_account_without_persisting_it(self):
        summary = [
            SimpleNamespace(account="REAL_A", tag="NetLiquidation", value="1000", currency="USD"),
            SimpleNamespace(account="REAL_B", tag="NetLiquidation", value="9000", currency="USD"),
            SimpleNamespace(account="REAL_A", tag="AvailableFunds", value="400", currency="USD"),
        ]
        contract = SimpleNamespace(
            symbol="SPY", localSymbol="SPY", secType="STK", currency="USD",
            strike=0, lastTradeDateOrContractMonth="", right="", multiplier="",
        )
        positions = [
            SimpleNamespace(account="REAL_A", contract=contract, position=3, avgCost=500),
            SimpleNamespace(account="REAL_B", contract=contract, position=99, avgCost=500),
        ]

        capacity = IBKRReadOnlyAdapter._summary_capacity(summary, "REAL_A")
        clean_positions = IBKRReadOnlyAdapter._positions(positions, "REAL_A")
        snapshot = tower.account_snapshot(
            broker="IBKR", alias="primary", scope="primary",
            capacity=capacity, positions=clean_positions,
        )

        encoded = json.dumps(snapshot)
        self.assertEqual(snapshot["capacity"]["net_liquidation"], 1000.0)
        self.assertEqual(snapshot["positions"][0]["quantity"], 3.0)
        self.assertNotIn("REAL_A", encoded)
        self.assertNotIn("REAL_B", encoded)
        self.assertTrue(snapshot["real_account_id_excluded"])

    def test_broker_errors_redact_real_account_identifiers(self):
        error = RuntimeError("subscription failed for REAL_A")
        sanitized = IBKRReadOnlyAdapter._safe_error(
            error,
            [{"account_id": "REAL_A", "account_alias": "primary", "account_scope": "primary"}],
        )

        self.assertNotIn("REAL_A", sanitized)
        self.assertIn("[ACCOUNT_ID_REDACTED]", sanitized)

    def test_futures_history_uses_exact_contract_and_expiration(self):
        future_contract = SimpleNamespace(
            symbol="MES", localSymbol="MESU6", secType="FUT", currency="USD",
            strike=0, lastTradeDateOrContractMonth="20260918", right="0",
            multiplier="5", exchange="", primaryExchange="",
        )
        clean = [{
            "ticker": "MES", "security_type": "FUT", "currency": "USD",
            "quantity": -1, "expiration": "20260918", "strike": 0,
            "right": "0", "multiplier": "5",
        }]

        class FakeIB:
            def __init__(self):
                self.requested_contracts = []

            def reqHistoricalData(self, contract, **kwargs):
                self.requested_contracts.append(contract)
                return [SimpleNamespace(close=6000), SimpleNamespace(close=6010)]

        ib = FakeIB()
        contracts = {IBKRReadOnlyAdapter._contract_key(future_contract): future_contract}
        enriched = IBKRReadOnlyAdapter._enrich_positions(ib, clean, contracts, {})

        self.assertIsNot(ib.requested_contracts[0], future_contract)
        self.assertEqual(ib.requested_contracts[0].exchange, "CME")
        self.assertEqual(ib.requested_contracts[0].lastTradeDateOrContractMonth, "20260918")
        self.assertEqual(enriched[0]["historical_closes"], [6000.0, 6010.0])

    def test_refresh_script_preserves_no_order_guardrails(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "refresh_multi_account_control_tower.py").read_text()
        self.assertIn("IBKRReadOnlyAdapter", source)
        self.assertIn('"execution_authorized": False', source)
        self.assertIn('"not_order_instruction": True', source)
        self.assertNotIn("placeOrder", source)

    def test_console_renders_control_tower_and_safe_refresh_action(self):
        generated = datetime.now(timezone.utc)
        registry = tower.build_registry({
            "marginal": {"alias": "marginal", "account_scope": "marginal"},
            "remanente": {"alias": "remanente", "account_scope": "remanente"},
        }, active_alias="remanente")
        snapshots = {
            alias: tower.account_snapshot(
                broker="IBKR", alias=alias, scope=alias,
                capacity={"net_liquidation": 100, "available_funds": 50, "buying_power": 200},
                generated_at=generated.isoformat(),
            )
            for alias in ["marginal", "remanente"]
        }
        payload = tower.consolidate(registry, snapshots, reference=generated)
        with tempfile.TemporaryDirectory() as tmp:
            original = account_console.CONTROL_TOWER_PATH
            original_runtime = account_console.RUNTIME
            account_console.RUNTIME = Path(tmp)
            account_console.CONTROL_TOWER_PATH = account_console.RUNTIME / "tower.json"
            account_console.CONTROL_TOWER_PATH.write_text(json.dumps(payload))
            for snapshot in snapshots.values():
                tower.write_snapshot(account_console.RUNTIME, snapshot)
            try:
                rendered = account_console.render_control_tower_panel(
                    {row["account_alias"]: row for row in registry["accounts"]},
                    {"account_alias": "remanente"},
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.CONTROL_TOWER_PATH = original

        self.assertIn("Control Tower multi-cuenta", rendered)
        self.assertIn("marginal", rendered)
        self.assertIn("remanente", rendered)
        self.assertIn("$200.00", rendered)
        self.assertIn('/control-tower-refresh', rendered)
        self.assertIn("no coloca ordenes", rendered)

    def test_console_exposes_control_tower_json_route(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/control-tower"', source)
        self.assertIn('self.path == "/control-tower-refresh"', source)
        self.assertIn("control_tower_refresh_command", source)
        self.assertIn("job-command", source)


if __name__ == "__main__":
    unittest.main()
